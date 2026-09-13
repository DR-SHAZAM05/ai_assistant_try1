import hmac
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Header, status
from typing import Optional, Dict, Any
from src.app.schemas.telegram import TelegramUpdate
from src.app.orchestrator.orchestrator import AIOrchestrator
from src.app.integrations.telegram.service import TelegramService, get_main_menu_keyboard
from src.app.memory.conversation_memory import ConversationMemoryService
from src.app.api.dependencies import (
    get_orchestrator_dependency,
    get_telegram_service_dependency,
    get_conversation_memory_service_dependency,
)
from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.core.rate_limit import telegram_rate_limiter

router = APIRouter(prefix="/telegram", tags=["Telegram Integration"])


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    update: TelegramUpdate,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
    orchestrator: AIOrchestrator = Depends(get_orchestrator_dependency),
    telegram_service: TelegramService = Depends(get_telegram_service_dependency),
    memory_service: ConversationMemoryService = Depends(get_conversation_memory_service_dependency),
) -> Dict[str, Any]:
    """
    Telegram Webhook endpoint. Receives updates from Telegram, routes to AI Orchestrator,
    and returns synthesized LLM response back to the user chat.
    """
    # Verify every configured secret. Production startup rejects weak or placeholder values.
    if settings.TELEGRAM_WEBHOOK_SECRET:
        if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
            x_telegram_bot_api_secret_token, settings.TELEGRAM_WEBHOOK_SECRET
        ):
            logger.warning("Unauthorized Telegram webhook call: secret token mismatch.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram secret token.")

    # Process message or callback_query from update
    callback_query = getattr(update, "callback_query", None)
    if callback_query and callback_query.message and callback_query.data:
        chat_id = callback_query.message.chat.id
        if not callback_query.from_user:
            logger.warning("Ignored Telegram callback without a sender identity.")
            return {"status": "ignored", "reason": "missing_sender"}
        sender_id = str(callback_query.from_user.id)
        user_text = callback_query.data
        try:
            await telegram_service.answer_callback_query(callback_query.id)
        except Exception:
            pass
    else:
        message = update.message or update.edited_message
        if not message or not message.text:
            logger.info(f"Received Telegram update_id {update.update_id} without text message. Skipping.")
            return {"status": "ignored", "reason": "no_text_message"}
        chat_id = message.chat.id
        if not message.from_user:
            logger.warning("Ignored Telegram message without a sender identity.")
            return {"status": "ignored", "reason": "missing_sender"}
        sender_id = str(message.from_user.id)
        user_text = message.text

    if settings.telegram_allowed_user_ids and sender_id not in settings.telegram_allowed_user_ids:
        logger.warning("Rejected Telegram message from unauthorized user %s", sender_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Telegram user is not allowed.")

    if settings.RATE_LIMIT_ENABLED:
        decision = await telegram_rate_limiter.check(
            f"telegram:{sender_id}",
            limit=settings.TELEGRAM_RATE_LIMIT_REQUESTS,
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )
        if not decision.allowed:
            logger.warning("Rate-limited Telegram message from user %s", sender_id)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many Telegram requests. Please retry later.",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

    logger.info("Incoming Telegram message accepted (text_length=%s).", len(user_text))

    # Pipeline execution with global safe handler to never return HTTP 500 to Telegram
    try:
        # Check for start / help onboarding
        prompt_norm = user_text.strip().lower()
        if prompt_norm in ["/start", "/help", "start", "help", "/menu", "meniu"]:
            welcome_text = (
                "👋 **Bună! Sunt Personal Academic AI Assistant (UNITBV).**\n\n"
                "Sunt asistentul tău inteligent modular pentru activitățile academice la Universitatea Transilvania din Brașov (FIESC).\n\n"
                "📌 **Comenzi rapide și funcționalități:**\n"
                "• 🌅 `/briefing` – Sinteza ta zilnică de dimineață (Calendar + Sarcini + Știri IT)\n"
                "• 📋 `/sinteza` sau *„Ce mai am de făcut?”* – Sinteză integrată multi-sursă (Calendar + Task-uri + E-mailuri + Practică)\n"
                "• 🎓 `/practica` sau `/documente` – Documente oficiale Word (.docx) Convenție și Caiet de practică\n"
                "• 🧠 `/memorie` sau *„Ține minte că...”* – Gestionează preferințele și regulile tale personale\n"
                "• 📅 `/calendar` – Orarul academic, laboratoarele și ședințele tale\n"
                "• 📋 `/sarcini` – Sarcinile și acțiunile extrase din e-mailuri cu bifare directă\n"
                "• 📧 `/email` – Verifică mesajele primite și generează drafturi de răspuns\n"
                "• 📰 `/stiri` – Știri tehnologice relevante filtrate și sortate\n\n"
                "Apasă pe oricare dintre butoanele de mai jos sau scrie-mi o întrebare! 👇"
            )
            send_success = await telegram_service.send_message(
                chat_id=chat_id,
                text=welcome_text,
                reply_markup=get_main_menu_keyboard(),
            )
            return {
                "status": "success",
                "chat_id": chat_id,
                "intent": "start_welcome",
                "telegram_sent": send_success,
                "response_summary": welcome_text[:100] + "...",
            }

        # Send typing action immediately so the user knows the assistant is working
        try:
            await telegram_service.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass

        # In group chats the chat is transport context, not the data owner.
        # Service queries are always additionally scoped by the sender id.
        session_id = f"telegram:{chat_id}"
        history = []
        try:
            history = await memory_service.get_history(
                session_id=session_id,
                user_id=sender_id,
                limit=8,
            )
        except Exception as mem_fetch_err:
            logger.warning("Failed to fetch conversation history: %s", mem_fetch_err)

        # 1. Pipeline: Pass message to AI Orchestrator with conversation history
        orchestrator_result: Dict[str, Any] = {}
        try:
            orchestrator_result = await orchestrator.process_request(
                user_prompt=user_text,
                user_id=sender_id,
                history=history,
            )
            response_text = orchestrator_result.get("response", "Nu am putut procesa mesajul tău.")
            intent = orchestrator_result.get("intent")
        except Exception:
            logger.exception("Error processing request in orchestrator")
            response_text = (
                "⚠️ Nu am putut procesa cererea în acest moment. "
                "Verifică integrarea necesară și încearcă din nou."
            )
            intent = "error"
            orchestrator_result = {"response": response_text, "intent": "error"}

        # Persist exchange to conversation memory
        try:
            await memory_service.add_message(
                session_id=session_id,
                sender_role="user",
                content=user_text,
                telegram_chat_id=str(chat_id),
                user_id=sender_id,
            )
            await memory_service.add_message(
                session_id=session_id,
                sender_role="assistant",
                content=response_text,
                telegram_chat_id=str(chat_id),
                user_id=sender_id,
            )
        except Exception as mem_store_err:
            logger.warning("Failed to persist conversation turn: %s", mem_store_err)

        # 2. Pipeline: Send response and any generated documents back to Telegram
        documents = orchestrator_result.get("documents", [])
        if documents:
            for doc_item in documents:
                try:
                    await telegram_service.send_document(
                        chat_id=chat_id,
                        document=doc_item["bytes"],
                        filename=doc_item["filename"],
                        caption=doc_item.get("caption"),
                    )
                except Exception as doc_err:
                    logger.error("Failed to send Telegram document (%s): %s", doc_item.get("filename"), doc_err)

        markup = get_main_menu_keyboard()
        if orchestrator_result.get("inline_keyboard"):
            markup = {"inline_keyboard": orchestrator_result["inline_keyboard"]}

        try:
            send_success = await telegram_service.send_message(
                chat_id=chat_id,
                text=response_text,
                reply_markup=markup,
            )
        except Exception as send_err:
            logger.error("Failed to send Telegram message: %s", send_err)
            try:
                send_success = await telegram_service.send_message(
                    chat_id=chat_id,
                    text=response_text,
                )
            except Exception:
                send_success = False

        return {
            "status": "success",
            "chat_id": chat_id,
            "intent": intent,
            "telegram_sent": send_success,
            "response_summary": response_text[:100] + "..." if len(response_text) > 100 else response_text
        }
    except Exception:
        logger.exception("Fatal unhandled error in telegram_webhook")
        try:
            await telegram_service.send_message(
                chat_id=chat_id,
                text="⚠️ A apărut o problemă la procesarea mesajului. Te rog să reîncerci.",
                reply_markup=get_main_menu_keyboard(),
            )
        except Exception:
            pass
        return {
            "status": "error",
            "chat_id": chat_id,
            "error": "message_processing_failed",
        }


@router.post("/setup-webhook")
async def setup_webhook(
    webhook_url: str,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
    telegram_service: TelegramService = Depends(get_telegram_service_dependency)
):
    """
    Helper endpoint to register Telegram webhook URL with Telegram API.
    """
    if (
        not settings.has_valid_telegram_webhook_secret
        or not x_telegram_bot_api_secret_token
        or not hmac.compare_digest(x_telegram_bot_api_secret_token, settings.TELEGRAM_WEBHOOK_SECRET)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid setup secret.")

    parsed_url = urlparse(webhook_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A public HTTPS webhook URL is required.")

    success = await telegram_service.set_webhook(
        webhook_url=webhook_url,
        secret_token=settings.TELEGRAM_WEBHOOK_SECRET
    )
    if success:
        return {"status": "success", "webhook_url": webhook_url}
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to register Telegram webhook.")
