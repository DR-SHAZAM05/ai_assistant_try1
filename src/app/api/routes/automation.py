"""Authenticated internal endpoints for n8n scheduled jobs."""

import hmac
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status

from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.services.email_service import EmailService
from src.app.services.news_service import NewsService


router = APIRouter(prefix="/automation", tags=["Internal Automation"])


def _require_automation_key(x_automation_key: Optional[str]) -> None:
    configured_key = settings.AUTOMATION_API_KEY
    if not configured_key or not x_automation_key or not hmac.compare_digest(x_automation_key, configured_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid automation credential.")


def _resolve_automation_user(telegram_user_id: Optional[str]) -> str:
    """Resolve the sole configured user or require an explicit safe target.

    Credentials for mail and calendar are process-wide configuration, so an
    automation must never broadcast their data to every allowed Telegram id.
    """

    allowed_ids = settings.telegram_allowed_user_ids
    requested_id = str(telegram_user_id or "").strip()
    if requested_id:
        if allowed_ids and requested_id not in allowed_ids and settings.APP_ENV != "test":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Telegram user is not allowed.")
        return requested_id
    if len(allowed_ids) == 1:
        return next(iter(allowed_ids))
    if not allowed_ids:
        if settings.APP_ENV == "test":
            return "test_automation_user"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configure TELEGRAM_ALLOWED_USER_IDS before running user-scoped automation.",
        )
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="telegram_user_id is required when more than one Telegram user is allowed.",
    )


@router.post("/news/refresh")
async def refresh_news(
    x_automation_key: Optional[str] = Header(None),
    telegram_user_id: Optional[str] = None,
):
    """Fetch, parse, and rank the configured RSS feeds for a scheduled n8n run."""
    _require_automation_key(x_automation_key)
    owner_id = _resolve_automation_user(telegram_user_id)
    articles = await NewsService().fetch_and_process_news(user_id=owner_id)
    logger.info("n8n news refresh completed with %s relevant articles.", len(articles))
    return {"status": "success", "relevant_articles": len(articles)}


@router.post("/email/poll")
async def poll_mailboxes(
    x_automation_key: Optional[str] = Header(None),
    notify_telegram: bool = False,
    telegram_user_id: Optional[str] = None,
):
    """Verify and poll configured inboxes. Optionally push Telegram alerts for urgent/practice emails."""
    _require_automation_key(x_automation_key)
    owner_id = _resolve_automation_user(telegram_user_id)
    service = EmailService()
    accounts = ("personal", "unitbv")
    results = {}
    urgent_alerts = []

    for account in accounts:
        try:
            emails = await service.list_emails(account, user_id=owner_id)
            results[account] = {"status": "success", "messages": len(emails)}
            for em in emails:
                if em.importance in ["high", "important"] or em.is_practice_related or em.requires_action:
                    urgent_alerts.append((account, em))
        except Exception as exc:
            logger.warning("n8n mailbox poll failed for %s (%s).", account, type(exc).__name__)
            results[account] = {"status": "error"}

    notifications_sent = 0
    if notify_telegram and urgent_alerts:
        from src.app.integrations.telegram.service import TelegramService
        telegram_service = TelegramService()
        for account, em in urgent_alerts[:2]:
            alert_msg = (
                f"📩 **Alertă E-mail Urgent ({account.upper()})**:\n"
                f"• **Expeditor**: `{em.sender}`\n"
                f"• **Subiect**: {em.subject}\n"
                f"• **Sumar**: {em.summary or em.body_text[:100]}...\n\n"
                "💡 *Apasă butonul de mai jos pentru a genera un răspuns rapid:*"
            )
            inline_kb = {
                "inline_keyboard": [
                    [{"text": f"✍️ Răspunde ({em.sender.split('@')[0]})", "callback_data": f"draft_reply:{em.message_id}"}]
                ]
            }
            try:
                if await telegram_service.send_message(chat_id=int(owner_id), text=alert_msg, reply_markup=inline_kb):
                    notifications_sent += 1
            except Exception as e:
                logger.warning("Failed to send email alert to %s: %s", owner_id, e)

    overall_status = "success" if all(item["status"] == "success" for item in results.values()) else "partial"
    return {
        "status": overall_status,
        "accounts": results,
        "urgent_detected": len(urgent_alerts),
        "notifications_sent": notifications_sent,
    }


