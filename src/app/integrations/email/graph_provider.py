"""Microsoft 365 / Microsoft Graph API Email Provider.

Implements the EmailProvider interface using Microsoft Graph REST API v1.0,
supporting OAuth2 Client Credentials grant, token caching, throttling/retry
handling, and safe redaction of sensitive credentials.
"""

import asyncio
import html
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException, IntegrationException
from src.app.core.logging import logger
from src.app.core.practice_config import get_practice_keywords
from src.app.integrations.email.base import EmailProvider
from src.app.schemas.email import EmailDraftReply, EmailFilterParams, EmailMessageSchema


class MicrosoftGraphEmailProvider(EmailProvider):
    """Access a UNITBV or organizational Microsoft 365 mailbox via Microsoft Graph API."""

    def __init__(self, account_type: str = "unitbv"):
        self.account_type = account_type.lower()
        self.endpoint = settings.MICROSOFT_GRAPH_ENDPOINT.rstrip("/")
        self.tenant_id = settings.MICROSOFT_TENANT_ID
        self.client_id = settings.MICROSOFT_CLIENT_ID
        self.client_secret = settings.MICROSOFT_CLIENT_SECRET
        self.scopes = settings.MICROSOFT_SCOPES
        self.mailbox_address = settings.MICROSOFT_MAILBOX_ADDRESS or settings.UNITBV_EMAIL_ACCOUNT
        self.static_token = settings.MICROSOFT_ACCESS_TOKEN

        self._cached_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._lock = asyncio.Lock()

    def _is_configured(self) -> bool:
        """Check if minimum required credentials to call Graph API are present."""
        if not self.mailbox_address or self._is_placeholder(self.mailbox_address):
            return False

        if self.static_token and not self._is_placeholder(self.static_token):
            return True

        oauth_fields = [self.tenant_id, self.client_id, self.client_secret]
        return bool(all(oauth_fields)) and not any(self._is_placeholder(f) for f in oauth_fields)

    @staticmethod
    def _is_placeholder(val: Optional[str]) -> bool:
        if not val:
            return True
        val_lower = str(val).strip().lower()
        return (
            val_lower.startswith("your-")
            or val_lower.startswith("<")
            or val_lower.startswith("replace-")
            or "placeholder" in val_lower
        )

    def _require_configuration(self) -> None:
        if not self._is_configured():
            raise ConfigurationException(
                f"Microsoft Graph settings for '{self.account_type}' are incomplete. "
                "Configure MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, "
                "and MICROSOFT_MAILBOX_ADDRESS (or UNITBV_EMAIL_ACCOUNT) in .env."
            )

    async def _get_access_token(self) -> str:
        """Acquire or return cached OAuth2 access token for Microsoft Graph."""
        if self.static_token and not self._is_placeholder(self.static_token):
            return self.static_token

        async with self._lock:
            # Re-check under lock in case another coroutine refreshed the token
            now = time.time()
            if self._cached_token and now < (self._token_expires_at - 60):
                return self._cached_token

            token_url = f"https://login.microsoftonline.com/{quote(self.tenant_id or '')}/oauth2/v2.0/token"
            payload = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
                "scope": self.scopes,
            }

            timeout = min(settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS, 30.0)
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(token_url, data=payload)
            except Exception as exc:
                raise IntegrationException(
                    f"Failed to connect to Microsoft Identity Platform token endpoint: {type(exc).__name__}"
                ) from exc

            if resp.status_code != 200:
                # Do not log or expose the secret; log only the safe status code and error description
                error_info = "authentication failure"
                try:
                    err_json = resp.json()
                    error_info = err_json.get("error_description", err_json.get("error", "token request failed"))
                except Exception:
                    pass
                raise IntegrationException(
                    f"Failed to acquire Microsoft Graph OAuth2 token (HTTP {resp.status_code}): {error_info}"
                )

            token_data = resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise IntegrationException("Microsoft token response did not contain an access_token.")

            expires_in = float(token_data.get("expires_in", 3600))
            self._cached_token = access_token
            self._token_expires_at = time.time() + expires_in
            logger.info("Acquired fresh Microsoft Graph OAuth2 token (expires in %ds).", int(expires_in))
            return self._cached_token

    def _get_user_path(self) -> str:
        """Build Graph base path for the mailbox."""
        if self.mailbox_address:
            return f"/users/{quote(self.mailbox_address)}"
        return "/me"

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """Perform an authorized Graph HTTP request with rate-limiting backoff and retries."""
        attempts = max(1, settings.EXTERNAL_RETRY_ATTEMPTS + 1)
        timeout = settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS

        for attempt in range(1, attempts + 1):
            token = await self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
            if json_data is not None:
                headers["Content-Type"] = "application/json"

            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.request(method, url, headers=headers, params=params, json=json_data)
            except Exception as exc:
                if attempt == attempts:
                    raise IntegrationException(
                        f"Microsoft Graph request failed after {attempts} attempts: {type(exc).__name__}"
                    ) from exc
                await asyncio.sleep(0.5 * attempt)
                continue

            # Handle throttling (HTTP 429 Too Many Requests)
            if resp.status_code == 429 or resp.status_code in (503, 504):
                if attempt < attempts:
                    retry_after_header = resp.headers.get("Retry-After")
                    try:
                        wait_seconds = float(retry_after_header) if retry_after_header else (1.0 * attempt)
                    except ValueError:
                        wait_seconds = 1.0 * attempt
                    wait_seconds = min(wait_seconds, 10.0)
                    logger.warning(
                        "Microsoft Graph throttled request (HTTP %d). Backing off for %.1fs (attempt %d/%d).",
                        resp.status_code,
                        wait_seconds,
                        attempt,
                        attempts,
                    )
                    await asyncio.sleep(wait_seconds)
                    continue

            return resp

        raise IntegrationException(f"Microsoft Graph request exceeded maximum retry attempts ({attempts}).")

    async def fetch_emails(
        self, account_type: str, filter_params: Optional[EmailFilterParams] = None
    ) -> List[EmailMessageSchema]:
        """Fetch emails from Microsoft Graph inbox."""
        self._require_configuration()

        url = f"{self.endpoint}{self._get_user_path()}/mailFolders/inbox/messages"
        limit = min(max((filter_params.limit if filter_params else 10), 1), 100)

        query_params: Dict[str, str] = {
            "$top": str(limit),
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,bodyPreview,body,from,toRecipients,receivedDateTime,importance,isRead",
        }

        # Build Graph $filter if parameters are specified
        filter_clauses = []
        if filter_params:
            if filter_params.is_important_only:
                filter_clauses.append("importance eq 'high'")
            if filter_params.sender:
                # Graph filter by sender address
                clean_sender = filter_params.sender.replace("'", "''")
                filter_clauses.append(f"from/emailAddress/address eq '{clean_sender}'")
            if filter_params.date_from:
                filter_clauses.append(
                    f"receivedDateTime ge {filter_params.date_from.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                )
            if filter_params.date_to:
                filter_clauses.append(
                    f"receivedDateTime le {filter_params.date_to.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                )

        if filter_clauses:
            query_params["$filter"] = " and ".join(filter_clauses)

        resp = await self._request_with_retry("GET", url, params=query_params)
        if resp.status_code != 200:
            err_msg = f"HTTP {resp.status_code}"
            try:
                err_data = resp.json()
                err_msg = err_data.get("error", {}).get("message", err_msg)
            except Exception:
                pass
            raise IntegrationException(f"Failed to fetch emails via Microsoft Graph API: {err_msg}")

        data = resp.json()
        messages_raw = data.get("value", [])

        results: List[EmailMessageSchema] = []
        for msg in messages_raw:
            parsed = self._parse_graph_message(msg)
            # Apply client-side keyword filtering if requested
            if filter_params and filter_params.keywords:
                content_lower = f"{parsed.subject} {parsed.body_text}".lower()
                if not any(kw.lower() in content_lower for kw in filter_params.keywords):
                    continue
            results.append(parsed)

        return results

    async def get_email_by_id(self, account_type: str, message_id: str) -> Optional[EmailMessageSchema]:
        """Fetch a specific email message by its Graph message ID."""
        self._require_configuration()

        url = f"{self.endpoint}{self._get_user_path()}/messages/{quote(message_id)}"
        query_params = {
            "$select": "id,subject,bodyPreview,body,from,toRecipients,receivedDateTime,importance,isRead",
        }

        resp = await self._request_with_retry("GET", url, params=query_params)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise IntegrationException(
                f"Microsoft Graph error retrieving email '{message_id}' (HTTP {resp.status_code})"
            )

        return self._parse_graph_message(resp.json())

    async def send_email(self, account_type: str, draft: EmailDraftReply) -> bool:
        """Send an email through Microsoft Graph sendMail endpoint after human approval."""
        self._require_configuration()

        url = f"{self.endpoint}{self._get_user_path()}/sendMail"
        payload = {
            "message": {
                "subject": draft.subject,
                "body": {
                    "contentType": "Text",
                    "content": draft.body,
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": draft.recipient,
                        }
                    }
                ],
            },
            "saveToSentItems": True,
        }

        resp = await self._request_with_retry("POST", url, json_data=payload)
        # Graph returns 202 Accepted on success
        if resp.status_code in (200, 202):
            logger.info("Sent email through Microsoft Graph API for %s to %s.", self.account_type, draft.recipient)
            return True

        err_detail = f"HTTP {resp.status_code}"
        try:
            err_json = resp.json()
            err_detail = err_json.get("error", {}).get("message", err_detail)
        except Exception:
            pass
        raise IntegrationException(f"Failed to send email via Microsoft Graph API: {err_detail}")

    def _parse_graph_message(self, item: Dict[str, Any]) -> EmailMessageSchema:
        """Map Microsoft Graph message JSON into EmailMessageSchema."""
        from_data = item.get("from") or {}
        email_addr = from_data.get("emailAddress") or {}
        sender_address = email_addr.get("address", "")
        sender_name = email_addr.get("name", "")
        sender = f"{sender_name} <{sender_address}>" if sender_name and sender_address else (sender_address or sender_name or "unknown@unitbv.ro")

        recipients = []
        for to_item in item.get("toRecipients", []):
            to_addr = (to_item.get("emailAddress") or {}).get("address")
            if to_addr:
                recipients.append(to_addr)

        raw_date = item.get("receivedDateTime")
        received_at = self._parse_iso_date(raw_date)

        subject = item.get("subject") or "(Fără subiect)"
        preview = item.get("bodyPreview") or ""
        body_dict = item.get("body") or {}
        body_text = self._clean_body_text(body_dict, fallback_preview=preview)

        # Classify importance
        graph_importance = (item.get("importance") or "normal").lower()
        is_practice = self._detect_practice(subject, body_text)
        is_high = graph_importance == "high" or is_practice or ("important" in subject.lower())
        importance_str = "high" if is_high else ("low" if graph_importance == "low" else "medium")

        # Deadline detection heuristic
        deadline = self._detect_deadline(body_text)

        return EmailMessageSchema(
            message_id=item.get("id", ""),
            account_type=self.account_type,
            sender=sender,
            recipients=recipients,
            subject=subject,
            body_text=body_text[:10000],
            received_at=received_at,
            importance=importance_str,
            summary=preview[:300] if preview else None,
            is_practice_related=is_practice,
            requires_action=bool(deadline or is_practice),
            detected_deadline=deadline,
        )

    @staticmethod
    def _parse_iso_date(raw_date: Optional[str]) -> datetime:
        if raw_date:
            try:
                # Graph returns ISO 8601 strings like "2026-09-10T10:15:30Z"
                dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        return datetime.now(timezone.utc)

    @staticmethod
    def _clean_body_text(body_dict: Dict[str, Any], fallback_preview: str = "") -> str:
        content = body_dict.get("content", "")
        content_type = (body_dict.get("contentType") or "text").lower()

        if content_type == "html" and content:
            clean = re.sub(r"<style[\s\S]*?</style>", "", content, flags=re.IGNORECASE)
            clean = re.sub(r"<script[\s\S]*?</script>", "", clean, flags=re.IGNORECASE)
            clean = re.sub(r"<br\s*/?>", "\n", clean, flags=re.IGNORECASE)
            clean = re.sub(r"</p>", "\n\n", clean, flags=re.IGNORECASE)
            clean = re.sub(r"</div>", "\n", clean, flags=re.IGNORECASE)
            clean = re.sub(r"<[^>]+>", "", clean)
            clean = html.unescape(clean)
            clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
            return clean or fallback_preview

        return content.strip() or fallback_preview

    @staticmethod
    def _detect_practice(subject: str, body: str) -> bool:
        """Detect if an email is practice‑related using token‑based matching.

        This avoids false positives such as the keyword "ore"
        matching inside the word "orele". The text is normalized to NFKD,
        diacritics are stripped, and then split into word tokens. A keyword
        matches only when it appears as an exact token.
        """
        import unicodedata
        import re

        # Combine subject and body, lower‑case for case‑insensitive matching
        text = f"{subject} {body}".lower()

        # Unicode‑normalize and remove combining marks (accents)
        normalized = unicodedata.normalize('NFKD', text)
        normalized = ''.join(ch for ch in normalized if not unicodedata.combining(ch))

        # Split into word tokens (alphanumeric + underscore)
        tokens = set(re.findall(r"\b\w+\b", normalized))

        # Base practice keywords (hard‑coded)
        base_keywords = [
            "practică",
            "practica",
            "convenție",
            "conventie",
            "caiet",
            "adeverință",
            "adeverinta",
            "colocviu",
            "tutore",
        ]

        # Combine with dynamic keywords from configuration
        all_keywords = set(base_keywords + get_practice_keywords())

        # Create a set of normalized keyword tokens
        kw_set = {''.join(ch for ch in unicodedata.normalize('NFKD', kw.lower()) if not unicodedata.combining(ch))
                  for kw in all_keywords}
        # Return True if any keyword token intersect with text tokens
        return bool(tokens.intersection(kw_set))

    @staticmethod
    def _detect_deadline(text: str) -> Optional[str]:
        # Search for dates like 28 august 2026 or 28.08.2026 or până la data de ...
        patterns = [
            r"(?:până la|termen limită|pana la|termen)[:\s]+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
            r"(?:până la|pana la|termen)[:\s]+(\d{1,2}\s+(?:ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+\d{4})",
        ]
        for pat in patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None
