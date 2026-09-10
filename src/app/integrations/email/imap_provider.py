"""IMAP/SMTP provider with TLS, bounded I/O, and retry-safe async wrappers."""

import asyncio
import email
import imaplib
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from typing import List, Optional

from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException, IntegrationException
from src.app.core.logging import logger
from src.app.core.retry import retry_async
from src.app.integrations.email.base import EmailProvider
from src.app.schemas.email import EmailDraftReply, EmailFilterParams, EmailMessageSchema


class IMAPEmailProvider(EmailProvider):
    """Access a configured personal or UNITBV IMAP/SMTP mailbox."""

    def __init__(self, account_type: str = "personal"):
        self.account_type = account_type.lower()
        prefix = "UNITBV_EMAIL" if self.account_type == "unitbv" else "EMAIL"
        self.email_address = getattr(settings, f"{prefix}_ACCOUNT")
        self.password = getattr(settings, f"{prefix}_PASSWORD")
        self.imap_server = getattr(settings, f"{prefix}_IMAP_SERVER")
        self.imap_port = int(getattr(settings, f"{prefix}_IMAP_PORT"))
        self.imap_folder = getattr(settings, f"{prefix}_IMAP_FOLDER")
        self.imap_use_ssl = bool(getattr(settings, f"{prefix}_IMAP_USE_SSL"))
        self.smtp_server = getattr(settings, f"{prefix}_SMTP_SERVER")
        self.smtp_port = int(getattr(settings, f"{prefix}_SMTP_PORT"))
        self.smtp_use_starttls = bool(getattr(settings, f"{prefix}_SMTP_USE_STARTTLS"))

    def _is_configured(self) -> bool:
        values = [self.email_address, self.password, self.imap_server, self.smtp_server]
        return bool(all(values)) and not any("your-" in str(value) for value in values)

    async def fetch_emails(
        self, account_type: str, filter_params: Optional[EmailFilterParams] = None
    ) -> List[EmailMessageSchema]:
        self._require_configuration()
        try:
            return await retry_async(
                lambda: asyncio.to_thread(self._fetch_emails_sync, filter_params),
                operation_name=f"imap_fetch:{self.account_type}",
            )
        except Exception as exc:
            raise IntegrationException(f"Failed to fetch {self.account_type} emails via IMAP: {exc}") from exc

    async def get_email_by_id(self, account_type: str, message_id: str) -> Optional[EmailMessageSchema]:
        emails = await self.fetch_emails(account_type, EmailFilterParams(limit=100))
        return next((item for item in emails if item.message_id == message_id), None)

    async def send_email(self, account_type: str, draft: EmailDraftReply) -> bool:
        self._require_configuration()
        try:
            # A timeout can occur after SMTP accepted a message; retrying blindly could send duplicates.
            return await asyncio.wait_for(
                asyncio.to_thread(self._send_email_sync, draft),
                timeout=settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise IntegrationException(f"Failed to send email via SMTP: {exc}") from exc

    def _require_configuration(self) -> None:
        if not self._is_configured():
            raise ConfigurationException(
                f"IMAP/SMTP settings for '{self.account_type}' are incomplete; configure them in .env."
            )

    def _fetch_emails_sync(self, filter_params: Optional[EmailFilterParams]) -> List[EmailMessageSchema]:
        mail = self._open_imap_connection()
        try:
            status, _ = mail.select(self.imap_folder, readonly=True)
            if status != "OK":
                raise IntegrationException(f"Cannot select IMAP folder '{self.imap_folder}'")

            status, messages = mail.search(None, *self._search_criteria(filter_params))
            if status != "OK":
                raise IntegrationException("IMAP search failed")

            limit = min(max((filter_params.limit if filter_params else 10), 1), 100)
            message_ids = messages[0].split()[-limit:]
            results: List[EmailMessageSchema] = []
            for imap_id in reversed(message_ids):
                status, data = mail.fetch(imap_id, "(RFC822)")
                if status != "OK":
                    logger.warning("Skipping email %s because IMAP fetch failed", imap_id)
                    continue
                raw_message = next((part[1] for part in data if isinstance(part, tuple)), None)
                if raw_message:
                    results.append(self._parse_message(raw_message, imap_id.decode("ascii", errors="replace")))
            return results
        finally:
            try:
                mail.logout()
            except Exception:
                pass

    def _open_imap_connection(self):
        timeout = settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS
        ssl_context = ssl.create_default_context()
        if self.imap_use_ssl:
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port, ssl_context=ssl_context, timeout=timeout)
        else:
            mail = imaplib.IMAP4(self.imap_server, self.imap_port, timeout=timeout)
            mail.starttls(ssl_context=ssl_context)
        mail.login(self.email_address, self.password)
        return mail

    def _search_criteria(self, filter_params: Optional[EmailFilterParams]) -> list[str]:
        if not filter_params:
            return ["ALL"]
        criteria: list[str] = ["ALL"]
        if filter_params.is_important_only:
            criteria.append("FLAGGED")
        if filter_params.sender:
            criteria.extend(["FROM", self._imap_quote(filter_params.sender)])
        if filter_params.subject:
            criteria.extend(["SUBJECT", self._imap_quote(filter_params.subject)])
        if filter_params.keywords:
            for keyword in filter_params.keywords:
                criteria.extend(["TEXT", self._imap_quote(keyword)])
        since = filter_params.date_from
        if not since and filter_params.days_back:
            since = datetime.now(timezone.utc) - timedelta(days=filter_params.days_back)
        if since:
            criteria.extend(["SINCE", since.strftime("%d-%b-%Y")])
        if filter_params.date_to:
            criteria.extend(["BEFORE", (filter_params.date_to + timedelta(days=1)).strftime("%d-%b-%Y")])
        return criteria

    @staticmethod
    def _imap_quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _parse_message(self, raw_message: bytes, fallback_id: str) -> EmailMessageSchema:
        message = email.message_from_bytes(raw_message)
        subject = str(make_header(decode_header(message.get("Subject", ""))))
        sender = str(make_header(decode_header(message.get("From", ""))))
        recipients = [item.strip() for item in (message.get("To") or "").split(",") if item.strip()]
        received_at = self._parse_date(message.get("Date"))
        body = self._extract_text_body(message)
        return EmailMessageSchema(
            message_id=message.get("Message-ID") or fallback_id,
            account_type=self.account_type,
            sender=sender,
            recipients=recipients,
            subject=subject,
            body_text=body[:10000],
            received_at=received_at,
            importance="high" if "important" in subject.lower() else "medium",
        )

    @staticmethod
    def _parse_date(raw_date: Optional[str]) -> datetime:
        if raw_date:
            try:
                parsed = parsedate_to_datetime(raw_date)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _extract_text_body(message) -> str:
        parts = message.walk() if message.is_multipart() else [message]
        for part in parts:
            if part.get_content_type() != "text/plain" or part.get_content_disposition() == "attachment":
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""

    def _send_email_sync(self, draft: EmailDraftReply) -> bool:
        message = MIMEText(draft.body, "plain", "utf-8")
        message["Subject"] = draft.subject
        message["From"] = self.email_address
        message["To"] = draft.recipient
        timeout = settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS
        ssl_context = ssl.create_default_context()
        with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=timeout) as server:
            server.ehlo()
            if self.smtp_use_starttls:
                server.starttls(context=ssl_context)
                server.ehlo()
            server.login(self.email_address, self.password)
            server.sendmail(self.email_address, [draft.recipient], message.as_string())
        logger.info("Sent email through %s SMTP after explicit approval.", self.account_type)
        return True
