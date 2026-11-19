"""Letzte Zutritte und Liste der Zutrittsberechtigten."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EdgeSoloConfigEntry
from .const import EVENT_TYPES
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


class CardholderSensor(EdgeSoloEntity, SensorEntity):
    """Anzahl der Berechtigten; die Liste steht im Attribut 'personen'."""

    _attr_name = "Zutrittsberechtigte"
    _attr_icon = "mdi:account-group"
    _attr_native_unit_of_measurement = "Personen"
    _unrecorded_attributes = frozenset({"personen"})

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "cardholders")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data["cardholders"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "personen": [
                {
                    "name": f"{p['vorname']} {p['nachname']}".strip(),
                    "zeitplan": p["zeitplan"],
                }
                for p in self.coordinator.data["cardholders"]
            ]
        }
