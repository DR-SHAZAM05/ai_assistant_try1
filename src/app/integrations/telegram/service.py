"""Telegram Bot API adapter."""

from typing import Any, Dict, Optional

import httpx

from src.app.core.config import is_valid_telegram_bot_token, settings
from src.app.core.exceptions import ConfigurationException, IntegrationException
from src.app.core.logging import logger
from src.app.core.retry import retry_async


def get_main_menu_keyboard() -> Dict[str, Any]:
    """Returns the persistent 6-button Telegram keyboard for quick student access."""
    return {
        "keyboard": [
            [{"text": "📄 Convenție Practică"}, {"text": "📘 Caiet de Practică"}],
            [{"text": "📋 Sarcinile Mele"}, {"text": "📅 Program Calendar"}],
            [{"text": "📧 Verifică Emailuri"}, {"text": "📰 Știri Tehnologice"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def get_draft_approval_keyboard(draft_id: str) -> Dict[str, Any]:
    """Inline keyboard for one-click human confirmation or cancellation of an email draft."""
    return {
        "inline_keyboard": [
            [
                {"text": "✉️ Trimite E-mail", "callback_data": f"approve_draft:{draft_id}"},
                {"text": "❌ Anulează", "callback_data": f"reject_draft:{draft_id}"},
            ]
        ]
    }


def get_tasks_action_keyboard(tasks: list) -> Dict[str, Any]:
    """Inline keyboard for marking open tasks as completed directly with a single tap."""
    buttons = []
    for it in tasks[:5]:
        tid = it.get("id")
        title = it.get("title", "")
        short_title = (title[:22] + "...") if len(title) > 22 else title
        buttons.append([{"text": f"✅ Finalizează #{tid}: {short_title}", "callback_data": f"complete_task:{tid}"}])
    return {"inline_keyboard": buttons}


def get_email_action_keyboard(emails: list) -> Dict[str, Any]:
    """Inline keyboard for quick drafting a reply to incoming emails."""
    buttons = []
    for idx, mail in enumerate(emails[:3], 1):
        sender = mail.get("sender", "")
        sender_name = sender.split("@")[0] if "@" in sender else sender
        sender_name = (sender_name[:15] + "...") if len(sender_name) > 15 else sender_name
        buttons.append([{"text": f"✍️ Răspunde la #{idx} ({sender_name})", "callback_data": f"reply_mail:{idx}"}])
    return {"inline_keyboard": buttons}


def get_documents_download_keyboard() -> Dict[str, Any]:
    """Inline keyboard for quick practice document generation."""
    return {
        "inline_keyboard": [
            [
                {"text": "📄 Convenție-Cadru (.docx)", "callback_data": "conventie_download"},
                {"text": "📘 Caiet Practică (.docx)", "callback_data": "caiet_download"},
            ],
            [
                {"text": "📦 Ambele Documente (.docx)", "callback_data": "all_docs_download"}
            ]
        ]
    }


class TelegramService:
    """Send messages and configure a Telegram webhook through the official Bot API."""

    def __init__(self, bot_token: Optional[str] = None):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}" if self._has_valid_token else None

    @property
    def _has_valid_token(self) -> bool:
        return is_valid_telegram_bot_token(self.bot_token)

    async def set_bot_commands(self) -> bool:
        """Register Telegram Bot commands to display the blue Menu button in the chat."""
        if not self._has_valid_token:
            return True
        commands = [
            {"command": "start", "description": "Afișează meniul principal și tastele rapide"},
            {"command": "briefing", "description": "Sinteza zilei (Calendar + Sarcini + Știri)"},
            {"command": "sinteza", "description": "Ce am de făcut? (Calendar + Task-uri + E-mail + Practică)"},
            {"command": "sarcini", "description": "Afișează sarcinile și acțiunile active"},
            {"command": "calendar", "description": "Verifică evenimentele și orarul din calendar"},
            {"command": "email", "description": "Verifică cele mai recente e-mailuri"},
            {"command": "practica", "description": "Ghid și informații despre practica UNITBV"},
            {"command": "conventie", "description": "Generează Convenția de practică UNITBV (.docx)"},
            {"command": "caiet", "description": "Generează Caietul de practică UNITBV (.docx)"},
            {"command": "memorie", "description": "Gestionează preferințele și regulile memorate"},
            {"command": "stiri", "description": "Noutăți și articole tehnologice"},
            {"command": "help", "description": "Ghid complet de utilizare și asistență"},
        ]
        try:
            return await self._post("setMyCommands", {"commands": commands})
        except Exception as exc:
            logger.warning("Failed to register Telegram bot commands: %s", exc)
            return False

    async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None) -> bool:
        if not self._has_valid_token:
            return True
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            return await self._post("answerCallbackQuery", payload)
        except Exception as exc:
            logger.debug("Failed to answer callback query: %s", exc)
            return False

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = "Markdown",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self._has_valid_token:
            if settings.mocks_allowed:
                logger.info("[Development Telegram mock] chat_id=%s", chat_id)
                return True
            raise ConfigurationException("TELEGRAM_BOT_TOKEN is required to send Telegram messages")

        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            # Enforce Telegram 64-byte limit on callback_data
            if "inline_keyboard" in reply_markup:
                sanitized_rows = []
                for row in reply_markup["inline_keyboard"]:
                    sanitized_row = []
                    for btn in row:
                        cb = btn.get("callback_data")
                        if cb and len(cb.encode("utf-8")) > 64:
                            btn = dict(btn)
                            btn["callback_data"] = cb.encode("utf-8")[:64].decode("utf-8", errors="ignore")
                        sanitized_row.append(btn)
                    sanitized_rows.append(sanitized_row)
                reply_markup["inline_keyboard"] = sanitized_rows
            payload["reply_markup"] = reply_markup

        try:
            return await self._post("sendMessage", payload, retry_without_parse_mode=bool(parse_mode))
        except Exception as exc:
            if reply_markup:
                logger.warning("Telegram sendMessage failed with reply_markup (%s). Retrying without markup...", exc)
                try:
                    fallback_payload = {"chat_id": chat_id, "text": text}
                    if parse_mode:
                        fallback_payload["parse_mode"] = parse_mode
                    return await self._post("sendMessage", fallback_payload, retry_without_parse_mode=bool(parse_mode))
                except Exception:
                    pass
            raise IntegrationException("Telegram sendMessage failed") from exc

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: Optional[str] = "Markdown",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Edit an existing message text and optionally its inline keyboard."""
        if not self._has_valid_token:
            if settings.mocks_allowed:
                logger.info("[Development Telegram mock] edit_message_text chat_id=%s message_id=%s", chat_id, message_id)
                return True
            raise ConfigurationException("TELEGRAM_BOT_TOKEN is required to edit Telegram messages")

        payload: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        try:
            return await self._post("editMessageText", payload, retry_without_parse_mode=bool(parse_mode))
        except Exception as exc:
            logger.warning("Failed to edit Telegram message %s in chat %s: %s", message_id, chat_id, exc)
            return False

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> bool:
        if not self._has_valid_token:
            return True
        payload: Dict[str, Any] = {"chat_id": chat_id, "action": action}
        try:
            return await self._post("sendChatAction", payload)
        except Exception as exc:
            logger.debug("Failed to send Telegram chat action %s: %s", action, exc)
            return False

    async def set_webhook(self, webhook_url: str, secret_token: Optional[str] = None) -> bool:
        if not self._has_valid_token:
            if settings.mocks_allowed:
                logger.info("[Development Telegram mock] webhook would be set to %s", webhook_url)
                return True
            raise ConfigurationException("TELEGRAM_BOT_TOKEN is required to configure the Telegram webhook")
        if not webhook_url.startswith("https://"):
            raise ConfigurationException("Telegram requires a public HTTPS webhook URL")

        payload: Dict[str, Any] = {"url": webhook_url, "drop_pending_updates": False}
        if secret_token:
            payload["secret_token"] = secret_token
        try:
            return await self._post("setWebhook", payload)
        except Exception as exc:
            raise IntegrationException("Telegram setWebhook failed") from exc

    async def send_document(
        self,
        chat_id: int,
        document: bytes,
        filename: str,
        caption: Optional[str] = None,
        parse_mode: Optional[str] = "Markdown",
    ) -> bool:
        if not self._has_valid_token:
            if settings.mocks_allowed:
                logger.info("[Development Telegram mock] send_document chat_id=%s filename=%s", chat_id, filename)
                return True
            raise ConfigurationException("TELEGRAM_BOT_TOKEN is required to send Telegram documents")

        data: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        if parse_mode:
            data["parse_mode"] = parse_mode

        files = {
            "document": (
                filename,
                document,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }

        try:
            return await self._post_multipart(
                "sendDocument",
                data=data,
                files=files,
                retry_without_parse_mode=bool(parse_mode),
            )
        except Exception as exc:
            raise IntegrationException("Telegram sendDocument failed") from exc

    async def _post(self, method: str, payload: Dict[str, Any], retry_without_parse_mode: bool = False) -> bool:
        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS) as client:
                return await client.post(f"{self.base_url}/{method}", json=payload)

        response = await retry_async(request, operation_name=f"telegram_{method}")
        if response.status_code == 200 and response.json().get("ok", False):
            return True
        if retry_without_parse_mode and response.status_code == 400:
            fallback_payload = dict(payload)
            fallback_payload.pop("parse_mode", None)
            return await self._post(method, fallback_payload, retry_without_parse_mode=False)
        raise IntegrationException(f"Telegram API returned HTTP {response.status_code}")

    async def _post_multipart(
        self,
        method: str,
        data: Dict[str, Any],
        files: Dict[str, Any],
        retry_without_parse_mode: bool = False,
    ) -> bool:
        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS) as client:
                return await client.post(f"{self.base_url}/{method}", data=data, files=files)

        response = await retry_async(request, operation_name=f"telegram_{method}")
        if response.status_code == 200 and response.json().get("ok", False):
            return True
        if retry_without_parse_mode and response.status_code == 400:
            fallback_data = dict(data)
            fallback_data.pop("parse_mode", None)
            return await self._post_multipart(method, fallback_data, files, retry_without_parse_mode=False)
        raise IntegrationException(f"Telegram API returned HTTP {response.status_code}")

