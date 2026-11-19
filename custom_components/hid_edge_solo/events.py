"""Ereignisse des Controllers für Sensoren und den Dienst get_events aufbereiten."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import EVENT_TYPES


def parse_time(value: str | None) -> datetime | None:
    """Gerätezeit (lokal, ohne Zeitzone) -> zeitzonenbewusst."""
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed


def event_name(event: dict[str, str]) -> str:
    name = f"{event.get('forename', '')} {event.get('surname', '')}".strip()
    return name or "Unbekannt"


def event_type(event: dict[str, str]) -> str:
    code = event.get("eventType", "")
    try:
        return EVENT_TYPES.get(int(code), f"Ereignis {code}")
    except ValueError:
        return f"Ereignis {code}"


def event_entry(event: dict[str, str]) -> dict[str, Any]:
    """Ein Ereignis ohne Kartennummern: Name, Zeit (ISO) und Art."""
    ts = parse_time(event.get("timestamp"))
    return {
        "name": event_name(event),
        "zeit": ts.isoformat() if ts else None,
        "ereignis": event_type(event),
    }
