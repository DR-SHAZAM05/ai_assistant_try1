from typing import List, Optional
from datetime import datetime, timedelta, timezone
from src.app.integrations.google_calendar.base import CalendarProvider
from src.app.schemas.calendar import CalendarEventSchema, CalendarQueryFilter
from src.app.core.logging import logger

now = datetime.now(timezone.utc)
today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
tomorrow_start = today_start + timedelta(days=1)
next_week_start = today_start + timedelta(days=7)

MOCK_EVENTS: List[CalendarEventSchema] = [
    # Today events
    CalendarEventSchema(
        id="event-today-1",
        summary="Ședință Departament FIESC UNITBV",
        description="Discuții despre convențiile de practică și colocviu.",
        location="Corp V, Sala V102",
        start_time=today_start + timedelta(hours=10),
        end_time=today_start + timedelta(hours=11, minutes=30),
        status="confirmed"
    ),
    CalendarEventSchema(
        id="event-today-2",
        summary="Consultații Practică Studenți",
        description="Preluare caiete de practică și adeverințe.",
        location="Corp N, Sala N204",
        start_time=today_start + timedelta(hours=14),
        end_time=today_start + timedelta(hours=16),
        status="confirmed"
    ),
    # Tomorrow events
    CalendarEventSchema(
        id="event-tomorrow-1",
        summary="Curs Inteligență Artificială și Agenți Autonomous",
        description="Curs introductiv RAG și Arhitecturi de Asistenți AI.",
        location="Amfiteatrul A3 UNITBV",
        start_time=tomorrow_start + timedelta(hours=9),
        end_time=tomorrow_start + timedelta(hours=11),
        status="confirmed"
    ),
    CalendarEventSchema(
        id="event-tomorrow-2",
        summary="Laborator Sisteme Embedded & RW612 NXP",
        description="Laborator practic microcontrollere.",
        location="Laborator L2 Corp V",
        start_time=tomorrow_start + timedelta(hours=12),
        end_time=tomorrow_start + timedelta(hours=14),
        status="confirmed"
    ),
    # Next week events
    CalendarEventSchema(
        id="event-nextweek-1",
        summary="Colocviu Final Practică 2026-2027",
        description="Prezentare caiete de practică și adeverințe ore efectuate.",
        location="Sala V101 UNITBV",
        start_time=next_week_start + timedelta(hours=10),
        end_time=next_week_start + timedelta(hours=13),
        status="confirmed"
    )
]


class MockCalendarProvider(CalendarProvider):
    """
    Mock Calendar Provider returning sample academic events for deterministic testing.
    """

    def __init__(self):
        self._storage: List[CalendarEventSchema] = list(MOCK_EVENTS)

    async def fetch_events(
        self,
        query_filter: CalendarQueryFilter
    ) -> List[CalendarEventSchema]:
        results = []
        for evt in self._storage:
            # Check overlap between event interval and query_filter interval
            if evt.start_time <= query_filter.end_time and evt.end_time >= query_filter.start_time:
                if query_filter.query:
                    text = f"{evt.summary} {evt.description or ''} {evt.location or ''}".lower()
                    if query_filter.query.lower() in text:
                        results.append(evt)
                else:
                    results.append(evt)

        # Sort chronologically
        results.sort(key=lambda x: x.start_time)
        return results[:query_filter.max_results]

    async def create_event(
        self,
        event: CalendarEventSchema
    ) -> CalendarEventSchema:
        if not event.id:
            event.id = f"event-custom-{len(self._storage)+1}"
        self._storage.append(event)
        logger.info(f"[MockCalendarProvider] Created event: {event.summary}")
        return event

    async def delete_event(
        self,
        event_id: str
    ) -> bool:
        initial_len = len(self._storage)
        self._storage = [e for e in self._storage if e.id != event_id]
        return len(self._storage) < initial_len

    async def update_event(
        self,
        event_id: str,
        updates: dict,
    ) -> dict:
        """Update an existing mock event and return the updated dict."""
        for idx, evt in enumerate(self._storage):
            if evt.id == event_id:
                for key, value in updates.items():
                    if hasattr(evt, key):
                        setattr(evt, key, value)
                logger.info(f"[MockCalendarProvider] Updated event {event_id}")
                return {
                    "id": evt.id,
                    "summary": evt.summary,
                    "description": evt.description,
                    "location": evt.location,
                    "start_time": evt.start_time,
                    "end_time": evt.end_time,
                    "status": evt.status,
                }
        raise Exception(f"Event {event_id} not found in mock storage")
