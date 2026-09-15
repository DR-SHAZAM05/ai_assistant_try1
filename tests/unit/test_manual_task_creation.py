"""Test manual task creation functionality."""

import pytest
from src.app.orchestrator.orchestrator import AIOrchestrator
from src.app.orchestrator.intent import IntentType
from src.app.services.action_item_service import ActionItemService


@pytest.mark.asyncio
async def test_manual_task_creation_intent_detection():
    """Test that manual task creation is detected correctly."""
    orchestrator = AIOrchestrator()
    
    # Test various task creation patterns
    test_phrases = [
        "Adauga sarcina: Finalizeaza referatul",
        "Creeaza task: Termina proiectul",
        "Sarcina noua: Prezinta raportul",
        "Adauga o sarcina: Contacteaza profesorul",
    ]
    
    for phrase in test_phrases:
        result = await orchestrator.detect_intent(phrase, user_id="test_user")
        assert result.intent == IntentType.TASKS_CREATE, f"Failed for phrase: {phrase}"
        assert result.confidence >= 0.9


@pytest.mark.asyncio
async def test_manual_task_creation_execution():
    """Test that manual task creation actually creates a task in the database."""
    orchestrator = AIOrchestrator()
    action_service = ActionItemService()
    test_user_id = "test_user_manual_creation"
    
    # Create a task
    result = await orchestrator.process_request(
        "Adauga sarcina: Finalizeaza laboratorul de sisteme",
        user_id=test_user_id
    )
    
    assert result["intent"] == "tasks_create"
    assert "creata cu succes" in result["response"].lower() or "creat cu succes" in result["response"].lower()
    
    # Verify the task was created in the database
    items = await action_service.list_action_items(user_id=test_user_id)
    assert len(items) >= 1
    assert any("laborator" in item["title"].lower() for item in items)
    
    # Verify user_id consistency
    created_task = [item for item in items if "laborator" in item["title"].lower()][0]
    assert created_task["user_id"] == test_user_id
    assert created_task["status"] == "open"


@pytest.mark.asyncio
async def test_manual_task_creation_and_listing():
    """Test the complete flow: create task -> list task -> task appears."""
    orchestrator = AIOrchestrator()
    action_service = ActionItemService()
    test_user_id = "test_user_complete_flow"
    
    # Create a task
    create_result = await orchestrator.process_request(
        "Adauga sarcina: Revizuirea proiectului de licenta",
        user_id=test_user_id
    )
    assert create_result["intent"] == "tasks_create"
    
    # List tasks
    list_result = await orchestrator.process_request(
        "Ce sarcini am?",
        user_id=test_user_id
    )
    assert list_result["intent"] == "tasks_query"
    assert "licenta" in list_result["response"].lower() or "proiect" in list_result["response"].lower()


@pytest.mark.asyncio
async def test_manual_task_creation_with_priority():
    """Test that priority can be specified in task creation."""
    orchestrator = AIOrchestrator()
    action_service = ActionItemService()
    test_user_id = "test_user_priority"
    
    # Create a high priority task
    result = await orchestrator.process_request(
        "Adauga sarcina cu prioritate mare: Trimite adeverinta",
        user_id=test_user_id
    )
    
    assert result["intent"] == "tasks_create"
    
    # Verify the task was created
    items = await action_service.list_action_items(user_id=test_user_id)
    assert len(items) >= 1
    # The task should have high priority
    high_priority_tasks = [item for item in items if item.get("priority") == "high"]
    assert len(high_priority_tasks) >= 1


@pytest.mark.asyncio
async def test_tasks_create_tool_registered():
    """Test that the tasks_create tool is registered in the tool registry."""
    from src.app.orchestrator.tool_registry import global_tool_registry
    
    tools = global_tool_registry.get_tool_definitions()
    tool_names = [t['function']['name'] for t in tools]
    
    assert "tasks_create" in tool_names
    assert "tasks_list" in tool_names