@router.post("/practice/deadlines-check")
async def check_practice_deadlines(
    x_automation_key: Optional[str] = Header(None),
    notify_telegram: bool = True,
    telegram_user_id: Optional[str] = None,
):
    """Check pending action items and official UNITBV practice milestones with proactive Telegram alerts."""
    _require_automation_key(x_automation_key)
    owner_id = _resolve_automation_user(telegram_user_id)
    from src.app.integrations.telegram.service import TelegramService
    from src.app.services.action_item_service import ActionItemService
    from datetime import datetime

    from src.app.core.practice_config import get_practice_deadlines

    action_service = ActionItemService()
    items = await action_service.list_action_items(status="open", user_id=owner_id)

    now = datetime.now()
    deadlines_cfg = get_practice_deadlines()
    milestone_lines = []
    for item in deadlines_cfg:
        title = item.get("title", "Termen")
        raw_dt = item.get("date")
        if isinstance(raw_dt, str):
            try:
                dt = datetime.fromisoformat(raw_dt)
            except Exception:
                dt = now
        elif isinstance(raw_dt, datetime):
            dt = raw_dt
        else:
            dt = now
        diff_days = (dt.date() - now.date()).days
        if diff_days > 0:
            proximity = f"(în {diff_days} zile)"
        elif diff_days == 0:
            proximity = "⚠️ **(AZI ESTE TERMENUL LIMITĂ!)**"
        else:
            proximity = f"(termen depășit cu {abs(diff_days)} zile)"
        milestone_lines.append(f"• **{title}**: `{dt.strftime('%d.%m.%Y')}` {proximity}")

    msg_lines = [
        "🔔 **Notificare Proactivă: Termene Limită & Practică UNITBV**\n",
        "📌 **Calendarul Oficial al Practicii (FIESC)**:",
    ]
    msg_lines.extend(milestone_lines)
    msg_lines.append("")

    if items:
        msg_lines.append(f"📋 **Ai {len(items)} sarcini active în evidență**:")
        for idx, it in enumerate(items[:4], 1):
            pri_icon = "🔴" if it.get("priority") in ["high", "urgent"] else "🟡"
            deadline = it.get("deadline")
            d_str = f" (până la {deadline.strftime('%d.%m.%Y')})" if hasattr(deadline, "strftime") else ""
            msg_lines.append(f"{idx}. {pri_icon} [Task #{it['id']}] {it['title']}{d_str}")
        if len(items) > 4:
            msg_lines.append(f"   *...și încă {len(items) - 4} sarcini.*")
    else:
        msg_lines.append("✅ Toate sarcinile tale specifice sunt la zi! Nu uita să semnezi documentele oficiale.")

    msg_lines.append("\n💡 *Apasă pe butoanele de mai jos pentru descărcare sau consultare rapidă:*")
    message_text = "\n".join(msg_lines)

    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "📄 Descarcă Convenție", "callback_data": "conventie_download"},
                {"text": "📘 Descarcă Caiet", "callback_data": "caiet_download"}
            ],
            [
                {"text": "📋 Vezi Sarcinile", "callback_data": "/sarcini"},
                {"text": "📅 Vezi Calendar", "callback_data": "/calendar"}
            ]
        ]
    }

    notifications_sent = 0
    if notify_telegram:
        telegram_service = TelegramService()
        try:
            if await telegram_service.send_message(chat_id=int(owner_id), text=message_text, reply_markup=inline_keyboard):
                notifications_sent += 1
        except Exception as e:
            logger.warning("Failed to send scheduled deadline reminder to %s: %s", owner_id, e)

    return {
        "status": "success",
        "open_action_items": len(items),
        "notifications_sent": notifications_sent,
    }


