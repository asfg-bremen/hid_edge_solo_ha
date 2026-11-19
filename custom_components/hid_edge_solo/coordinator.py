"""Zentrale Datenabfrage für einen Controller."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .access import access_status, is_new, merge_first_seen
from .api import EdgeSoloAuthError, EdgeSoloClient, EdgeSoloError
from .const import (
    CARDHOLDER_REFRESH,
    CARDHOLDER_RETRY,
    DOMAIN,
    EVENT_CARDHOLDER_ADDED,
    EVENT_CARDHOLDER_REMOVED,
    EVENT_COUNT,
    NEW_GRANT_WINDOW,
    SCAN_INTERVAL,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def person_name(person: dict[str, Any]) -> str:
    return f"{person.get('vorname', '')} {person.get('nachname', '')}".strip()


class EdgeSoloCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holt Türstatus und Ereignisse (alle 30 s) sowie die Personenliste."""

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
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        # cardholderID -> erstmals gesehen (ISO) bzw. None für den Bestand.
        # None insgesamt = noch nie geladen (erste Installation).
        self._first_seen: dict[str, str | None] | None = None
        # Verhindert, dass Blättern und Schreibzugriffe sich überlappen
        self._cardholder_lock = asyncio.Lock()
        self._cardholders: list[dict[str, Any]] = []
        self._cardholders_loaded = False
        self._cardholders_complete = False
        self._cardholders_updated: datetime | None = None
        self._cardholders_error: str | None = None
        self._next_cardholder_refresh: datetime | None = None

    async def _async_setup(self) -> None:
        stored = await self._store.async_load()
        if stored is not None:
            self._first_seen = dict(stored.get("first_seen") or {})

    # ----------------------------------------------------------- Abfrage

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            door = await self.client.get_door()
            events = await self.client.get_events(EVENT_COUNT)
        except EdgeSoloAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EdgeSoloError as err:
            raise UpdateFailed(str(err)) from err

        now = dt_util.utcnow()
        if self._next_cardholder_refresh is None or now >= self._next_cardholder_refresh:
            try:
                await self._load_cardholders()
            except EdgeSoloAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except EdgeSoloError as err:
                # Türstatus trotzdem aktualisieren, alte Liste behalten
                _LOGGER.warning("Personenliste konnte nicht geladen werden: %s", err)
        return {"door": door, "events": events, **self._cardholder_data()}

    def _cardholder_data(self) -> dict[str, Any]:
        return {
            "cardholders": self._cardholders,
            "cardholders_meta": {
                "geladen": self._cardholders_loaded,
                "vollstaendig": self._cardholders_complete,
                "stand": self._cardholders_updated,
                "fehler": self._cardholders_error,
            },
        }

    async def _load_cardholders(self) -> None:
        async with self._cardholder_lock:
            await self._load_cardholders_locked()

    async def _load_cardholders_locked(self) -> None:
        now = dt_util.utcnow()
        try:
            result = await self.client.get_cardholders()
        except EdgeSoloError as err:
            self._cardholders_error = str(err)
            self._next_cardholder_refresh = now + CARDHOLDER_RETRY
            raise

        previous = {p["id"]: p for p in self._cardholders if p["id"]}
        ids = [p["id"] for p in result.people if p["id"]]
        first_seen, added, removed = merge_first_seen(
            self._first_seen, ids, now, remove_missing=result.complete
        )
        self._first_seen = first_seen
        self._store.async_delay_save(lambda: {"first_seen": self._first_seen}, 10)

        for person in result.people:
            person["erstmals_gesehen"] = first_seen.get(person["id"]) if person["id"] else None

        self._cardholders = result.people
        self._cardholders_loaded = True
        self._cardholders_complete = result.complete
        self._cardholders_updated = now
        self._cardholders_error = (
            None if result.complete else "Personenliste wurde nur teilweise geladen"
        )
        self._next_cardholder_refresh = now + (
            CARDHOLDER_REFRESH if result.complete else CARDHOLDER_RETRY
        )
        _LOGGER.debug(
            "Personenliste geladen: %s Personen in %s Anfragen, vollständig=%s",
            len(result.people),
            result.requests,
            result.complete,
        )

        current = {p["id"]: p for p in result.people if p["id"]}
        entry_id = self.config_entry.entry_id
        for pid in added:
            self.hass.bus.async_fire(
                EVENT_CARDHOLDER_ADDED,
                {"config_entry_id": entry_id, "cardholder_id": pid, "name": person_name(current[pid])},
            )
        for pid in removed:
            old = previous.get(pid)
            self.hass.bus.async_fire(
                EVENT_CARDHOLDER_REMOVED,
                {
                    "config_entry_id": entry_id,
                    "cardholder_id": pid,
                    "name": person_name(old) if old else None,
                },
            )

    async def async_refresh_cardholders(self) -> None:
        """Personenliste sofort neu laden und Entitäten aktualisieren.

        Wirft EdgeSoloError, damit Dienstaufrufe einen Fehler sehen.
        """
        try:
            await self._load_cardholders()
        finally:
            if self.data is not None:
                self.async_set_updated_data({**self.data, **self._cardholder_data()})

    async def _refresh_after_write(self) -> None:
        try:
            await self.async_refresh_cardholders()
        except EdgeSoloError as err:
            _LOGGER.warning(
                "Änderung wurde gesendet, die Personenliste konnte danach aber "
                "nicht neu geladen werden: %s",
                err,
            )

    # ------------------------------------------------------- Auswertung

    def cardholder_view(self) -> list[dict[str, Any]]:
        """Personen mit aktuellem Freigabestatus und Kennzeichen "neu".

        Wird bei jeder Aktualisierung neu berechnet, damit ablaufende oder
        beginnende Freigaben ohne Neuladen der Liste umspringen.
        """
        people = (self.data or {}).get("cardholders", [])
        now = dt_util.now()
        tz = dt_util.get_default_time_zone()
        # Nur prüfen, was der Controller im Listenformat überhaupt mitliefert
        check_roles = any(p.get("rollen") for p in people)
        check_credentials = any(p.get("ausweise") for p in people)
        return [
            {
                **p,
                "status": access_status(
                    p, now, tz, check_roles=check_roles, check_credentials=check_credentials
                ),
                "neu": is_new(p.get("erstmals_gesehen"), now, NEW_GRANT_WINDOW),
            }
            for p in people
        ]

    def find_cardholder(self, cardholder_id: str) -> dict[str, Any] | None:
        for person in self._cardholders:
            if person["id"] == cardholder_id:
                return person
        return None

    def known_schedules(self) -> dict[str, str | None]:
        """Zeitpläne, die in der Personenliste vorkommen (ID -> Name)."""
        schedules: dict[str, str | None] = {}
        for person in self._cardholders:
            for role in person.get("rollen", []):
                sid = role.get("zeitplan_id")
                if sid and (sid not in schedules or schedules[sid] is None):
                    schedules[sid] = role.get("zeitplan")
        return dict(sorted(schedules.items(), key=lambda kv: (kv[1] or "", kv[0])))

    # ------------------------------------------------------- Schreiben
    # Ändert die Zutrittsdaten am Controller. Nur über die Dienste aufrufen.

    async def async_add_cardholder(
        self, forename: str, surname: str, schedule_id: str | None = None
    ) -> str:
        try:
            async with self._cardholder_lock:
                cardholder_id = await self.client.add_cardholder(forename, surname)
                _LOGGER.info("Person %s am Controller angelegt", cardholder_id)
                if schedule_id:
                    try:
                        await self.client.assign_schedule(cardholder_id, schedule_id)
                    except EdgeSoloError as err:
                        raise EdgeSoloError(
                            f"Person {cardholder_id} wurde angelegt, der Zeitplan "
                            f"{schedule_id} konnte aber nicht zugewiesen werden: {err}"
                        ) from err
                    _LOGGER.info(
                        "Zeitplan %s an Person %s zugewiesen", schedule_id, cardholder_id
                    )
        finally:
            await self._refresh_after_write()
        return cardholder_id

    async def async_delete_cardholder(self, cardholder_id: str) -> None:
        try:
            async with self._cardholder_lock:
                await self.client.delete_cardholder(cardholder_id)
                _LOGGER.info("Person %s am Controller gelöscht", cardholder_id)
        finally:
            await self._refresh_after_write()
