"""Tests verifying strict user isolation across all services (User A 111111 vs User B 222222)."""

import pytest
from datetime import datetime, timezone

from src.app.memory.user_memory import UserMemoryService
from src.app.services.action_item_service import ActionItemService
from src.app.services.email_service import EmailService
from src.app.services.news_service import NewsService
from src.app.services.practice_history_service import PracticeHistoryService
from src.app.memory.conversation_memory import ConversationMemoryService
from src.app.services.audit_service import AuditService
from src.app.schemas.email import EmailMessageSchema
from src.app.schemas.news import NewsArticleSchema


USER_A = "111111"
USER_B = "222222"


@pytest.mark.asyncio
async def test_user_memory_isolation():
    service = UserMemoryService()

    # User A and User B set memories with the same key
    await service.set_memory(key="career_goal", value="Data Scientist", category="preference", user_id=USER_A)
    await service.set_memory(key="career_goal", value="Cybersecurity Expert", category="preference", user_id=USER_B)

    # Verify retrieval
    val_a = await service.get_memory("career_goal", user_id=USER_A)
    val_b = await service.get_memory("career_goal", user_id=USER_B)
    assert val_a == "Data Scientist"
    assert val_b == "Cybersecurity Expert"

    # Verify list memories
    list_a = await service.list_memories(user_id=USER_A)
    list_b = await service.list_memories(user_id=USER_B)
    assert any(m["key"] == "career_goal" and m["value"] == "Data Scientist" for m in list_a)
    assert not any(m["value"] == "Cybersecurity Expert" for m in list_a)
    assert any(m["key"] == "career_goal" and m["value"] == "Cybersecurity Expert" for m in list_b)
    assert not any(m["value"] == "Data Scientist" for m in list_b)

    # Deleting User A's memory does not affect User B
    deleted = await service.delete_memory("career_goal", user_id=USER_A)
    assert deleted is True
    assert await service.get_memory("career_goal", user_id=USER_A) is None
    assert await service.get_memory("career_goal", user_id=USER_B) == "Cybersecurity Expert"


@pytest.mark.asyncio
async def test_action_items_isolation():
    service = ActionItemService()

    item_a = await service.create_action_item(
        title="Predare conventie practica A",
        source="email",
        priority="high",
        user_id=USER_A,
    )
    item_b = await service.create_action_item(
        title="Inscriere colocviu B",
        source="telegram",
        priority="medium",
        user_id=USER_B,
    )

    # Listing action items only shows own items
    items_a = await service.list_action_items(user_id=USER_A)
    items_b = await service.list_action_items(user_id=USER_B)

    assert any(it["id"] == item_a["id"] for it in items_a)
    assert not any(it["id"] == item_b["id"] for it in items_a)

    assert any(it["id"] == item_b["id"] for it in items_b)
    assert not any(it["id"] == item_a["id"] for it in items_b)

    # User B cannot complete or alter User A's action item
    hacked = await service.update_action_item_status(item_id=item_a["id"], new_status="completed", user_id=USER_B)
    assert hacked is False

    # Verify item A is still open for User A
    open_a = await service.list_action_items(status="open", user_id=USER_A)
    assert any(it["id"] == item_a["id"] for it in open_a)


@pytest.mark.asyncio
async def test_email_service_isolation():
    service = EmailService()

    email_a = EmailMessageSchema(
        id=101,
        message_id="msg-a-01",
        account_type="personal",
        sender="secret_a@example.com",
        recipients=["user_a@example.com"],
        subject="Confidential Project A",
        body_text="Details for user A only",
        received_at=datetime.now(timezone.utc),
        is_read=False,
    )
    email_b = EmailMessageSchema(
        id=202,
        message_id="msg-b-01",
        account_type="personal",
        sender="secret_b@example.com",
        recipients=["user_b@example.com"],
        subject="Confidential Project B",
        body_text="Details for user B only",
        received_at=datetime.now(timezone.utc),
        is_read=False,
    )

    await service.persist_emails([email_a], user_id=USER_A)
    await service.persist_emails([email_b], user_id=USER_B)

    # Read back emails
    stored_a = await service.list_persisted_emails(user_id=USER_A, account_type="personal")
    stored_b = await service.list_persisted_emails(user_id=USER_B, account_type="personal")

    ids_a = [e.message_id for e in stored_a]
    ids_b = [e.message_id for e in stored_b]

    assert "msg-a-01" in ids_a
    assert "msg-b-01" not in ids_a

    assert "msg-b-01" in ids_b
    assert "msg-a-01" not in ids_b

    # Search isolation
    results_a = await service.search_emails(account_type="personal", query="Confidential Project B", user_id=USER_A)
    assert not any(e.message_id == "msg-b-01" for e in results_a)


