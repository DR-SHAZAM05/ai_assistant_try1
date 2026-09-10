import pytest
from src.app.services.calendar_service import CalendarService
from src.app.agents.calendar_agent import CalendarAgent
from src.app.integrations.google_calendar.mock_provider import MockCalendarProvider
from src.app.schemas.calendar import CalendarQueryFilter
from datetime import datetime, timedelta, timezone


@pytest.mark.asyncio
async def test_calendar_service_date_parsing():
    service = CalendarService()
    
    # Test 'mâine'
    start_m, end_m, label_m = service.parse_natural_date_range("Ce am mâine?")
    assert label_m == "mâine"
    assert (end_m - start_m).days == 0

    # Test 'săptămâna viitoare'
    start_w, end_w, label_w = service.parse_natural_date_range("Ce am săptămâna viitoare?")
    assert label_w == "săptămâna viitoare"
    assert end_w > start_w


@pytest.mark.asyncio
async def test_mock_calendar_provider_fetch():
    provider = MockCalendarProvider()
    now = datetime.now(timezone.utc)
    q_filter = CalendarQueryFilter(
        start_time=now - timedelta(days=1),
        end_time=now + timedelta(days=10)
    )
    events = await provider.fetch_events(q_filter)
    assert len(events) > 0


@pytest.mark.asyncio
async def test_calendar_agent_handle_query():
    agent = CalendarAgent()
    res = await agent.handle_calendar_query("Ce am mâine în calendar?")
    assert "text" in res
    assert "mâine" in res["text"].lower() or "programul" in res["text"].lower()
    assert res["count"] >= 0


@pytest.mark.asyncio
async def test_calendar_service_create_and_delete():
    service = CalendarService()
    now = datetime.now(timezone.utc)
    evt = await service.create_event(
        summary="Test Meeting FIESC",
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        description="Test description",
        location="Corp V, Sala V101",
    )
    assert evt.id is not None
    assert evt.summary == "Test Meeting FIESC"

    # Delete event
    deleted = await service.delete_event(evt.id)
    assert deleted is True


@pytest.mark.asyncio
async def test_calendar_agent_handle_create_event():
    class FakeLLM:
        async def generate_completion(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
            return '{"summary": "Sedinta Practica", "start_time": "2026-09-12T14:00:00", "end_time": "2026-09-12T15:00:00", "location": "Online", "description": "Discutii conventie"}'

    agent = CalendarAgent(llm_provider=FakeLLM())
    res = await agent.handle_create_event_query("Adaugă în calendar ședință de practică pe 12 septembrie la ora 14")
    assert res["status"] == "success"
    assert "Eveniment programat cu succes" in res["text"]
    assert "Sedinta Practica" in res["text"]

