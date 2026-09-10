from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class CalendarEventSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    summary: str
    description: Optional[str] = None
    location: Optional[str] = None
    start_time: datetime
    end_time: datetime
    is_all_day: bool = False
    status: str = "confirmed"  # "confirmed", "tentative", "cancelled"
    creator_email: Optional[str] = None
    html_link: Optional[str] = None


class CalendarQueryFilter(BaseModel):
    start_time: datetime
    end_time: datetime
    query: Optional[str] = None
    max_results: int = 10
