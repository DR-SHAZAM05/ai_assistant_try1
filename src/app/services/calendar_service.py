from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional, Dict, Any
from src.app.integrations.google_calendar.factory import get_calendar_provider
from src.app.schemas.calendar import CalendarEventSchema, CalendarQueryFilter
from src.app.core.logging import logger


class CalendarService:
    """
    Business Logic Service for Calendar operations and Natural Language Date Parsing.
    """

    def parse_natural_date_range(self, prompt: str) -> Tuple[datetime, datetime, str]:
        """
        Parses natural language date expressions (azi, mâine, săptămâna viitoare) into UTC start and end datetimes.
        """
        prompt_lower = prompt.lower()
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        import re
        interval_match = re.search(r'(?:între|intre)\s+(?:orele\s+)?(\d{1,2})(?::\d{2})?\s+și\s+(\d{1,2})', prompt_lower)
        if interval_match:
            h1, h2 = int(interval_match.group(1)), int(interval_match.group(2))
            base_date = today_start
            day_tag = "astăzi"
            if any(kw in prompt_lower for kw in ["mâine", "maine"]):
                base_date = today_start + timedelta(days=1)
                day_tag = "mâine"
            start = base_date.replace(hour=h1, minute=0, second=0)
            end = base_date.replace(hour=h2, minute=0, second=0)
            label = f"intervalul {h1:02d}:00 – {h2:02d}:00 ({day_tag})"
            return start, end, label

        if any(kw in prompt_lower for kw in ["următorul eveniment", "urmatorul eveniment", "următoarea ședință", "urmatoarea sedinta", "următoarea întâlnire", "urmatoarea intalnire"]):
            start = now
            end = now + timedelta(days=14)
            label = "următorul eveniment"
            return start, end, label

        if any(kw in prompt_lower for kw in ["mâine", "maine", "tomorrow"]):
            start = today_start + timedelta(days=1)
            end = today_end + timedelta(days=1)
            label = "mâine"
        elif any(kw in prompt_lower for kw in ["poimâine", "poimaine"]):
            start = today_start + timedelta(days=2)
            end = today_end + timedelta(days=2)
            label = "poimâine"
        elif any(kw in prompt_lower for kw in ["săptămâna viitoare", "saptamana viitoare", "next week"]):
            # Start next Monday, end next Sunday
            days_until_next_monday = (7 - today_start.weekday())
            start = today_start + timedelta(days=days_until_next_monday)
            end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
            label = "săptămâna viitoare"
        elif any(kw in prompt_lower for kw in ["săptămâna aceasta", "saptamana aceasta", "this week"]):
            start = today_start - timedelta(days=today_start.weekday())
            end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
            label = "săptămâna aceasta"
        elif any(kw in prompt_lower for kw in ["următoarele 7 zile", "urmatoarele 7 zile", "7 zile"]):
            start = today_start
            end = today_end + timedelta(days=7)
            label = "următoarele 7 zile"
        else:
            # Default to today
            start = today_start
            end = today_end
            label = "astăzi"

        return start, end, label

    async def get_events(
        self,
        prompt: str,
        query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetches events matching natural language prompt date range.
        """
        start_time, end_time, label = self.parse_natural_date_range(prompt)
        query_filter = CalendarQueryFilter(
            start_time=start_time,
            end_time=end_time,
            query=query
        )

        provider = get_calendar_provider()
        events = await provider.fetch_events(query_filter)

        is_hourly = "intervalul" in label
        is_next = label == "următorul eveniment"

        return {
            "label": label,
            "start_time": start_time,
            "end_time": end_time,
            "events": events,
            "is_hourly_interval": is_hourly,
            "is_next_event": is_next,
        }

    async def detect_conflicts(self, events: List[CalendarEventSchema]) -> List[Tuple[CalendarEventSchema, CalendarEventSchema]]:
        """
        Detects overlapping time conflicts between calendar events.
        """
        conflicts = []
        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                evt1, evt2 = events[i], events[j]
                if evt1.start_time < evt2.end_time and evt2.start_time < evt1.end_time:
                    conflicts.append((evt1, evt2))
        return conflicts

    async def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        description: Optional[str] = None,
        location: Optional[str] = None,
    ) -> CalendarEventSchema:
        """Create a new event in Google Calendar."""
        event = CalendarEventSchema(
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            status="confirmed",
        )
        provider = get_calendar_provider()
        return await provider.create_event(event)

    async def delete_event(self, event_id: str) -> bool:
        """Delete an event from Google Calendar by its ID."""
        provider = get_calendar_provider()
        return await provider.delete_event(event_id)

