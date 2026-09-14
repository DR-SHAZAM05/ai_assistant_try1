"""CalendarService - Human-in-the-Loop calendar management."""

import re
from datetime import datetime, timedelta
from typing import Optional, Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.integrations.google_calendar.base import CalendarProvider
from src.app.schemas.calendar import CalendarEventSchema, CalendarQueryFilter
from src.app.services.pending_calendar_action_store import PendingCalendarActionStore
from src.app.services.audit_service import AuditService


class CalendarService:
    """
    Calendar management with human-in-the-loop approval.
    
    Flow:
    1. Request → Pending Action
    2. Preview shown to user
    3. User confirms or cancels
    4. If confirmed → Provider executes
    5. Audit logged
    """

    def __init__(
        self,
        provider: CalendarProvider,
        session: AsyncSession,
        audit_service: AuditService,
    ):
        self.provider = provider
        self.session = session
        self.store = PendingCalendarActionStore(session)
        self.audit_service = audit_service
        self.timezone = ZoneInfo(settings.GOOGLE_CALENDAR_TIMEZONE)

    async def fetch_events(
        self,
        user_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        query: Optional[str] = None,
    ) -> list[CalendarEventSchema]:
        """Fetch calendar events (no approval needed)."""
        if not start_date:
            start_date = datetime.now(self.timezone)
        if not end_date:
            end_date = start_date + timedelta(days=30)

        query_filter = CalendarQueryFilter(
            start_time=start_date,
            end_time=end_date,
            query=query,
            max_results=50,
        )

        try:
            events = await self.provider.fetch_events(query_filter)
            logger.info(f"[CalendarService] User {user_id} fetched {len(events)} events")
            return events
        except Exception as exc:
            logger.error(f"[CalendarService] fetch_events failed: {exc}")
            raise

    async def request_create(
        self,
        user_id: str,
        summary: str,
        description: Optional[str] = None,
        location: Optional[str] = None,
        start_time: datetime = None,
        end_time: datetime = None,
    ) -> tuple[str, str]:
        """
        Request to create a calendar event.
        Returns (action_id, preview_text).
        Provider is NOT called.
        """
        if not start_time or not end_time:
            raise ValueError("start_time and end_time are required")

        event = CalendarEventSchema(
            id=None,
            summary=summary,
            description=description,
            location=location,
            start_time=start_time,
            end_time=end_time,
            status="confirmed",
        )

        payload = {
            "action_type": "create",
            "event": {
                "summary": event.summary,
                "description": event.description,
                "location": event.location,
                "start_time": event.start_time.isoformat(),
                "end_time": event.end_time.isoformat(),
                "is_all_day": event.is_all_day,
            },
        }

        preview = self._build_preview(
            "Eveniment propus",
            event.summary,
            event.description,
            event.location,
            event.start_time,
            event.end_time,
        )

        action_id = await self.store.save(
            owner_id=user_id,
            action_type="create",
            payload=payload,
            preview_text=preview,
        )

        logger.info(f"[CalendarService] User {user_id} requested CREATE event: {summary}")
        await self.audit_service.log_event(
            user_id=user_id,
            user_request=f"Crează eveniment: {summary}",
            selected_tool="calendar_create_request",
            status="pending_approval",
            external_operation="calendar.create.pending",
        )

        return action_id, preview

    async def request_update(
        self,
        user_id: str,
        event_query: str,
        updates: dict[str, Any],
    ) -> tuple[str, str]:
        """
        Request to update a calendar event.
        
        Ambiguity rules:
        - 0 matches → raise error
        - 1 match → create pending action
        - >1 matches → raise error (require clarification)
        """
        events = await self.fetch_events(user_id, query=event_query)

        if len(events) == 0:
            raise ValueError(f"Nu am găsit niciun eveniment cu: {event_query}")

        if len(events) > 1:
            summaries = "\n  - ".join([e.summary for e in events[:5]])
            raise ValueError(
                f"Sunt {len(events)} evenimente care se potrivesc.\n"
                f"Te rog clarifică care anume:\n  - {summaries}"
            )

        event = events[0]
        event_id = event.id

        payload = {
            "action_type": "update",
            "event_id": event_id,
            "updates": updates,
        }

        preview_lines = [
            "Eveniment de modificat",
            "",
            f"Titlu: {event.summary}",
            f"Data: {event.start_time.strftime('%d.%m.%Y')}",
            f"Ora: {event.start_time.strftime('%H:%M')} - {event.end_time.strftime('%H:%M')}",
        ]

        if updates.get("summary"):
            preview_lines.append(f"⇒ Titlu nou: {updates['summary']}")
        if updates.get("start_time"):
            start = updates["start_time"]
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            preview_lines.append(f"⇒ Data nouă: {start.strftime('%d.%m.%Y')}")

        if event.location:
            preview_lines.append(f"Locație: {event.location}")
        if event.description:
            preview_lines.append(f"Descriere: {event.description}")

        preview_lines.extend(["", "Dorești să aplic această modificare?"])
        preview = "\n".join(preview_lines)

        action_id = await self.store.save(
            owner_id=user_id,
            action_type="update",
            payload=payload,
            preview_text=preview,
        )

        logger.info(f"[CalendarService] User {user_id} requested UPDATE event: {event_id}")
        await self.audit_service.log_event(
            user_id=user_id,
            user_request=f"Modifică eveniment: {event.summary}",
            selected_tool="calendar_update_request",
            status="pending_approval",
            external_operation="calendar.update.pending",
        )

        return action_id, preview

    async def request_delete(
        self,
        user_id: str,
        event_query: str,
    ) -> tuple[str, str]:
        """
        Request to delete a calendar event.
        
        Ambiguity rules:
        - 0 matches → raise error
        - 1 match → create pending action
        - >1 matches → raise error (require clarification)
        """
        events = await self.fetch_events(user_id, query=event_query)

        if len(events) == 0:
            raise ValueError(f"Nu am găsit niciun eveniment cu: {event_query}")

        if len(events) > 1:
            summaries = "\n  - ".join([e.summary for e in events[:5]])
            raise ValueError(
                f"Sunt {len(events)} evenimente care se potrivesc.\n"
                f"Te rog clarifică care anume:\n  - {summaries}"
            )

        event = events[0]
        event_id = event.id

        payload = {
            "action_type": "delete",
            "event_id": event_id,
        }

        preview = self._build_preview(
            "Eveniment de șters",
            event.summary,
            event.description,
            event.location,
            event.start_time,
            event.end_time,
        )
        preview += "\n\nDorești să ștergi acest eveniment?"

        action_id = await self.store.save(
            owner_id=user_id,
            action_type="delete",
            payload=payload,
            preview_text=preview,
        )

        logger.info(f"[CalendarService] User {user_id} requested DELETE event: {event_id}")
        await self.audit_service.log_event(
            user_id=user_id,
            user_request=f"Șterge eveniment: {event.summary}",
            selected_tool="calendar_delete_request",
            status="pending_approval",
            external_operation="calendar.delete.pending",
        )

        return action_id, preview

    async def confirm_action(
        self,
        user_id: str,
        action_id: str,
    ) -> str:
        """
        Confirm and execute a pending calendar action.
        
        Checks:
        1. Action exists
        2. Ownership (user_id matches)
        3. Status (not already processed)
        4. TTL (not expired)
        5. Execute provider
        6. Audit
        """
        action = await self.store.get(action_id)
        if not action:
            raise ValueError("Acțiunea nu există.")

        if action.owner_id != user_id:
            raise PermissionError(
                "Nu ai permisiunea să confirmi/anulezi această acțiune – aparține altui utilizator."
            )

        if action.status != "pending_approval":
            raise ValueError("Acțiunea a fost deja procesată.")

        if await self.store.is_expired(action_id):
            await self.store.decide(action_id, "expired")
            raise ValueError("Acțiunea a expirat. Te rog să o inițiezi din nou.")

        try:
            if action.action_type == "create":
                event_data = action.payload["event"]
                event = CalendarEventSchema(
                    id=None,
                    summary=event_data["summary"],
                    description=event_data["description"],
                    location=event_data["location"],
                    start_time=datetime.fromisoformat(event_data["start_time"]),
                    end_time=datetime.fromisoformat(event_data["end_time"]),
                    is_all_day=event_data.get("is_all_day", False),
                    status="confirmed",
                )
                result = await self.provider.create_event(event)
                result_summary = f"Eveniment creat: {result.summary}"

            elif action.action_type == "update":
                event_id = action.payload["event_id"]
                updates = action.payload["updates"]
                result = await self.provider.update_event(event_id, updates)
                result_summary = f"Eveniment modificat: {updates.get('summary', 'N/A')}"

            elif action.action_type == "delete":
                event_id = action.payload["event_id"]
                result = await self.provider.delete_event(event_id)
                result_summary = f"Eveniment șters"

            else:
                raise ValueError(f"Tip acțiune necunoscut: {action.action_type}")

            await self.store.decide(action_id, "approved")

            await self.audit_service.log_event(
                user_id=user_id,
                user_request=f"{action.action_type.upper()}: Confirmat",
                selected_tool="calendar_confirm_action",
                status="success",
                external_operation=f"calendar.{action.action_type}.confirmed",
            )

            logger.info(f"[CalendarService] User {user_id} confirmed {action.action_type}: {action_id}")
            return result_summary

        except Exception as exc:
            await self.audit_service.log_event(
                user_id=user_id,
                user_request=f"{action.action_type.upper()}: Eșec",
                selected_tool="calendar_confirm_action",
                status="error",
                external_operation=f"calendar.{action.action_type}.failed",
            )
            logger.error(f"[CalendarService] confirm_action failed: {exc}")
            raise

    async def cancel_action(
        self,
        user_id: str,
        action_id: str,
    ) -> str:
        """
        Cancel a pending calendar action.
        
        Checks:
        1. Action exists
        2. Ownership
        3. Status
        4. TTL
        5. Does NOT execute provider
        6. Audit
        """
        action = await self.store.get(action_id)
        if not action:
            raise ValueError("Acțiunea nu există.")

        if action.owner_id != user_id:
            raise PermissionError(
                "Nu ai permisiunea să confirmi/anulezi această acțiune – aparține altui utilizator."
            )

        if action.status != "pending_approval":
            raise ValueError("Acțiunea a fost deja procesată.")

        if await self.store.is_expired(action_id):
            await self.store.decide(action_id, "expired")
            raise ValueError("Acțiunea a expirat.")

        await self.store.decide(action_id, "rejected")

        await self.audit_service.log_event(
            user_id=user_id,
            user_request=f"{action.action_type.upper()}: Anulat",
            selected_tool="calendar_cancel_action",
            status="cancelled",
            external_operation=f"calendar.{action.action_type}.rejected",
        )

        logger.info(f"[CalendarService] User {user_id} cancelled {action.action_type}: {action_id}")
        return f"Acțiunea a fost anulată ({action.action_type})."

    def _build_preview(
        self,
        title: str,
        summary: str,
        description: Optional[str],
        location: Optional[str],
        start_time: datetime,
        end_time: datetime,
    ) -> str:
        """Build a plain-text preview (no emoji, Romanian)."""
        lines = [
            title,
            "",
            f"Titlu: {summary}",
            f"Data: {start_time.strftime('%d.%m.%Y')}",
            f"Ora: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}",
        ]
        if location:
            lines.append(f"Locație: {location}")
        if description:
            lines.append(f"Descriere: {description}")
        lines.append("")
        lines.append("Dorești să aplic această modificare?")
        return "\n".join(lines)

    def _sanitize_audit_payload(self, payload: dict) -> dict:
        """
        Sanitize payload for audit: redact emails, phone numbers, tokens, secrets.
        Recursively process nested structures.
        """
        import copy
        result = copy.deepcopy(payload)

        def redact_recursively(obj: Any) -> Any:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    key_lower = key.lower()
                    if any(term in key_lower for term in ["token", "secret", "password", "pwd"]):
                        obj[key] = "<redacted>"
                    elif isinstance(value, (dict, list)):
                        obj[key] = redact_recursively(value)
                    elif isinstance(value, str):
                        if re.search(r"\S+@\S+", value):
                            obj[key] = "<redacted>"
                        elif re.search(r"\+?\d{7,}", value):
                            obj[key] = "<redacted>"
                return obj
            elif isinstance(obj, list):
                return [redact_recursively(item) for item in obj]
            return obj

        return redact_recursively(result)
