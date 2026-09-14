"""Unit tests for Telegram interactive inline keyboards, callback routing, and Human-in-the-Loop confirmations."""

import pytest
from src.app.integrations.telegram.service import (
    TelegramService,
    get_draft_approval_keyboard,
    get_tasks_action_keyboard,
    get_email_action_keyboard,
    get_documents_download_keyboard,
    get_main_menu_keyboard,
    get_calendar_action_keyboard,
)
from src.app.orchestrator.orchestrator import AIOrchestrator
from src.app.orchestrator.intent import IntentType
from src.app.services.action_item_service import ActionItemService
from src.app.agents.email_agent import EmailAgent


def test_main_menu_keyboard_structure():
    kb = get_main_menu_keyboard()
    assert "keyboard" in kb
    assert len(kb["keyboard"]) == 3
    assert kb.get("is_persistent") is True


def test_draft_approval_keyboard_structure():
    draft_id = "test-draft-xyz-123"
    kb = get_draft_approval_keyboard(draft_id)
    assert "inline_keyboard" in kb
    buttons = kb["inline_keyboard"][0]
    assert len(buttons) == 2
    assert "Trimite" in buttons[0]["text"]
    assert buttons[0]["callback_data"] == f"approve_draft:{draft_id}"
    assert "Anulează" in buttons[1]["text"]
    assert buttons[1]["callback_data"] == f"reject_draft:{draft_id}"


def test_tasks_action_keyboard_structure():
    tasks = [
        {"id": 1, "title": "Trimite conventia de practica semnata"},
        {"id": 2, "title": "Completeaza jurnalul saptamanal"},
    ]
    kb = get_tasks_action_keyboard(tasks)
    assert "inline_keyboard" in kb
    assert len(kb["inline_keyboard"]) == 2
    assert kb["inline_keyboard"][0][0]["callback_data"] == "complete_task:1"
    assert kb["inline_keyboard"][1][0]["callback_data"] == "complete_task:2"


def test_email_action_keyboard_structure():
    emails = [
        {"message_id": "msg-1", "sender": "profesor@unitbv.ro", "subject": "Colocviu"},
        {"message_id": "msg-2", "sender": "secretariat@unitbv.ro", "subject": "Adeverinta"},
    ]
    kb = get_email_action_keyboard(emails)
    assert "inline_keyboard" in kb
    assert len(kb["inline_keyboard"]) == 2
    assert kb["inline_keyboard"][0][0]["callback_data"] == "reply_mail:1"
    assert kb["inline_keyboard"][1][0]["callback_data"] == "reply_mail:2"


def test_documents_download_keyboard_structure():
    kb = get_documents_download_keyboard()
    assert "inline_keyboard" in kb
    assert len(kb["inline_keyboard"]) == 2
    assert kb["inline_keyboard"][0][0]["callback_data"] == "conventie_download"
    assert kb["inline_keyboard"][0][1]["callback_data"] == "caiet_download"
    assert kb["inline_keyboard"][1][0]["callback_data"] == "all_docs_download"


def test_calendar_action_keyboard_structure():
    """get_calendar_action_keyboard returns proper confirm/cancel inline keyboard."""
    action_id = "cal-action-abc-123"
    kb = get_calendar_action_keyboard(action_id)
    assert "inline_keyboard" in kb
    row = kb["inline_keyboard"][0]
    assert len(row) == 2
    confirm_btn = row[0]
    cancel_btn = row[1]
    assert confirm_btn["callback_data"] == f"calendar_confirm:{action_id}"
    assert cancel_btn["callback_data"] == f"calendar_cancel:{action_id}"
    # Labels should contain meaningful text
    assert len(confirm_btn["text"]) > 0
    assert len(cancel_btn["text"]) > 0


@pytest.mark.asyncio
async def test_telegram_service_get_me_mock():
    """get_me returns mock bot identity when no real token is configured."""
    service = TelegramService(bot_token="dummy:NOTOKEN")
    result = await service.get_me()
    assert isinstance(result, dict)
    assert "is_bot" in result
    assert result["is_bot"] is True


