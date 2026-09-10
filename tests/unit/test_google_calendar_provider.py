from datetime import datetime, timezone

import pytest

from src.app.integrations.google_calendar.google_provider import GoogleCalendarProvider
from src.app.schemas.calendar import CalendarEventSchema, CalendarQueryFilter


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeEventsResource:
    def __init__(self):
        self.list_kwargs = None
        self.insert_kwargs = None
        self.deleted_id = None

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return FakeRequest(
            {
                "items": [
                    {
                        "id": "google-1",
                        "summary": "Laborator UNITBV",
                        "start": {"dateTime": "2026-08-30T09:00:00+03:00"},
                        "end": {"dateTime": "2026-08-30T11:00:00+03:00"},
                        "creator": {"email": "coordonator@unitbv.ro"},
                        "htmlLink": "https://calendar.google.test/event/google-1",
                    }
                ]
            }
        )

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        result = dict(kwargs["body"])
        result["id"] = "google-created"
        result["htmlLink"] = "https://calendar.google.test/event/google-created"
        return FakeRequest(result)

    def delete(self, **kwargs):
        self.deleted_id = kwargs["eventId"]
        return FakeRequest({})


class FakeGoogleService:
    def __init__(self):
        self.events_resource = FakeEventsResource()

    def events(self):
        return self.events_resource


@pytest.mark.asyncio
async def test_google_calendar_provider_maps_list_create_and_delete_operations():
    service = FakeGoogleService()
    provider = GoogleCalendarProvider(service=service)
    query = CalendarQueryFilter(
        start_time=datetime(2026, 8, 30, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 31, tzinfo=timezone.utc),
        query="UNITBV",
        max_results=4,
    )

    events = await provider.fetch_events(query)

    assert events[0].id == "google-1"
    assert events[0].creator_email == "coordonator@unitbv.ro"
    assert service.events_resource.list_kwargs["calendarId"] == provider.calendar_id
    assert service.events_resource.list_kwargs["q"] == "UNITBV"

    created = await provider.create_event(
        CalendarEventSchema(
            summary="Seminar",
            start_time=datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 30, 13, tzinfo=timezone.utc),
        )
    )
    assert created.id == "google-created"
    assert service.events_resource.insert_kwargs["body"]["start"]["dateTime"].startswith("2026-08-30T12:00:00")

    assert await provider.delete_event("google-created") is True
    assert service.events_resource.deleted_id == "google-created"