@pytest.mark.asyncio
async def test_news_service_isolation():
    service = NewsService()

    art_a = NewsArticleSchema(
        id=1,
        title="AI Breakthrough in Healthcare for User A",
        url="https://news.example.com/a1",
        source_name="TechNews",
        topic="ai",
        summary="Summary for user A",
        relevance_score=0.95,
        published_at=datetime.now(timezone.utc),
    )
    art_b = NewsArticleSchema(
        id=2,
        title="Quantum Computing Leap for User B",
        url="https://news.example.com/b1",
        source_name="ScienceDaily",
        topic="quantum",
        summary="Summary for user B",
        relevance_score=0.88,
        published_at=datetime.now(timezone.utc),
    )

    await service.persist_articles([art_a], user_id=USER_A)
    await service.persist_articles([art_b], user_id=USER_B)

    persisted_a = await service.list_persisted_articles(limit=10, user_id=USER_A)
    persisted_b = await service.list_persisted_articles(limit=10, user_id=USER_B)

    urls_a = [a.url for a in persisted_a]
    urls_b = [a.url for a in persisted_b]

    assert "https://news.example.com/a1" in urls_a
    assert "https://news.example.com/b1" not in urls_a

    assert "https://news.example.com/b1" in urls_b
    assert "https://news.example.com/a1" not in urls_b


@pytest.mark.asyncio
async def test_practice_history_isolation():
    service = PracticeHistoryService()

    await service.save_exchange(
        academic_year="2026-2027",
        topic="bursa",
        question_summary="Cum procedez cu bursa de practica la FIESC?",
        answer_summary="Detaliile bursei se gasesc la decanat.",
        source_type="faq",
        user_id=USER_A,
    )
    await service.save_exchange(
        academic_year="2026-2027",
        topic="erasmus",
        question_summary="Unde depun cererea de mobilitate Erasmus practica?",
        answer_summary="La biroul de relatii internationale.",
        source_type="faq",
        user_id=USER_B,
    )

    similar_a = await service.find_similar(query="bursa", user_id=USER_A)
    similar_b = await service.find_similar(query="Erasmus", user_id=USER_B)

    assert any("bursa" in s.question_summary.lower() for s in similar_a)
    assert not any("erasmus" in s.question_summary.lower() for s in similar_a)

    assert any("erasmus" in s.question_summary.lower() for s in similar_b)
    assert not any("bursa" in s.question_summary.lower() for s in similar_b)


@pytest.mark.asyncio
async def test_conversation_memory_isolation():
    service = ConversationMemoryService()

    await service.add_message(session_id="session_general", sender_role="user", content="Secret note from User A", user_id=USER_A)
    await service.add_message(session_id="session_general", sender_role="user", content="Secret note from User B", user_id=USER_B)

    history_a = await service.get_history(session_id="session_general", user_id=USER_A)
    history_b = await service.get_history(session_id="session_general", user_id=USER_B)

    texts_a = [m["content"] for m in history_a]
    texts_b = [m["content"] for m in history_b]

    assert "Secret note from User A" in texts_a
    assert "Secret note from User B" not in texts_a

    assert "Secret note from User B" in texts_b
    assert "Secret note from User A" not in texts_b


@pytest.mark.asyncio
async def test_audit_service_isolation():
    service = AuditService()

    await service.log_event(user_request="Secret request A", selected_tool="tool_a", user_id=USER_A)
    await service.log_event(user_request="Secret request B", selected_tool="tool_b", user_id=USER_B)

    logs_a = await service.get_recent_logs(limit=20, user_id=USER_A)
    logs_b = await service.get_recent_logs(limit=20, user_id=USER_B)

    tools_a = [log.selected_tool for log in logs_a]
    tools_b = [log.selected_tool for log in logs_b]

    assert "tool_a" in tools_a
    assert "tool_b" not in tools_a

    assert "tool_b" in tools_b
    assert "tool_a" not in tools_b
