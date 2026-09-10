"""Google Calendar v3 adapter with OAuth and service-account authentication."""

import asyncio
import json
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable, List, Optional
from zoneinfo import ZoneInfo

from src.app.core.config import settings
from src.app.core.exceptions import ConfigurationException, IntegrationException
from src.app.core.logging import logger
from src.app.core.retry import retry_async
from src.app.integrations.google_calendar.base import CalendarProvider
from src.app.schemas.calendar import CalendarEventSchema, CalendarQueryFilter


class GoogleCalendarProvider(CalendarProvider):
    """Execute calendar operations against the configured Google Calendar."""

    def __init__(self, service: Any = None, service_builder: Optional[Callable[[], Any]] = None):
        self.calendar_id = settings.GOOGLE_CALENDAR_ID
        self.timezone = ZoneInfo(settings.GOOGLE_CALENDAR_TIMEZONE)
        self._service = service
        self._service_builder = service_builder or self._build_service

    async def fetch_events(self, query_filter: CalendarQueryFilter) -> List[CalendarEventSchema]:
        async def operation() -> List[CalendarEventSchema]:
            service = await self._get_service()
            payload = await asyncio.to_thread(
                lambda: service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=self._as_rfc3339(query_filter.start_time),
                    timeMax=self._as_rfc3339(query_filter.end_time),
                    q=query_filter.query or None,
                    maxResults=query_filter.max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            return [self._to_schema(item) for item in payload.get("items", [])]

        try:
            return await retry_async(operation, operation_name="google_calendar_fetch")
        except Exception as exc:
            raise IntegrationException(f"Google Calendar fetch failed: {exc}") from exc

    async def create_event(self, event: CalendarEventSchema) -> CalendarEventSchema:
        async def operation() -> CalendarEventSchema:
            service = await self._get_service()
            created = await asyncio.to_thread(
                lambda: service.events()
                .insert(calendarId=self.calendar_id, body=self._to_google_event(event))
                .execute()
            )
            return self._to_schema(created)

        try:
            return await retry_async(operation, operation_name="google_calendar_create")
        except Exception as exc:
            raise IntegrationException(f"Google Calendar event creation failed: {exc}") from exc

    async def delete_event(self, event_id: str) -> bool:
        async def operation() -> bool:
            service = await self._get_service()
            await asyncio.to_thread(
                lambda: service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
            )
            return True

        try:
            return await retry_async(operation, operation_name="google_calendar_delete")
        except Exception as exc:
            raise IntegrationException(f"Google Calendar event deletion failed: {exc}") from exc

    async def _get_service(self) -> Any:
        if self._service is None:
            self._service = await asyncio.to_thread(self._service_builder)
        return self._service

    def _build_service(self) -> Any:
        """Create a Google API client from a refreshed OAuth token or service account."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ConfigurationException("Google Calendar dependencies are not installed") from exc

        scopes = settings.google_calendar_scopes
        auth_mode = settings.GOOGLE_AUTH_MODE.lower()

        if auth_mode == "service_account":
            service_account_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
            if not service_account_file or not Path(service_account_file).is_file():
                raise ConfigurationException("GOOGLE_SERVICE_ACCOUNT_FILE must point to a readable service-account JSON file")
            credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=scopes)
        elif auth_mode == "oauth":
            token_file = Path(settings.GOOGLE_TOKEN_FILE)
            if not token_file.is_file():
                raise ConfigurationException(
                    "Google OAuth token is missing. Run `python scripts/authorize_google_calendar.py` first."
                )
            credentials = Credentials.from_authorized_user_file(str(token_file), scopes)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                token_file.write_text(credentials.to_json(), encoding="utf-8")
            if not credentials.valid:
                raise ConfigurationException(
                    "Google OAuth token is invalid or cannot be refreshed. Run the authorization script again."
                )
        else:
            raise ConfigurationException("GOOGLE_AUTH_MODE must be either 'oauth' or 'service_account'")

        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def _to_google_event(self, event: CalendarEventSchema) -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": event.summary,
            "description": event.description,
            "location": event.location,
            "status": event.status,
        }
        if event.is_all_day:
            body["start"] = {"date": event.start_time.date().isoformat()}
            body["end"] = {"date": event.end_time.date().isoformat()}
        else:
            body["start"] = {"dateTime": self._as_rfc3339(event.start_time), "timeZone": str(self.timezone)}
            body["end"] = {"dateTime": self._as_rfc3339(event.end_time), "timeZone": str(self.timezone)}
        return {key: value for key, value in body.items() if value is not None}

    def _to_schema(self, item: dict[str, Any]) -> CalendarEventSchema:
        start, start_is_all_day = self._parse_google_time(item.get("start", {}))
        end, end_is_all_day = self._parse_google_time(item.get("end", {}))
        return CalendarEventSchema(
            id=item.get("id"),
            summary=item.get("summary") or "(fără titlu)",
            description=item.get("description"),
            location=item.get("location"),
            start_time=start,
            end_time=end,
            is_all_day=start_is_all_day or end_is_all_day,
            status=item.get("status", "confirmed"),
            creator_email=(item.get("creator") or {}).get("email"),
            html_link=item.get("htmlLink"),
        )

    def _parse_google_time(self, value: dict[str, str]) -> tuple[datetime, bool]:
        if value.get("dateTime"):
            parsed = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=self.timezone), False
        if value.get("date"):
            parsed = datetime.combine(datetime.fromisoformat(value["date"]).date(), time.min)
            return parsed.replace(tzinfo=self.timezone), True
        raise IntegrationException("Google Calendar returned an event without a start or end time")

    def _as_rfc3339(self, value: datetime) -> str:
        localized = value if value.tzinfo else value.replace(tzinfo=self.timezone)
        return localized.isoformat()
