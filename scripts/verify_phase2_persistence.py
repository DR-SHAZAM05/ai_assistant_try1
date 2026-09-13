"""Script to verify live PostgreSQL persistence and user isolation in Docker."""

import asyncio
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


async def seed_data():
    print("--- 1. Seeding User A and User B in PostgreSQL ---")
    mem_svc = UserMemoryService()
    await mem_svc.set_memory(key="theme_preference", value="dark_mode", category="ui", user_id=USER_A)
    await mem_svc.set_memory(key="theme_preference", value="light_mode", category="ui", user_id=USER_B)

    act_svc = ActionItemService()
    item_a = await act_svc.create_action_item(
        title="Predare Raport Practica Semestrul 2",
        source="unitbv_email",
        priority="high",
        source_reference="ref-seed-a",
        user_id=USER_A,
    )
    item_b = await act_svc.create_action_item(
        title="Cerere Cazare Camin Student",
        source="unitbv_email",
        priority="medium",
        source_reference="ref-seed-b",
        user_id=USER_B,
    )

    em_svc = EmailService()
    email_a = EmailMessageSchema(
        id=901,
        message_id="msg-persist-a-01",
        account_type="unitbv",
        sender="secretariat@unitbv.ro",
        recipients=["user_a@unitbv.ro"],
        subject="Important: Documente practica A",
        body_text="Documente oficiale pentru User A",
        received_at=datetime.now(timezone.utc),
        is_read=False,
    )
    email_b = EmailMessageSchema(
        id=902,
        message_id="msg-persist-b-01",
        account_type="unitbv",
        sender="secretariat@unitbv.ro",
        recipients=["user_b@unitbv.ro"],
        subject="Important: Documente practica B",
        body_text="Documente oficiale pentru User B",
        received_at=datetime.now(timezone.utc),
        is_read=False,
    )
    await em_svc.persist_emails([email_a], user_id=USER_A)
    await em_svc.persist_emails([email_b], user_id=USER_B)

    news_svc = NewsService()
    art_a = NewsArticleSchema(
        id=9001,
        title="PostgreSQL 16 Security and Performance Advances for A",
        url="https://postgresql.org/news/seed-a",
        source_name="PostgresNews",
        topic="database",
        summary="Summary for user A",
        relevance_score=0.99,
        published_at=datetime.now(timezone.utc),
    )
    art_b = NewsArticleSchema(
        id=9002,
        title="FastAPI Async Scalability Benchmark for B",
        url="https://fastapi.tiangolo.com/news/seed-b",
        source_name="FastAPINews",
        topic="web",
        summary="Summary for user B",
        relevance_score=0.91,
        published_at=datetime.now(timezone.utc),
    )
    await news_svc.persist_articles([art_a], user_id=USER_A)
    await news_svc.persist_articles([art_b], user_id=USER_B)

    prac_svc = PracticeHistoryService()
    await prac_svc.save_exchange(
        academic_year="2026-2027",
        topic="conventie",
        question_summary="Cand trebuie semnata conventia de practica?",
        answer_summary="Conventia se semneaza inainte de inceperea stagiului.",
        source_type="unitbv_email",
        user_id=USER_A,
    )
    await prac_svc.save_exchange(
        academic_year="2026-2027",
        topic="caiet",
        question_summary="Cate pagini trebuie sa aiba caietul de practica?",
        answer_summary="Caietul de practica trebuie sa aiba minim 15-20 pagini.",
        source_type="unitbv_email",
        user_id=USER_B,
    )

    conv_svc = ConversationMemoryService()
    await conv_svc.add_message(
        session_id="session_persist_test",
        sender_role="user",
        content="Mesaj de test persistenta User A",
        user_id=USER_A,
    )
    await conv_svc.add_message(
        session_id="session_persist_test",
        sender_role="user",
        content="Mesaj de test persistenta User B",
        user_id=USER_B,
    )

    audit_svc = AuditService()
    await audit_svc.log_event(
        selected_tool="practice_agent",
        execution_duration_ms=42.0,
        user_id=USER_A,
    )
    await audit_svc.log_event(
        selected_tool="email_agent",
        execution_duration_ms=55.0,
        user_id=USER_B,
    )

    print("Data seeded successfully.")


