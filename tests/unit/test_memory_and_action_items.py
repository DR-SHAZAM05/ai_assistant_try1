import pytest
from src.app.memory.conversation_memory import ConversationMemoryService
from src.app.memory.user_memory import UserMemoryService
from src.app.services.action_item_service import ActionItemService


@pytest.mark.asyncio
async def test_conversation_memory_service():
    mem = ConversationMemoryService()
    session_id = "test-session-123"

    await mem.add_message(session_id=session_id, sender_role="user", content="Ce am mâine în calendar?")
    await mem.add_message(session_id=session_id, sender_role="assistant", content="Ai 2 întâlniri.")

    history = await mem.get_history(session_id=session_id, limit=5)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Ce am mâine în calendar?"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Ai 2 întâlniri."


@pytest.mark.asyncio
async def test_user_memory_service():
    user_mem = UserMemoryService()

    await user_mem.set_memory(key="preferred_email_signature", value="Cu stimă, Student", category="email")
    val = await user_mem.get_memory("preferred_email_signature")
    assert val == "Cu stimă, Student"

    memories = await user_mem.list_memories(category="email")
    assert any(m["key"] == "preferred_email_signature" for m in memories)


@pytest.mark.asyncio
async def test_action_item_service():
    service = ActionItemService()

    item = await service.create_action_item(
        title="Trimite adeverința de practică",
        source="email",
        priority="high",
        source_reference="msg-unitbv-102"
    )
    assert item["title"] == "Trimite adeverința de practică"
    assert item["status"] == "open"

    items = await service.list_action_items(status="open")
    assert len(items) > 0

    updated = await service.update_action_item_status(item["id"], "completed")
    assert updated is True


@pytest.mark.asyncio
async def test_orchestrator_tasks_query():
    from src.app.orchestrator.orchestrator import AIOrchestrator
    orc = AIOrchestrator()
    service = ActionItemService()

    # Create open task
    item = await service.create_action_item(
        title="Predare caiet practica",
        source="email",
        priority="high",
        source_reference="msg-test-orch-tasks"
    )

    res_list = await orc.process_request("Ce sarcini am?")
    assert res_list["intent"] == "tasks_query"
    assert "Predare caiet practica" in res_list["response"]

    # Mark as completed
    res_comp = await orc.process_request(f"Marchează sarcina {item['id']} ca rezolvată")
    assert "finalizată" in res_comp["response"] or "finalizata" in res_comp["response"]


@pytest.mark.asyncio
async def test_user_memory_delete():
    user_mem = UserMemoryService()
    await user_mem.set_memory(key="temp_key_to_delete", value="test_val")
    val_before = await user_mem.get_memory("temp_key_to_delete")
    assert val_before == "test_val"

    deleted = await user_mem.delete_memory("temp_key_to_delete")
    assert deleted is True

    val_after = await user_mem.get_memory("temp_key_to_delete")
    assert val_after is None


@pytest.mark.asyncio
async def test_orchestrator_memory_management_lifecycle():
    from src.app.orchestrator.orchestrator import AIOrchestrator
    orc = AIOrchestrator()

    # 1. Store a preference
    store_res = await orc.process_request("Ține minte că prefer răspunsuri foarte scurte și concise")
    assert store_res["intent"] == "memory_manage"
    assert "Am salvat noua regulă" in store_res["response"]

    # 2. List preferences
    list_res = await orc.process_request("Ce preferințe ai salvate?")
    assert list_res["intent"] == "memory_manage"
    assert "răspunsuri foarte scurte" in list_res["response"] or "preferințe" in list_res["response"].lower()

    # 3. Reset preferences
    clear_res = await orc.process_request("Uită tot ce ai memorat")
    assert clear_res["intent"] == "memory_manage"
    assert "resetată" in clear_res["response"] or "șters" in clear_res["response"]

