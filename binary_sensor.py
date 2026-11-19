"""Verriegelungs- und Alarmstatus als Binärsensoren."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EdgeSoloConfigEntry
from .entity import EdgeSoloEntity


@dataclass(frozen=True, kw_only=True)
class EdgeSoloBinaryDescription(BinarySensorEntityDescription):
    attr: str


DESCRIPTIONS: tuple[EdgeSoloBinaryDescription, ...] = (
    # Gerätklasse "lock": an = entriegelt, aus = verriegelt
    EdgeSoloBinaryDescription(
        key="lock", attr="relayState", name="Schloss",
        device_class=BinarySensorDeviceClass.LOCK,
    ),
    EdgeSoloBinaryDescription(
        key="door_forced", attr="doorForcedAlarmState", name="Tür aufgebrochen",
        device_class=BinarySensorDeviceClass.SAFETY,
    ),
    EdgeSoloBinaryDescription(
        key="door_held", attr="doorHeldAlarmState", name="Tür zu lange offen",
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
    EdgeSoloBinaryDescription(
        key="tamper", attr="tamperAlarmState", name="Sabotage",
        device_class=BinarySensorDeviceClass.TAMPER,
    ),
    EdgeSoloBinaryDescription(
        key="ac", attr="acAlarmState", name="Netzstörung",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EdgeSoloBinaryDescription(
        key="battery", attr="batteryAlarmState", name="Batterie",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    EdgeSoloBinaryDescription(
        key="relay_alert", attr="relayAlertState", name="Relaisstörung",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdgeSoloConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        EdgeSoloBinarySensor(coordinator, description) for description in DESCRIPTIONS
    )


class EdgeSoloBinarySensor(EdgeSoloEntity, BinarySensorEntity):
    entity_description: EdgeSoloBinaryDescription

    def __init__(self, coordinator, description: EdgeSoloBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data["door"].get(self.entity_description.attr)
        if value is None:
            return None
        return value == "set"
