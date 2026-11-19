"""HID Edge Solo – Zutrittscontroller in Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import EdgeSoloClient
from .const import DOMAIN, STORAGE_VERSION
from .coordinator import EdgeSoloCoordinator
from .frontend import async_register_card
from .services import async_setup_services

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type EdgeSoloConfigEntry = ConfigEntry[EdgeSoloCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    # Dienste einmal pro Integration registrieren, nicht pro Controller
    async_setup_services(hass)
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EdgeSoloConfigEntry) -> bool:
    client = EdgeSoloClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = EdgeSoloCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EdgeSoloConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: EdgeSoloConfigEntry) -> None:
    """Gespeicherte "erstmals gesehen"-Daten beim Entfernen mitlöschen."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
