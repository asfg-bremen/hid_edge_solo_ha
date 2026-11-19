"""Gemeinsame Basis für alle Entitäten eines Controllers."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EdgeSoloCoordinator


class EdgeSoloEntity(CoordinatorEntity[EdgeSoloCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EdgeSoloCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HID Global",
            model="Edge Solo",
            configuration_url=f"http://{entry.data[CONF_HOST]}/",
        )
