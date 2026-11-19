"""Button zum sofortigen Neuladen der Personenliste (nur lesend)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EdgeSoloConfigEntry
from .api import EdgeSoloError
from .entity import EdgeSoloEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EdgeSoloConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([RefreshCardholdersButton(entry.runtime_data)])


class RefreshCardholdersButton(EdgeSoloEntity, ButtonEntity):
    _attr_name = "Personenliste aktualisieren"
    _attr_icon = "mdi:account-sync"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "refresh_cardholders")

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_refresh_cardholders()
        except EdgeSoloError as err:
            raise HomeAssistantError(f"Personenliste konnte nicht geladen werden: {err}") from err
