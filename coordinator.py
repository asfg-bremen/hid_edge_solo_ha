"""Zentrale Datenabfrage für einen Controller."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EdgeSoloAuthError, EdgeSoloClient, EdgeSoloError
from .const import CARDHOLDER_REFRESH, DOMAIN, EVENT_COUNT, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class EdgeSoloCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holt Türstatus, Ereignisse und (stündlich) die Personenliste."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: EdgeSoloClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_HOST]}",
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self._cardholders: list[dict[str, Any]] = []
        self._cardholders_updated: datetime | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            door = await self.client.get_door()
            events = await self.client.get_events(EVENT_COUNT)
            now = dt_util.utcnow()
            if (
                self._cardholders_updated is None
                or now - self._cardholders_updated > CARDHOLDER_REFRESH
            ):
                self._cardholders = await self.client.get_cardholders()
                self._cardholders_updated = now
        except EdgeSoloAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EdgeSoloError as err:
            raise UpdateFailed(str(err)) from err
        return {"door": door, "events": events, "cardholders": self._cardholders}
