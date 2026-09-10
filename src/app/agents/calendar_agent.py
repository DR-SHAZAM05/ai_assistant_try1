from typing import Dict, Any, Optional
from src.app.services.calendar_service import CalendarService
from src.app.llm.factory import get_llm_provider
from src.app.core.logging import logger


class CalendarAgent:
    """
    Specialized Calendar Agent. Parses natural language date ranges,
    formats calendar responses, and schedules new events.
    """

    def __init__(
        self,
        calendar_service: Optional[CalendarService] = None,
        llm_provider=None,
    ):
        self.calendar_service = calendar_service or CalendarService()
        self.llm = llm_provider or get_llm_provider()

    async def handle_calendar_query(
        self,
        user_prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Processes natural language calendar queries (e.g., 'Ce am mâine?', 'Am ceva între 12 și 15?',
        'Când este următorul eveniment?', 'Și după al doilea?').
        """
        import re
        from datetime import datetime, timezone
        logger.info("CalendarAgent processing query (query_length=%s).", len(user_prompt))
        prompt_lower = user_prompt.strip().lower()

        # 1. Check conversation history follow-up (Section 18.1: "Și după al doilea?")
        follow_up_triggers = ["și după al doilea", "si dupa al doilea", "după al doilea", "dupa al doilea", "după al 2-lea", "dupa al 2-lea", "după a doua", "dupa a doua"]
        if any(trig in prompt_lower for trig in follow_up_triggers) and history:
            for prev_msg in reversed(history):
                if prev_msg.get("role") == "assistant" or prev_msg.get("sender_role") == "assistant":
                    content = prev_msg.get("content", "")
                    event_matches = re.findall(r'(?:•\s*)?(\d{1,2}:\d{2})\s*(?:–|-|\ba\b)\s*(\d{1,2}:\d{2})?:?\s*([^•\n]+)?', content)
                    if len(event_matches) >= 2:
                        second_evt_end = event_matches[1][1] or event_matches[1][0]
                        second_evt_title = event_matches[1][2].strip() if event_matches[1][2] else "al doilea eveniment"
                        if len(event_matches) > 2:
                            third_evt_start = event_matches[2][0]
                            third_evt_title = event_matches[2][2].strip() if event_matches[2][2] else "următorul eveniment"
                            ans_text = f"📅 După al doilea eveniment ({second_evt_title}, ora {second_evt_end}), ai programat **{third_evt_title}** la ora **{third_evt_start}**."
                        else:
                            ans_text = f"📅 După al doilea eveniment (ora {second_evt_end}) nu mai ai nimic programat în calendar pentru acea zi."
                        return {
                            "text": ans_text,
                            "count": len(event_matches),
                            "label": "follow_up"
                        }

        try:
            data = await self.calendar_service.get_events(user_prompt)
        except Exception as exc:
            logger.warning("Calendar service unavailable (%s): %s", type(exc).__name__, exc)
            err_str = str(exc).lower()
            if "not been used in project" in err_str or "accessnotconfigured" in err_str or "disabled" in err_str:
                msg = (
                    "📅 **Google Calendar API nu este activat în Google Cloud Console.**\n\n"
                    "Activează API-ul dând click pe linkul direct din proiectul tău:\n"
                    "👉 https://console.developers.google.com/apis/api/calendar-json.googleapis.com/overview?project=717531530848\n\n"
                    "Apasă butonul albastru **ENABLE (Activează)**, iar apoi reîntreabă-mă despre programul tău!"
                )
            elif "not found" in err_str or "does not have access" in err_str or "404" in err_str:
                msg = (
                    "📅 **Calendarul tău nu a fost încă partajat cu asistentul AI.**\n\n"
                    "Pentru a-mi permite să-ți citesc orarul:\n"
                    "1. Deschide Google Calendar în browser (https://calendar.google.com)\n"
                    "2. În stânga, dă click pe cele 3 puncte de lângă calendarul tău -> **Settings and sharing**\n"
                    "3. La secțiunea **Share with specific people**, apasă **Add people** și adaugă:\n"
                    "`proiect-practica-2026@practica-proiect.iam.gserviceaccount.com`\n"
                    "4. Setează permisiunea: *'See all event details'*."
                )
            else:
                msg = (
                    f"📅 **Google Calendar nu este disponibil momentan.**\n\n"
                    f"Detalii: `{exc}`"
                )
            return {
                "text": msg,
                "count": 0,
                "label": "calendar"
            }
        
        events = data["events"]
        label = data["label"]

        # Check next event query
        if data.get("is_next_event"):
            now = datetime.now(timezone.utc)
            future_events = [e for e in events if (getattr(e.start_time, "tzinfo", None) and e.start_time >= now) or (not getattr(e.start_time, "tzinfo", None) and e.start_time >= now.replace(tzinfo=None))]
            if not future_events:
                return {
                    "text": "📅 Nu ai niciun eveniment viitor programat în calendar pentru următoarele două săptămâni.",
                    "count": 0,
                    "label": "următorul eveniment"
                }
            next_evt = future_events[0]
            start_str = next_evt.start_time.strftime("%d.%m.%Y la ora %H:%M")
            start_tz = next_evt.start_time if getattr(next_evt.start_time, "tzinfo", None) else next_evt.start_time.replace(tzinfo=timezone.utc)
            delta_mins = int((start_tz - now).total_seconds() / 60)
            if delta_mins < 60:
                time_left_str = f"în aproximativ {max(delta_mins, 1)} minute"
            elif delta_mins < 1440:
                time_left_str = f"peste {delta_mins // 60} ore"
            else:
                time_left_str = f"peste {delta_mins // 1440} zile"

            loc_str = f"\n📍 Locație: `{next_evt.location}`" if next_evt.location else ""
            desc_str = f"\n_{next_evt.description}_" if next_evt.description else ""
            return {
                "text": (
                    f"⏰ **Următorul tău eveniment din calendar:**\n\n"
                    f"• **{next_evt.summary}**\n"
                    f"• Dată și oră: **{start_str}** ({time_left_str})"
                    f"{loc_str}{desc_str}"
                ),
                "count": 1,
                "label": "următorul eveniment"
            }

        # Check hourly interval query ("Am ceva între 12 și 15?")
        if data.get("is_hourly_interval"):
            int_start = data["start_time"]
            int_end = data["end_time"]
            overlapping = [
                e for e in events
                if (e.start_time < int_end and e.end_time > int_start)
            ]
            if not overlapping:
                return {
                    "text": f"🟢 **Ești complet liber în {label}!** Nu ai niciun eveniment programat în acest interval orar.",
                    "count": 0,
                    "label": label
                }
            lines = [f"🟡 **În {label} ai {len(overlapping)} eveniment(e) programat(e):**\n"]
            for evt in overlapping:
                s_str = evt.start_time.strftime("%H:%M")
                e_str = evt.end_time.strftime("%H:%M")
                loc = f" 📍 `{evt.location}`" if evt.location else ""
                lines.append(f"• **{s_str} – {e_str}**: {evt.summary}{loc}")
            return {
                "text": "\n".join(lines),
                "count": len(overlapping),
                "label": label
            }

        if not events:
            return {
                "text": f"📅 **Nu ai evenimente programate pentru {label}.**",
                "count": 0,
                "label": label
            }

        lines = [f"📅 **Programul tău pentru {label}**:\n"]
        for evt in events:
            start_str = evt.start_time.strftime("%H:%M")
            end_str = evt.end_time.strftime("%H:%M")
            loc_str = f" 📍 `{evt.location}`" if evt.location else ""
            lines.append(f"• **{start_str} – {end_str}**: {evt.summary}{loc_str}")
            if evt.description:
                lines.append(f"   _{evt.description}_")

        # Check for conflicts
        conflicts = await self.calendar_service.detect_conflicts(events)
        if conflicts:
            lines.append("\n⚠️ **Suprapuneri detectate în calendar!**")

        return {
            "text": "\n".join(lines),
            "count": len(events),
            "label": label,
        }

    async def handle_create_event_query(
        self,
        user_prompt: str,
    ) -> Dict[str, Any]:
        """Parses and creates a calendar event from natural language."""
        import json
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        logger.info("CalendarAgent creating event from prompt (query_length=%s).", len(user_prompt))

        try:
            tz = ZoneInfo("Europe/Bucharest")
        except Exception:
            tz = timezone.utc
        now = datetime.now(tz)

        system_prompt = (
            f"Ești un asistent universitar care extrage detaliile unui nou eveniment de calendar din mesajul utilizatorului.\n"
            f"Data și ora curentă de referință (Europe/Bucharest): {now.strftime('%Y-%m-%d %H:%M')}.\n"
            f"Răspunde EXCLUSIV cu un bloc JSON valid (fără alte explicații sau text) cu cheile:\n"
            f'{{\n'
            f'  "summary": "Titlul clar al evenimentului",\n'
            f'  "start_time": "YYYY-MM-DDTHH:MM:SS",\n'
            f'  "end_time": "YYYY-MM-DDTHH:MM:SS",\n'
            f'  "location": "Locație sau null",\n'
            f'  "description": "Descriere sau null"\n'
            f'}}\n'
            f"Dacă utilizatorul nu menționează ora de sfârșit, seteaz-o la 1 oră după start_time."
        )

        try:
            llm_response = await self.llm.generate_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
            )
            clean_json = llm_response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            event_data = json.loads(clean_json)
            summary = event_data.get("summary") or "Eveniment nou"
            start_dt = datetime.fromisoformat(event_data["start_time"])
            end_dt = datetime.fromisoformat(event_data["end_time"])
            location = event_data.get("location")
            description = event_data.get("description")

            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=tz)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=tz)

            created_event = await self.calendar_service.create_event(
                summary=summary,
                start_time=start_dt,
                end_time=end_dt,
                description=description,
                location=location,
            )

            start_fmt = start_dt.strftime("%d.%m.%Y de la %H:%M")
            end_fmt = end_dt.strftime("%H:%M")
            loc_fmt = f"\n📍 **Locație**: `{location}`" if location else ""
            desc_fmt = f"\n📝 **Descriere**: _{description}_" if description else ""

            ans = (
                f"✅ **Eveniment programat cu succes în Google Calendar!**\n\n"
                f"📌 **Titlu**: **{created_event.summary}**\n"
                f"🕒 **Când**: {start_fmt} până la {end_fmt}"
                f"{loc_fmt}{desc_fmt}\n\n"
                f"💡 *Evenimentul este sincronizat direct pe contul tău Google.*"
            )
            return {
                "text": ans,
                "event_id": created_event.id,
                "status": "success",
            }
        except Exception as exc:
            logger.error("Failed to create calendar event from prompt: %s", exc)
            return {
                "text": f"⚠️ Nu am putut programa evenimentul în calendar.\nDetalii: `{exc}`",
                "status": "error",
            }