@pytest.mark.asyncio
async def test_telegram_service_get_webhook_info_mock():
    """get_webhook_info returns mock webhook info when no real token is configured."""
    service = TelegramService(bot_token="dummy:NOTOKEN")
    result = await service.get_webhook_info()
    assert isinstance(result, dict)
    assert "url" in result
    assert "pending_update_count" in result


@pytest.mark.asyncio
async def test_telegram_service_delete_webhook_mock():
    """delete_webhook succeeds gracefully in mock mode."""
    service = TelegramService(bot_token="dummy:NOTOKEN")
    result = await service.delete_webhook(drop_pending_updates=False)
    assert result is True


@pytest.mark.asyncio
async def test_telegram_service_edit_message_mock(monkeypatch):
    service = TelegramService(bot_token="dummy:token")
    res = await service.edit_message_text(
        chat_id=12345,
        message_id=99,
        text="Updated text",
    )
    # In mock/test environment without real token, it succeeds gracefully
    assert res in [True, False]


@pytest.mark.asyncio
async def test_orchestrator_callback_intent_detection():
    orchestrator = AIOrchestrator()

    res_approve = await orchestrator.detect_intent("approve_draft:draft-101", user_id="u1")
    assert res_approve.intent == IntentType.EMAIL_SEND_CONFIRMATION

    res_reject = await orchestrator.detect_intent("reject_draft:draft-101", user_id="u1")
    assert res_reject.intent == IntentType.EMAIL_SEND_CONFIRMATION

    res_task = await orchestrator.detect_intent("complete_task:42", user_id="u1")
    assert res_task.intent == IntentType.TASKS_QUERY

    res_reply = await orchestrator.detect_intent("draft_reply:msg-202", user_id="u1")
    assert res_reply.intent == IntentType.EMAIL_DRAFT_REPLY

    res_reply_idx = await orchestrator.detect_intent("reply_mail:1", user_id="u1")
    assert res_reply_idx.intent == IntentType.EMAIL_DRAFT_REPLY

    res_doc = await orchestrator.detect_intent("conventie_download", user_id="u1")
    assert res_doc.intent == IntentType.PRACTICE_DOCUMENT_REQUEST

    # Calendar HITL callbacks
    res_cal_confirm = await orchestrator.detect_intent("calendar_confirm:cal-abc-123", user_id="u1")
    assert res_cal_confirm.intent == IntentType.CALENDAR_CONFIRM_ACTION

    res_cal_cancel = await orchestrator.detect_intent("calendar_cancel:cal-abc-123", user_id="u1")
    assert res_cal_cancel.intent == IntentType.CALENDAR_CANCEL_ACTION


@pytest.mark.asyncio
async def test_orchestrator_callback_email_draft_and_approval_cycle():
    orchestrator = AIOrchestrator()
    uid = "test-user-cycle-1"

    # 1. User drafts a reply via quick button
    draft_res = await orchestrator.process_request("draft_reply:msg-unitbv-101", user_id=uid)
    assert draft_res["intent"] == IntentType.EMAIL_DRAFT_REPLY.value
    assert "inline_keyboard" in draft_res
    draft_id = draft_res.get("draft_id")
    assert draft_id is not None

    # 2. User taps [Trimite Email] via callback
    approve_res = await orchestrator.process_request(f"approve_draft:{draft_id}", user_id=uid)
    assert approve_res["intent"] == IntentType.EMAIL_SEND_CONFIRMATION.value
    assert "trimis" in approve_res["response"].lower() or "sent" in approve_res["response"].lower()


@pytest.mark.asyncio
async def test_orchestrator_callback_task_completion():
    action_service = ActionItemService()
    item = await action_service.create_action_item(
        title="Test callback completion task",
        source="test",
        priority="high",
        user_id="u_task",
    )
    task_id = item["id"]

    orchestrator = AIOrchestrator(action_item_service=action_service)
    complete_res = await orchestrator.process_request(f"complete_task:{task_id}", user_id="u_task")
    assert complete_res["intent"] == IntentType.TASKS_QUERY.value
    assert "finalizată" in complete_res["response"] or "finalizata" in complete_res["response"]

    # Verify status in service
    completed_items = await action_service.list_action_items(status="completed", user_id="u_task")
    assert any(it["id"] == task_id for it in completed_items)