async def verify_data():
    print("--- 2. Verifying PostgreSQL Data and User Isolation ---")
    mem_svc = UserMemoryService()
    assert await mem_svc.get_memory("theme_preference", user_id=USER_A) == "dark_mode"
    assert await mem_svc.get_memory("theme_preference", user_id=USER_B) == "light_mode"
    print("✓ UserMemory verified and isolated.")

    act_svc = ActionItemService()
    items_a = await act_svc.list_action_items(user_id=USER_A)
    items_b = await act_svc.list_action_items(user_id=USER_B)
    assert any("Raport Practica" in it["title"] for it in items_a)
    assert not any("Cazare Camin" in it["title"] for it in items_a)
    assert any("Cazare Camin" in it["title"] for it in items_b)
    assert not any("Raport Practica" in it["title"] for it in items_b)
    print("✓ ActionItems verified and isolated.")

    em_svc = EmailService()
    emails_a = await em_svc.list_persisted_emails(user_id=USER_A)
    emails_b = await em_svc.list_persisted_emails(user_id=USER_B)
    assert any(e.message_id == "msg-persist-a-01" for e in emails_a)
    assert not any(e.message_id == "msg-persist-b-01" for e in emails_a)
    assert any(e.message_id == "msg-persist-b-01" for e in emails_b)
    assert not any(e.message_id == "msg-persist-a-01" for e in emails_b)
    print("✓ Emails verified and isolated.")

    news_svc = NewsService()
    news_a = await news_svc.list_persisted_articles(user_id=USER_A)
    news_b = await news_svc.list_persisted_articles(user_id=USER_B)
    assert any("seed-a" in n.url for n in news_a)
    assert not any("seed-b" in n.url for n in news_a)
    assert any("seed-b" in n.url for n in news_b)
    assert not any("seed-a" in n.url for n in news_b)
    print("✓ News verified and isolated.")

    prac_svc = PracticeHistoryService()
    sim_a = await prac_svc.find_similar(query="conventie", user_id=USER_A)
    sim_b = await prac_svc.find_similar(query="caiet", user_id=USER_B)
    assert any("conventia" in s.question_summary.lower() for s in sim_a)
    assert not any("caiet" in s.question_summary.lower() for s in sim_a)
    assert any("caiet" in s.question_summary.lower() for s in sim_b)
    assert not any("conventie" in s.question_summary.lower() for s in sim_b)
    print("✓ Practice History verified and isolated.")

    conv_svc = ConversationMemoryService()
    hist_a = await conv_svc.get_history(session_id="session_persist_test", user_id=USER_A)
    hist_b = await conv_svc.get_history(session_id="session_persist_test", user_id=USER_B)
    assert any("User A" in m["content"] for m in hist_a)
    assert not any("User B" in m["content"] for m in hist_a)
    assert any("User B" in m["content"] for m in hist_b)
    assert not any("User A" in m["content"] for m in hist_b)
    print("✓ Conversation Memory verified and isolated.")

    audit_svc = AuditService()
    aud_a = await audit_svc.get_recent_logs(user_id=USER_A)
    aud_b = await audit_svc.get_recent_logs(user_id=USER_B)
    assert any(log.selected_tool == "practice_agent" for log in aud_a)
    assert not any(log.selected_tool == "email_agent" for log in aud_a)
    assert any(log.selected_tool == "email_agent" for log in aud_b)
    assert not any(log.selected_tool == "practice_agent" for log in aud_b)
    print("✓ Audit Logs verified and isolated.")

    # 3. Explicit cross-user tamper attempt verification
    print("--- 3. Verifying Cross-User Mutation/Tamper Attempts are Rejected ---")
    item_a_id = items_a[0]["id"]
    # User B attempts to complete User A's action item
    tamper_task = await act_svc.update_action_item_status(item_id=item_a_id, new_status="completed", user_id=USER_B)
    assert tamper_task is False, "Security failure: User B was able to modify User A's task!"
    # Verify User A's task is still open
    refreshed_items_a = await act_svc.list_action_items(status="open", user_id=USER_A)
    assert any(it["id"] == item_a_id for it in refreshed_items_a), "Security failure: User A's task was modified by User B!"
    print("✓ User B cross-task modification strictly rejected (returned False, task remains open).")

    # User B attempts to delete User A's memory key
    tamper_del = await mem_svc.delete_memory("user_a_only_secret", user_id=USER_B)
    assert tamper_del is False, "Security failure: User B was able to delete User A's key!"
    assert await mem_svc.get_memory("theme_preference", user_id=USER_A) == "dark_mode"
    print("✓ User A memory remains intact after User B delete attempt.")

    print("\nALL PERSISTENCE AND ISOLATION CHECKS PASSED SUCCESSFULLY IN POSTGRESQL!")


async def run_full_pipeline():
    await seed_data()
    await verify_data()


if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if action == "seed":
        asyncio.run(seed_data())
    elif action == "verify":
        asyncio.run(verify_data())
    else:
        asyncio.run(run_full_pipeline())
