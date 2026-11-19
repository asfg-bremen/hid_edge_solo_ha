"""Dienste: Personenliste neu laden, Person anlegen, Person löschen.

add_cardholder und delete_cardholder ändern die Zutrittsdaten am Controller.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import EdgeSoloError
from .const import DOMAIN
from .coordinator import EdgeSoloCoordinator, person_name

SERVICE_REFRESH = "refresh_cardholders"
SERVICE_ADD = "add_cardholder"
SERVICE_DELETE = "delete_cardholder"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_CARDHOLDER_ID = "cardholder_id"
ATTR_FORENAME = "forename"
ATTR_SURNAME = "surname"
ATTR_SCHEDULE_ID = "schedule_id"

_ENTRY = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}
_NAME = vol.All(cv.string, vol.Strip, vol.Length(min=1, max=64))
_ID = vol.All(vol.Coerce(str), vol.Strip, vol.Match(r"^\d+$"))

REFRESH_SCHEMA = vol.Schema(_ENTRY)
ADD_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_FORENAME): _NAME,
        vol.Required(ATTR_SURNAME): _NAME,
        vol.Optional(ATTR_SCHEDULE_ID): _ID,
    }
)
DELETE_SCHEMA = vol.Schema({**_ENTRY, vol.Required(ATTR_CARDHOLDER_ID): _ID})


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> EdgeSoloCoordinator:
    """Controller aus config_entry_id; ohne Angabe nur, wenn genau einer existiert."""
    loaded = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id:
        for entry in loaded:
            if entry.entry_id == entry_id:
                return entry.runtime_data
        raise ServiceValidationError(
            f"Kein geladener HID-Edge-Solo-Controller mit der ID {entry_id}"
        )
    if len(loaded) == 1:
        return loaded[0].runtime_data
    if not loaded:
        raise ServiceValidationError("Kein HID-Edge-Solo-Controller geladen")
    raise ServiceValidationError(
        "Mehrere Controller eingerichtet, bitte config_entry_id angeben"
    )


async def _refresh(call: ServiceCall) -> None:
    coordinator = _coordinator(call.hass, call)
    try:
        await coordinator.async_refresh_cardholders()
    except EdgeSoloError as err:
        raise HomeAssistantError(f"Personenliste konnte nicht geladen werden: {err}") from err


async def _add(call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(call.hass, call)
    forename: str = call.data[ATTR_FORENAME]
    surname: str = call.data[ATTR_SURNAME]
    schedule_id: str | None = call.data.get(ATTR_SCHEDULE_ID)

    known = coordinator.known_schedules()
    if schedule_id and known and schedule_id not in known:
        raise ServiceValidationError(
            f"Zeitplan {schedule_id} ist unbekannt. Bekannte Zeitpläne: "
            + ", ".join(f"{sid} ({name or '?'})" for sid, name in known.items())
        )

    try:
        cardholder_id = await coordinator.async_add_cardholder(forename, surname, schedule_id)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
    except EdgeSoloError as err:
        raise HomeAssistantError(f"Person konnte nicht angelegt werden: {err}") from err
    return {ATTR_CARDHOLDER_ID: cardholder_id, "name": f"{forename} {surname}"}


async def _delete(call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(call.hass, call)
    cardholder_id: str = call.data[ATTR_CARDHOLDER_ID]

    # Nur löschen, was in der zuletzt geladenen Liste steht. Schützt vor
    # Tippfehlern bei der ID und vor veralteten Dashboard-Ansichten.
    person = coordinator.find_cardholder(cardholder_id)
    if person is None:
        raise ServiceValidationError(
            f"Person mit der ID {cardholder_id} ist in der Personenliste nicht "
            "vorhanden. Gegebenenfalls zuerst die Liste aktualisieren."
        )
    name = person_name(person)
    try:
        await coordinator.async_delete_cardholder(cardholder_id)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err
    except EdgeSoloError as err:
        raise HomeAssistantError(f"Person {name} konnte nicht gelöscht werden: {err}") from err
    return {ATTR_CARDHOLDER_ID: cardholder_id, "name": name}


def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _refresh, schema=REFRESH_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD,
        _add,
        schema=ADD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE,
        _delete,
        schema=DELETE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