@router.post("/daily-briefing")
async def daily_morning_briefing(
    x_automation_key: Optional[str] = Header(None),
    notify_telegram: bool = True,
    telegram_user_id: Optional[str] = None,
):
    """Compile and push a morning daily briefing (Calendar + Tasks + Top Tech News)."""
    _require_automation_key(x_automation_key)
    owner_id = _resolve_automation_user(telegram_user_id)
    from src.app.integrations.telegram.service import TelegramService
    from src.app.agents.calendar_agent import CalendarAgent
    from src.app.services.action_item_service import ActionItemService
    from datetime import datetime

    today_str = datetime.now().strftime("%d.%m.%Y")
    briefing_lines = [
        f"🌅 **Bună dimineața! Sinteza ta academică pentru astăzi ({today_str}):**\n"
    ]

    # 1. Today's Calendar Schedule
    try:
        cal_res = await CalendarAgent().handle_calendar_query(
            user_id=owner_id,
            user_prompt="ce am azi?",
        )
        cal_text = cal_res.get("text", "")
        briefing_lines.append("📅 **Programul tău de astăzi**:")
        briefing_lines.append(cal_text)
        briefing_lines.append("")
    except Exception as e:
        logger.debug("Briefing calendar check error: %s", e)

    # 2. Email Status (Section 17: EMAIL)
    try:
        from src.app.services.email_service import EmailService
        from src.app.schemas.email import EmailFilterParams
        email_svc = EmailService()
        all_emails = []
        for acc in ["personal", "unitbv"]:
            try:
                fetched = await email_svc.list_emails(
                    account_type=acc,
                    filter_params=EmailFilterParams(limit=5),
                    user_id=owner_id,
                )
                all_emails.extend(fetched)
            except Exception:
                pass
        important_count = sum(1 for e in all_emails if e.importance in ["high", "important"] or e.is_practice_related)
        action_count = sum(1 for e in all_emails if e.requires_action or e.detected_deadline)
        briefing_lines.append("📧 **E-mailuri Noi & Necesitate Răspuns**:")
        if all_emails:
            briefing_lines.append(f"• {len(all_emails)} mesaje verificate ({important_count} importante)")
            if action_count > 0:
                briefing_lines.append(f"• ⚠️ {action_count} mesaje necesită răspuns sau acțiune")
            else:
                briefing_lines.append("• ✅ Niciun mesaj nu necesită răspuns urgent")
        else:
            briefing_lines.append("• Căsuțele poștale sunt la zi (niciun mesaj nou)")
        briefing_lines.append("")
    except Exception as e:
        logger.debug("Briefing email check error: %s", e)

    # 3. UNITBV / Practică Status (Section 17: UNITBV / PRACTICĂ)
    from src.app.core.practice_config import get_practice_deadlines
    deadlines_cfg = get_practice_deadlines()
    briefing_lines.append("🎓 **UNITBV / Practică Studențească**:")
    for dl in deadlines_cfg[:2]:
        briefing_lines.append(f"• Termen {dl.get('id', 'termen').capitalize()}: **{dl.get('display_date', '')}** ({dl.get('description', '')})")
    briefing_lines.append("")

    # 4. Open Tasks & Action Items (Section 17: ACTION ITEMS)
    try:
        action_service = ActionItemService()
        items = await action_service.list_action_items(status="open", user_id=owner_id)
        if items:
            briefing_lines.append(f"📋 **Sarcini prioritare ({len(items)} în așteptare)**:")
            for idx, it in enumerate(items[:3], 1):
                briefing_lines.append(f"{idx}. [Task #{it['id']}] {it['title']}")
            briefing_lines.append("")
        else:
            briefing_lines.append("📋 **Sarcini**: Nicio sarcină restantă! Ești la zi.")
            briefing_lines.append("")
    except Exception as e:
        logger.debug("Briefing tasks check error: %s", e)

    # 3. Top News
    try:
        articles = await NewsService().fetch_and_process_news(max_results=2, user_id=owner_id)
        if articles:
            briefing_lines.append("📰 **Top Știri Tehnologice Relevante**:")
            for n in articles[:2]:
                briefing_lines.append(f"• [{n.title}]({n.url})")
            briefing_lines.append("")
    except Exception as e:
        logger.debug("Briefing news check error: %s", e)

    briefing_lines.append("O zi productivă și mult succes la activitățile de practică! 🚀")
    briefing_text = "\n".join(briefing_lines)

    inline_keyboard = {
        "inline_keyboard": [
            [
                {"text": "📅 Deschide Calendar", "callback_data": "/calendar"},
                {"text": "📋 Sarcinile Mele", "callback_data": "/sarcini"}
            ],
            [
                {"text": "📧 Verifică Emailuri", "callback_data": "/email"},
                {"text": "📰 Știri Tehnologice", "callback_data": "/stiri"}
            ]
        ]
    }

    notifications_sent = 0
    if notify_telegram:
        telegram_service = TelegramService()
        try:
            if await telegram_service.send_message(chat_id=int(owner_id), text=briefing_text, reply_markup=inline_keyboard):
                notifications_sent += 1
        except Exception as e:
            logger.warning("Failed to send morning briefing to %s: %s", owner_id, e)

    return {
        "status": "success",
        "briefing_length": len(briefing_text),
        "notifications_sent": notifications_sent,
    }

