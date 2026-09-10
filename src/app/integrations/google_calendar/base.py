from abc import ABC, abstractmethod
from typing import List, Optional
from src.app.schemas.calendar import CalendarEventSchema, CalendarQueryFilter


class CalendarProvider(ABC):
    """
    Abstract Base Class for Calendar Providers (Google Calendar, Mock, Outlook Calendar).
    Ensures Calendar Service logic is completely decoupled from external Google API protocols.
    """

    @abstractmethod
    async def fetch_events(
        self,
        query_filter: CalendarQueryFilter
    ) -> List[CalendarEventSchema]:
        """
        Fetch events matching date range and optional keyword filter.
        """
        pass

    @abstractmethod
    async def create_event(
        self,
        event: CalendarEventSchema
    ) -> CalendarEventSchema:
        """
        Create a new calendar event (requires Human-in-the-Loop approval).
        """
        pass

    @abstractmethod
    async def delete_event(
        self,
        event_id: str
    ) -> bool:
        """
        Delete an existing calendar event (requires Human-in-the-Loop approval).
        """
        pass
