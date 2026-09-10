import pytest
from src.app.orchestrator.orchestrator import AIOrchestrator
from src.app.orchestrator.intent import IntentType


@pytest.mark.asyncio
async def test_detect_intent_greeting():
    orchestrator = AIOrchestrator()
    intent_result = await orchestrator.detect_intent("Salut, asistent!")
    assert intent_result.intent == IntentType.GENERAL_GREETING


@pytest.mark.asyncio
async def test_detect_intent_calendar():
    orchestrator = AIOrchestrator()
    intent_result = await orchestrator.detect_intent("Ce am mâine în calendar?")
    assert intent_result.intent == IntentType.CALENDAR_QUERY


@pytest.mark.asyncio
async def test_detect_intent_practice_query():
    orchestrator = AIOrchestrator()
    intent_result = await orchestrator.detect_intent("Care este procedura XZY9999?")
    assert intent_result.intent == IntentType.PRACTICE_QUERY
    assert "practice_agent" in intent_result.target_agents


@pytest.mark.asyncio
async def test_detect_intent_practice_history_query():
    orchestrator = AIOrchestrator()
    intent_result = await orchestrator.detect_intent("Ce am răspuns anul trecut despre Erasmus?")
    assert intent_result.intent == IntentType.PRACTICE_HISTORY_QUERY
    assert "practice_agent" in intent_result.target_agents


@pytest.mark.asyncio
async def test_process_request_flow():
    orchestrator = AIOrchestrator()
    response_data = await orchestrator.process_request("Salut!")
    assert "response" in response_data
    assert "intent" in response_data
    assert response_data["intent"] == IntentType.GENERAL_GREETING.value


@pytest.mark.asyncio
async def test_detect_intent_aggregated_overview():
    orchestrator = AIOrchestrator()
    for phrase in ["Ce mai am de făcut?", "ce am de facut?", "/sinteza", "/overview"]:
        res = await orchestrator.detect_intent(phrase)
        assert res.intent == IntentType.AGGREGATED_OVERVIEW
        assert "calendar_agent" in res.target_agents
        assert "action_item_service" in res.target_agents


@pytest.mark.asyncio
async def test_detect_intent_daily_briefing():
    orchestrator = AIOrchestrator()
    for phrase in ["/briefing", "fă-mi un briefing matinal", "rezumatul zilei"]:
        res = await orchestrator.detect_intent(phrase)
        assert res.intent == IntentType.DAILY_BRIEFING
        assert "calendar_agent" in res.target_agents


@pytest.mark.asyncio
async def test_detect_intent_memory_manage():
    orchestrator = AIOrchestrator()
    for phrase in ["Ține minte că prefer răspunsuri scurte", "/memorie", "ce preferințe ai memorate", "uită tot"]:
        res = await orchestrator.detect_intent(phrase)
        assert res.intent == IntentType.MEMORY_MANAGE
        assert "user_memory_service" in res.target_agents


@pytest.mark.asyncio
async def test_process_request_aggregated_overview_t5():
    """Test Section 6 & Section 27 Test T5: Multi-Tool Synthesis."""
    orchestrator = AIOrchestrator()
    res = await orchestrator.process_request("Ce mai am de făcut?")
    assert res["intent"] == IntentType.AGGREGATED_OVERVIEW.value
    assert "Sinteza activităților tale" in res["response"]
    assert "Calendar" in res["response"]
    assert "Sarcini" in res["response"]
    assert "E-mailuri" in res["response"]
    assert "Practică UNITBV" in res["response"]
    assert "28 August 2026" in res["response"]
    assert "2 Septembrie 2026" in res["response"]
    assert "inline_keyboard" in res


@pytest.mark.asyncio
async def test_process_request_daily_briefing():
    orchestrator = AIOrchestrator()
    res = await orchestrator.process_request("/briefing")
    assert res["intent"] == IntentType.DAILY_BRIEFING.value
    assert "Sinteza ta zilnică academică" in res["response"]
    assert "inline_keyboard" in res

