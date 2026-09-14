"""Calendar Agent - Handles calendar operations with Human-in-the-Loop."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import json
import re

from src.app.core.config import settings
from src.app.core.logging import logger
from src.app.llm.factory import get_llm_provider
from src.app.services.calendar_service import CalendarService


_DEFAULT = object()


class CalendarAgent:
    """
    Calendar Agent: Parses natural language date ranges, formats calendar responses,
    and manages event creation/update/deletion with Human-in-the-Loop approval.
    """

    def __init__(
        self,
        calendar_service: Any = _DEFAULT,
        llm_provider=None,
    ):
        if calendar_service is _DEFAULT:
            try:
                from src.app.integrations.google_calendar.factory import get_calendar_provider
                from src.app.database.session import AsyncSessionLocal
                provider = get_calendar_provider()
                if provider is not None:
                    self.calendar_service = CalendarService(
                        provider=provider,
                        session_factory=AsyncSessionLocal,
                    )
                else:
                    self.calendar_service = None
            except Exception as exc:
                logger.warning("Default CalendarService initialization note: %s: %s", type(exc).__name__, exc)
                self.calendar_service = None
        else:
            self.calendar_service = calendar_service

        self.llm = llm_provider or get_llm_provider()
        self.tz = ZoneInfo(settings.GOOGLE_CALENDAR_TIMEZONE)
        # Fallback read-only provider for handle_calendar_query when no CalendarService is injected
        self._read_provider = self._build_read_provider()

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        """Extract and parse JSON from LLM response text, tolerating markdown and surrounding prose."""
        cleaned = text.strip()
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return json.loads(cleaned)

    def _build_read_provider(self):
        """Build a read-only CalendarProvider for fetch_events queries without a DB session."""
        try:
            provider_name = settings.CALENDAR_PROVIDER.lower()
            if provider_name == "mock" or settings.mocks_allowed:
                from src.app.integrations.google_calendar.mock_provider import MockCalendarProvider
                return MockCalendarProvider()
            # In production attempt a real provider; failure is non-fatal here
            return None
        except Exception:
            return None

    async def handle_calendar_query(
        self,
        user_id: str,
        user_prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Fetch calendar events (read-only query)."""
        try:
            now = datetime.now(self.tz)
            start_date, end_date, label = self._parse_date_range(user_prompt, now)

            # Prefer full CalendarService (has user_id, audit, etc.)
            if self.calendar_service:
                events = await self.calendar_service.fetch_events(
                    user_id=user_id,
                    start_date=start_date,
                    end_date=end_date,
                    query=None,
                )
            elif self._read_provider:
                from src.app.schemas.calendar import CalendarQueryFilter
                q = CalendarQueryFilter(start_time=start_date, end_time=end_date, max_results=50)
                events = await self._read_provider.fetch_events(q)
            else:
                return {"text": "Calendar service not configured.", "status": "error", "count": 0}

            if not events:
                return {
                    "text": f"\U0001f4c5 Nu ai evenimente programate pentru {label}.",
                    "count": 0,
                    "label": label,
                }

            lines = [f"\U0001f4c5 **Programul t\u0103u pentru {label}**:\n"]
            for evt in events:
                start_str = evt.start_time.strftime("%H:%M")
                end_str = evt.end_time.strftime("%H:%M")
                loc_str = f" \U0001f4cd {evt.location}" if evt.location else ""
                lines.append(f"\u2022 {start_str} \u2013 {end_str}: {evt.summary}{loc_str}")
                if evt.description:
                    lines.append(f"   {evt.description}")

            return {
                "text": "\n".join(lines),
                "count": len(events),
                "label": label,
            }

        except Exception as exc:
            logger.error(f"[CalendarAgent] calendar query failed: {exc}")
            return {
                "text": f"\u26a0\ufe0f Nu am putut citi calendarul. Detalii: {exc}",
                "status": "error",
            }

    async def handle_create_event_query(
        self,
        user_id: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        """
        Parse and request calendar event creation (HiTL - creates pending action).
        Returns (action_id, preview_text).
        """
        if not self.calendar_service:
            return {
                "text": "Calendar service not configured.",
                "status": "error",
            }

        try:
            now = datetime.now(self.tz)

            # Use LLM to parse event details
            system_prompt = (
                f"Ești asistent universitar. Extrage detaliile unui eveniment de calendar.\n"
                f"Data curentă: {now.strftime('%Y-%m-%d %H:%M')} (Europe/Bucharest).\n"
                f"Răspunde EXCLUSIV cu JSON valid (fără text suplimentar):\n"
                f'{{\n'
                f'  "summary": "Titlul evenimentului",\n'
                f'  "start_time": "YYYY-MM-DDTHH:MM:SS",\n'
                f'  "end_time": "YYYY-MM-DDTHH:MM:SS",\n'
                f'  "location": "Locație sau null",\n'
                f'  "description": "Descriere sau null"\n'
                f'}}\n'
                f"Dacă ora de sfârșit nu e menționată, seteaz-o la 1 oră după start."
            )

            try:
                llm_response = await self.llm.generate_completion(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=0.1,
                )
            except TypeError:
                llm_response = await self.llm.generate_completion(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.1,
                )

            raw_text = (
                llm_response.get("content", "")
                if isinstance(llm_response, dict)
                else str(llm_response)
            )
            event_data = self._extract_json(raw_text)

            summary = event_data.get("summary") or "Eveniment nou"
            start_raw = event_data.get("start_time")
            if not start_raw:
                raise ValueError("Nu am putut identifica data și ora de început a evenimentului.")
            start_dt = datetime.fromisoformat(start_raw)
            end_raw = event_data.get("end_time")
            if end_raw:
                end_dt = datetime.fromisoformat(end_raw)
            else:
                end_dt = start_dt + timedelta(hours=1)
            location = event_data.get("location")
            description = event_data.get("description")

            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=self.tz)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=self.tz)

            # Request (HiTL)
            action_id, preview = await self.calendar_service.request_create(
                user_id=user_id,
                summary=summary,
                description=description,
                location=location,
                start_time=start_dt,
                end_time=end_dt,
            )

            return {
                "status": "pending",
                "action_id": action_id,
                "preview": preview,
            }

        except Exception as exc:
            logger.error(f"[CalendarAgent] create_event_query failed: {exc}")
            return {
                "text": f"⚠️ Nu am putut procesa cererea. Detalii: {exc}",
                "status": "error",
            }

    async def handle_update_event_query(
        self,
        user_id: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        """
        Request calendar event update (HiTL - creates pending action).
        Ambiguity handling: requires clarification if 0 or >1 results.
        """
        if not self.calendar_service:
            return {
                "text": "Calendar service not configured.",
                "status": "error",
            }

        try:
            # Parse update details from prompt
            # Example: "Modifică ședința de proiect la 15:00"
            system_prompt = (
                f"Ești asistent universitar. Din mesajul utilizatorului, extrage:\n"
                f"1. Event query string (keyword pentru a găsi evenimentul)\n"
                f"2. Updates dict cu câmpurile de modificat\n"
                f"Răspunde EXCLUSIV cu JSON valid:\n"
                f'{{\n'
                f'  "event_query": "Cuvântul cheie pentru a găsi evenimentul",\n'
                f'  "updates": {{\n'
                f'    "summary": "Titlu nou sau null",\n'
                f'    "start_time": "YYYY-MM-DDTHH:MM:SS sau null",\n'
                f'    "location": "Locație nouă sau null"\n'
                f'  }}\n'
                f'}}\n'
            )

            try:
                llm_response = await self.llm.generate_completion(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=0.1,
                )
            except TypeError:
                llm_response = await self.llm.generate_completion(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.1,
                )

            raw_text = (
                llm_response.get("content", "")
                if isinstance(llm_response, dict)
                else str(llm_response)
            )
            parsed = self._extract_json(raw_text)

            event_query = parsed.get("event_query", "").strip()
            updates_raw = parsed.get("updates", {})
            updates = {k: v for k, v in updates_raw.items() if v is not None}

            if not event_query:
                return {
                    "text": "Te rog specifică care eveniment dorești să modifici.",
                    "status": "error",
                }

            if not updates:
                return {
                    "text": "Te rog specifică ce dorești să modifici în eveniment.",
                    "status": "error",
                }

            # Request (HiTL) - ambiguity handling inside
            action_id, preview = await self.calendar_service.request_update(
                user_id=user_id,
                event_query=event_query,
                updates=updates,
            )

            return {
                "status": "pending",
                "action_id": action_id,
                "preview": preview,
            }

        except ValueError as exc:
            # Ambiguity or not found
            return {
                "text": str(exc),
                "status": "clarification_needed",
            }
        except Exception as exc:
            logger.error(f"[CalendarAgent] update_event_query failed: {exc}")
            return {
                "text": f"⚠️ Nu am putut procesa cererea. Detalii: {exc}",
                "status": "error",
            }

    async def handle_delete_event_query(
        self,
        user_id: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        """
        Request calendar event deletion (HiTL - creates pending action).
        Ambiguity handling: requires clarification if 0 or >1 results.
        """
        if not self.calendar_service:
            return {
                "text": "Calendar service not configured.",
                "status": "error",
            }

        try:
            # Extract event query keyword
            system_prompt = (
                f"Ești asistent universitar. Din mesajul utilizatorului, extrage cuvântul cheie "
                f"pentru a identifica evenimentul de șters.\n"
                f"Răspunde EXCLUSIV cu JSON valid:\n"
                f'{{\n'
                f'  "event_query": "Cuvântul cheie pentru a găsi evenimentul"\n'
                f'}}\n'
            )

            try:
                llm_response = await self.llm.generate_completion(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=0.1,
                )
            except TypeError:
                llm_response = await self.llm.generate_completion(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.1,
                )

            raw_text = (
                llm_response.get("content", "")
                if isinstance(llm_response, dict)
                else str(llm_response)
            )
            parsed = self._extract_json(raw_text)

            event_query = parsed.get("event_query", "").strip()
            if not event_query:
                return {
                    "text": "Te rog specifică care eveniment dorești să ștergi.",
                    "status": "error",
                }

            # Request (HiTL) - ambiguity handling inside
            action_id, preview = await self.calendar_service.request_delete(
                user_id=user_id,
                event_query=event_query,
            )

            return {
                "status": "pending",
                "action_id": action_id,
                "preview": preview,
            }

        except ValueError as exc:
            # Ambiguity or not found
            return {
                "text": str(exc),
                "status": "clarification_needed",
            }
        except Exception as exc:
            logger.error(f"[CalendarAgent] delete_event_query failed: {exc}")
            return {
                "text": f"⚠️ Nu am putut procesa cererea. Detalii: {exc}",
                "status": "error",
            }

    async def handle_confirm_action(
        self,
        user_id: str,
        action_id: str,
    ) -> Dict[str, Any]:
        """Confirm a pending calendar action."""
        if not self.calendar_service:
            return {
                "text": "Calendar service not configured.",
                "status": "error",
            }

        try:
            result = await self.calendar_service.confirm_action(user_id, action_id)
            return {
                "text": f"✅ {result}",
                "status": "success",
            }
        except PermissionError as exc:
            return {
                "text": str(exc),
                "status": "permission_error",
            }
        except ValueError as exc:
            return {
                "text": str(exc),
                "status": "error",
            }
        except Exception as exc:
            logger.error(f"[CalendarAgent] confirm_action failed: {exc}")
            return {
                "text": f"⚠️ Eroare: {exc}",
                "status": "error",
            }

    async def handle_cancel_action(
        self,
        user_id: str,
        action_id: str,
    ) -> Dict[str, Any]:
        """Cancel a pending calendar action."""
        if not self.calendar_service:
            return {
                "text": "Calendar service not configured.",
                "status": "error",
            }

        try:
            result = await self.calendar_service.cancel_action(user_id, action_id)
            return {
                "text": f"✅ {result}",
                "status": "success",
            }
        except PermissionError as exc:
            return {
                "text": str(exc),
                "status": "permission_error",
            }
        except ValueError as exc:
            return {
                "text": str(exc),
                "status": "error",
            }
        except Exception as exc:
            logger.error(f"[CalendarAgent] cancel_action failed: {exc}")
            return {
                "text": f"⚠️ Eroare: {exc}",
                "status": "error",
            }

    def _parse_date_range(
        self,
        user_prompt: str,
        now: datetime,
    ) -> tuple[datetime, datetime, str]:
        """Parse relative date references (azi, mâine, săptămâna viitoare, etc.)."""
        prompt_lower = user_prompt.lower()

        if any(w in prompt_lower for w in ["azi", "azi"]):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            return start, end, "azi"

        if any(w in prompt_lower for w in ["mâine", "maine", "mâine"]):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            end = start + timedelta(days=1)
            return start, end, "mâine"

        if any(w in prompt_lower for w in ["poimâine", "poimaine"]):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)
            end = start + timedelta(days=1)
            return start, end, "poimâine"

        if any(w in prompt_lower for w in ["săptămâna viitoare", "saptamana viitoare", "săptămâna aceasta", "saptamana aceasta"]):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
            return start, end, "săptămâna viitoare"

        # Default: next 30 days
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=30)
        return start, end, "următoarele 30 de zile"
