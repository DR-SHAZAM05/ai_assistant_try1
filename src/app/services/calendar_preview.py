"""Calendar preview formatting helpers.

All functions return a plain Romanian markdown string (no emojis) describing the
operation that will be performed. They are used by the HiTL flow to build the
preview shown to the user before they confirm the action.
"""

from src.app.schemas.calendar import CalendarEventSchema
from typing import Dict, Any


def format_create_preview(event: CalendarEventSchema) -> str:
    """Return a preview string for a CREATE request.

    Example output:
        Creare eveniment:
        Titlu: Întâlnire de proiect
        Data: 2024-10-05 10:00 – 2024-10-05 11:00
        Locație: Sala 101
        Descriere: Discuție tehnică
    """
    start = event.start_time.strftime("%Y-%m-%d %H:%M")
    end = event.end_time.strftime("%Y-%m-%d %H:%M")
    lines = ["Creare eveniment:", f"Titlu: {event.summary}"]
    lines.append(f"Data: {start} – {end}")
    if event.location:
        lines.append(f"Locație: {event.location}")
    if event.description:
        lines.append(f"Descriere: {event.description}")
    return "\n".join(lines)


def format_update_preview(original: CalendarEventSchema, updates: Dict[str, Any]) -> str:
    """Return a preview string for an UPDATE request.

    Shows the fields that will be changed and their new values.
    """
    lines = ["Actualizare eveniment:", f"Titlu: {original.summary}"]
    for key, value in updates.items():
        if key in {"summary", "description", "location"}:
            lines.append(f"{key.capitalize()}: {value}")
        elif key in {"start_time", "end_time"} and isinstance(value, str):
            lines.append(f"{key.replace('_', ' ').capitalize()}: {value}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def format_delete_preview(event: CalendarEventSchema) -> str:
    """Return a preview string for a DELETE request.

    Shows the event that will be removed.
    """
    start = event.start_time.strftime("%Y-%m-%d %H:%M")
    end = event.end_time.strftime("%Y-%m-%d %H:%M")
    lines = ["Ștergere eveniment:", f"Titlu: {event.summary}", f"Data: {start} – {end}"]
    if event.location:
        lines.append(f"Locație: {event.location}")
    return "\n".join(lines)
