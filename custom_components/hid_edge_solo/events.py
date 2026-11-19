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


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def usage_keys(event: dict[str, str]) -> list[str]:
    """Schlüssel, unter denen die letzte Verwendung einer Person gespeichert wird.

    Über die cardholderID, wenn der Controller sie mitliefert, sonst über den
    Namen. Ereignisse ohne Person (z. B. unbekannte Karte) zählen nicht.
    """
    keys = []
    cardholder_id = (event.get("cardholderID") or "").strip()
    if cardholder_id:
        keys.append(f"id:{cardholder_id}")
    name = f"{event.get('forename', '')} {event.get('surname', '')}".strip()
    if name:
        keys.append(f"name:{_norm(name)}")
    return keys


def person_usage_keys(person: dict[str, Any]) -> list[str]:
    keys = []
    if person.get("id"):
        keys.append(f"id:{person['id']}")
    name = f"{person.get('vorname', '')} {person.get('nachname', '')}".strip()
    if name:
        keys.append(f"name:{_norm(name)}")
    return keys


def merge_last_used(known: dict[str, str], events: list[dict[str, str]]) -> bool:
    """Trägt die Ereignisse in known ein (Schlüssel -> ISO-Zeit). True bei Änderung."""
    changed = False
    for event in events:
        ts = parse_time(event.get("timestamp"))
        if ts is None:
            continue
        for key in usage_keys(event):
            old = parse_time(known.get(key))
            if old is None or ts > old:
                known[key] = ts.isoformat()
                changed = True
    return changed


def last_used(known: dict[str, str], person: dict[str, Any]) -> str | None:
    """Letzte Verwendung einer Person (ISO) oder None."""
    found = [t for t in (parse_time(known.get(k)) for k in person_usage_keys(person)) if t]
    return max(found).isoformat() if found else None
