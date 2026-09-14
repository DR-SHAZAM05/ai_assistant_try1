from enum import Enum
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime

class CalendarIntentType(str, Enum):
    QUERY = "CALENDAR_QUERY"
    CREATE = "CALENDAR_CREATE"
    UPDATE = "CALENDAR_UPDATE"
    DELETE = "CALENDAR_DELETE"

class CalendarQueryIntent(BaseModel):
    intent: CalendarIntentType = Field(default=CalendarIntentType.QUERY, const=True)
    # optional natural language date range or explicit timestamps
    date_range: Optional[str] = None  # e.g. "mâine", "30/09/2024", "2024-09-30 to 2024-10-07"
    # optional free‑text filter for event title/description
    query: Optional[str] = None
    max_results: Optional[int] = Field(default=10, ge=1, le=100)

class CalendarEventBase(BaseModel):
    summary: str
    description: Optional[str] = None
    location: Optional[str] = None
    # start/end can be either ISO8601 datetime strings or "all_day" date strings (YYYY‑MM‑DD)
    start: str
    end: str
    is_all_day: bool = False

    @validator("start", "end")
    def validate_iso(cls, v):
        # basic validation – real validation occurs in service layer
        return v

class CalendarCreateIntent(BaseModel):
    intent: CalendarIntentType = Field(default=CalendarIntentType.CREATE, const=True)
    event: CalendarEventBase
    # optional recurrence rule (RFC5545) – not used now but kept for future extensibility
    recurrence: Optional[List[str]] = None

class CalendarUpdateIntent(BaseModel):
    intent: CalendarIntentType = Field(default=CalendarIntentType.UPDATE, const=True)
    # identifier of the event to update – could be Google event ID or a custom UUID
    event_id: str = Field(..., description="Google Calendar event identifier")
    # fields that can be updated – same schema as create but all optional
    summary: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    is_all_day: Optional[bool] = None

class CalendarDeleteIntent(BaseModel):
    intent: CalendarIntentType = Field(default=CalendarIntentType.DELETE, const=True)
    event_id: str = Field(..., description="Google Calendar event identifier to delete")
