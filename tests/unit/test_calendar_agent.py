"""Unit tests for CalendarAgent and CalendarService — Phase 4 compatible."""
import pytest
from datetime import datetime, timedelta, timezone

from src.app.agents.calendar_agent import CalendarAgent
from src.app.integrations.google_calendar.mock_provider import MockCalendarProvider
from src.app.schemas.calendar import CalendarQueryFilter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "user_test_001"


def _make_agent() -> CalendarAgent:
    """Return a CalendarAgent with no calendar_service (read-only queries only)."""
    return CalendarAgent()


# ---------------------------------------------------------------------------
# Test: MockCalendarProvider.fetch_events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_calendar_provider_fetch():
    provider = MockCalendarProvider()
    now = datetime.now(timezone.utc)
    q_filter = CalendarQueryFilter(
        start_time=now - timedelta(days=1),
        end_time=now + timedelta(days=10),
    )
    events = await provider.fetch_events(q_filter)
    assert len(events) > 0


# ---------------------------------------------------------------------------
# Test: CalendarAgent._parse_date_range (date parsing logic)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_service_date_parsing():
    """CalendarAgent._parse_date_range correctly resolves relative date labels."""
    agent = _make_agent()
    now = datetime.now(agent.tz)

    # 'mâine'
    start_m, end_m, label_m = agent._parse_date_range("Ce am mâine?", now)
    assert label_m == "mâine"
    assert end_m >= start_m

    # 'săptămâna viitoare'
    start_w, end_w, label_w = agent._parse_date_range("Ce am săptămâna viitoare?", now)
    assert label_w == "săptămâna viitoare"
    assert end_w > start_w


# ---------------------------------------------------------------------------
# Test: CalendarAgent.handle_calendar_query (with user_id — Phase 4 API)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_agent_handle_query():
    agent = _make_agent()
    res = await agent.handle_calendar_query(user_id=USER_ID, user_prompt="Ce am mâine în calendar?")
    assert "text" in res
    assert isinstance(res["text"], str) and len(res["text"]) > 0


# ---------------------------------------------------------------------------
# Test: CalendarAgent.handle_create_event_query (Phase 4 – pending flow)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_agent_handle_create_event():
    """
    In Phase 4, handle_create_event_query returns an error when no calendar_service
    is injected (no DB session available in plain unit tests).
    It must NOT raise an unhandled exception and must return a dict with 'text'.
    """
    class FakeLLM:
        async def generate_completion(
            self, system_prompt: str, user_prompt: str, temperature: float = 0.1
        ) -> str:
            return (
                '{"summary": "Sedinta Practica", '
                '"start_time": "2026-09-20T14:00:00", '
                '"end_time": "2026-09-20T15:00:00", '
                '"location": "Online", '
                '"description": "Discutii conventie"}'
            )

    agent = CalendarAgent(llm_provider=FakeLLM())
    res = await agent.handle_create_event_query(
        user_id=USER_ID,
        user_prompt="Adaugă în calendar ședință de practică pe 20 septembrie la ora 14",
    )
    # Without an injected calendar_service the agent must return gracefully
    assert "text" in res
    assert isinstance(res["text"], str)


