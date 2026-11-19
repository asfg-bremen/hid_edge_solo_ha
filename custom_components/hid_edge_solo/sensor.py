"""Letzte Zutritte und Liste der Zutrittsberechtigten."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EdgeSoloConfigEntry
from .access import ALL_STATUSES, STATUS_ACTIVE
from .const import EVENT_TYPES, NEW_GRANT_WINDOW
from .coordinator import person_name
from .entity import EdgeSoloEntity


def _parse_time(value: str | None) -> datetime | None:
    """Gerätezeit (lokal, ohne Zeitzone) -> zeitzonenbewusst."""
    if not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return parsed


def _event_name(event: dict[str, str]) -> str:
    name = f"{event.get('forename', '')} {event.get('surname', '')}".strip()
    return name or "Unbekannt"


def _event_type(event: dict[str, str]) -> str:
    code = event.get("eventType", "")
    try:
        return EVENT_TYPES.get(int(code), f"Ereignis {code}")
    except ValueError:
        return f"Ereignis {code}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdgeSoloConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            LastAccessSensor(coordinator),
            LastAccessTimeSensor(coordinator),
            CardholderSensor(coordinator),
            NewGrantsSensor(coordinator),
        ]
    )


class LastAccessSensor(EdgeSoloEntity, SensorEntity):
    """Name der letzten Person + Verlauf der letzten Zutritte."""

    _attr_name = "Letzter Zutritt"
    _attr_icon = "mdi:card-account-details"
    _unrecorded_attributes = frozenset({"verlauf"})

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "last_access")

    @property
    def native_value(self) -> str | None:
        events = self.coordinator.data["events"]
        return _event_name(events[0]) if events else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        events = self.coordinator.data["events"]
        verlauf = []
        for ev in events:
            ts = _parse_time(ev.get("timestamp"))
            verlauf.append(
                {
                    "name": _event_name(ev),
                    "zeit": ts.isoformat() if ts else None,
                    "ereignis": _event_type(ev),
                }
            )
        attrs: dict[str, Any] = {"verlauf": verlauf}
        if verlauf:
            attrs["zeit"] = verlauf[0]["zeit"]
            attrs["ereignis"] = verlauf[0]["ereignis"]
        return attrs


class LastAccessTimeSensor(EdgeSoloEntity, SensorEntity):
    """Zeitpunkt des letzten Zutritts."""

    _attr_name = "Letzter Zutritt Zeit"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "last_access_time")

    @property
    def native_value(self) -> datetime | None:
        events = self.coordinator.data["events"]
        return _parse_time(events[0].get("timestamp")) if events else None


class _CardholderBase(EdgeSoloEntity, SensorEntity):
    """Gemeinsames für die Sensoren der Personenliste."""

    _attr_native_unit_of_measurement = "Personen"
    _unrecorded_attributes = frozenset({"personen", "zeitplaene"})

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data["cardholders_meta"]["geladen"]

    def _meta(self) -> dict[str, Any]:
        meta = self.coordinator.data["cardholders_meta"]
        stand = meta["stand"]
        return {
            "vollstaendig": meta["vollstaendig"],
            "stand": stand.isoformat() if stand else None,
            "fehler": meta["fehler"],
        }


def _person_attr(p: dict[str, Any]) -> dict[str, Any]:
    """Eine Person für die Attribute (ohne Kartennummern)."""
    return {
        "id": p["id"],
        "name": person_name(p),
        "vorname": p["vorname"],
        "nachname": p["nachname"],
        "status": p["status"],
        "neu": p["neu"],
        "zeitplan": p["zeitplan"],
        "zeitplaene": [r["zeitplan"] or r["zeitplan_id"] for r in p["rollen"]],
        "ausweise": len(p["ausweise"]),
        "gueltig_bis": _latest_end(p),
        "erstmals_gesehen": p.get("erstmals_gesehen"),
    }


def _latest_end(p: dict[str, Any]) -> str | None:
    """Spätestes Ablaufdatum aller Ausweise (None = unbegrenzt/unbekannt)."""
    ends = [c.get("ende") for c in p["ausweise"]]
    if not ends or any(not e for e in ends):
        return None
    parsed = [t for t in (_parse_time(e) for e in ends) if t is not None]
    return max(parsed).isoformat() if parsed else None


class CardholderSensor(_CardholderBase):
    """Anzahl der Personen mit aktuell gültiger Freigabe.

    Das Attribut 'personen' enthält alle Personen am Controller mit Status,
    sodass auch abgelaufene oder geplante Freigaben sichtbar bleiben.
    """

    _attr_name = "Zutrittsberechtigte"
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "cardholders")

    @property
    def native_value(self) -> int:
        return sum(1 for p in self.coordinator.cardholder_view() if p["status"] == STATUS_ACTIVE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        people = self.coordinator.cardholder_view()
        counts = {status: 0 for status in ALL_STATUSES}
        for p in people:
            counts[p["status"]] += 1
        return {
            "gesamt": len(people),
            **{f"anzahl_{status}": count for status, count in counts.items()},
            **self._meta(),
            "zeitplaene": [
                {"id": sid, "name": name}
                for sid, name in self.coordinator.known_schedules().items()
            ],
            "personen": [_person_attr(p) for p in people],
        }


class NewGrantsSensor(_CardholderBase):
    """Personen, die innerhalb der letzten Tage neu hinzugekommen sind."""

    _attr_name = "Neue Freigaben"
    _attr_icon = "mdi:account-plus"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "new_cardholders")

    def _new(self) -> list[dict[str, Any]]:
        people = [p for p in self.coordinator.cardholder_view() if p["neu"]]
        people.sort(key=lambda p: p.get("erstmals_gesehen") or "", reverse=True)
        return people

    @property
    def native_value(self) -> int:
        return len(self._new())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "zeitraum_tage": NEW_GRANT_WINDOW.days,
            **self._meta(),
            "personen": [_person_attr(p) for p in self._new()],
        }
