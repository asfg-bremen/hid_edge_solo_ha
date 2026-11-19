"""Integrationstest in einer Test-HA-Instanz. Der Controller-Client ist gemockt."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.hid_edge_solo.api import CardholderList
from custom_components.hid_edge_solo.const import DOMAIN, EVENT_CARDHOLDER_ADDED, EVENT_CARDHOLDER_REMOVED


def _p(pid, vor, nach, *, ende=None, rollen=True):
    return {
        "id": pid, "vorname": vor, "nachname": nach, "zeitplan": "Immer" if rollen else None,
        "rollen": [{"rolle_id": pid, "zeitplan_id": "1", "zeitplan": "Immer", "start": None, "ende": None}] if rollen else [],
        "ausweise": [{"karte": True, "start": None, "ende": ende}],
    }


@pytest.fixture
def client():
    with patch("custom_components.hid_edge_solo.EdgeSoloClient", autospec=True) as cls:
        c = cls.return_value
        c.get_door = AsyncMock(return_value={"relayState": "unset"})
        c.get_events = AsyncMock(return_value=[])
        c.get_cardholders = AsyncMock(return_value=CardholderList(
            people=[_p("1", "Anna", "A"), _p("2", "Bob", "B", ende="2000-01-01T00:00:00"), _p("3", "Cem", "C", rollen=False)],
            complete=True, requests=1))
        c.add_cardholder = AsyncMock(return_value="9")
        c.assign_schedule = AsyncMock()
        c.delete_cardholder = AsyncMock()
        yield c


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "192.0.2.1", CONF_USERNAME: "u", CONF_PASSWORD: "p"}, title="Tür")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_status_and_new(hass: HomeAssistant, client) -> None:
    entry = await _setup(hass)
    state = hass.states.get("sensor.tur_zutrittsberechtigte")
    assert state.state == "1"  # nur Anna aktiv
    assert state.attributes["gesamt"] == 3
    status = {p["id"]: p["status"] for p in state.attributes["personen"]}
    assert status == {"1": "aktiv", "2": "abgelaufen", "3": "kein_zeitplan"}
    assert state.attributes["zeitplaene"] == [{"id": "1", "name": "Immer"}]
    # Für die Dashboard-Karte
    assert state.attributes["config_entry_id"] == entry.entry_id
    assert state.attributes["controller"] == "Tür"
    # Erstes Laden = Bestand, nichts ist neu
    assert hass.states.get("sensor.tur_neue_freigaben").state == "0"


async def test_new_person_and_events(hass: HomeAssistant, client) -> None:
    await _setup(hass)
    added = async_capture_events(hass, EVENT_CARDHOLDER_ADDED)
    removed = async_capture_events(hass, EVENT_CARDHOLDER_REMOVED)
    client.get_cardholders.return_value = CardholderList(
        people=[_p("1", "Anna", "A"), _p("4", "Dora", "D")], complete=True, requests=1)
    await hass.services.async_call(DOMAIN, "refresh_cardholders", {}, blocking=True)
    await hass.async_block_till_done()
    new = hass.states.get("sensor.tur_neue_freigaben")
    assert new.state == "1" and new.attributes["personen"][0]["name"] == "Dora D"
    assert [e.data["cardholder_id"] for e in added] == ["4"]
    assert sorted(e.data["cardholder_id"] for e in removed) == ["2", "3"]


async def test_incomplete_list_no_removals(hass: HomeAssistant, client) -> None:
    await _setup(hass)
    removed = async_capture_events(hass, EVENT_CARDHOLDER_REMOVED)
    client.get_cardholders.return_value = CardholderList(people=[_p("1", "Anna", "A")], complete=False, requests=1000)
    await hass.services.async_call(DOMAIN, "refresh_cardholders", {}, blocking=True)
    await hass.async_block_till_done()
    assert removed == []
    assert hass.states.get("sensor.tur_zutrittsberechtigte").attributes["vollstaendig"] is False


async def test_add_and_delete_services(hass: HomeAssistant, client) -> None:
    await _setup(hass)
    resp = await hass.services.async_call(
        DOMAIN, "add_cardholder", {"forename": "Eva", "surname": "E", "schedule_id": "1"},
        blocking=True, return_response=True)
    assert resp["cardholder_id"] == "9"
    client.add_cardholder.assert_awaited_once_with("Eva", "E")
    client.assign_schedule.assert_awaited_once_with("9", "1")

    resp = await hass.services.async_call(
        DOMAIN, "delete_cardholder", {"cardholder_id": "2"}, blocking=True, return_response=True)
    assert resp == {"cardholder_id": "2", "name": "Bob B"}
    client.delete_cardholder.assert_awaited_once_with("2")


async def test_delete_unknown_id_is_rejected(hass: HomeAssistant, client) -> None:
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "delete_cardholder", {"cardholder_id": "777"}, blocking=True)
    client.delete_cardholder.assert_not_awaited()


async def test_add_unknown_schedule_is_rejected(hass: HomeAssistant, client) -> None:
    await _setup(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "add_cardholder", {"forename": "X", "surname": "Y", "schedule_id": "55"}, blocking=True)
    client.add_cardholder.assert_not_awaited()


async def test_card_is_registered_with_frontend(hass: HomeAssistant) -> None:
    from pathlib import Path
    from unittest.mock import MagicMock

    from custom_components.hid_edge_solo.frontend import async_register_card

    http = MagicMock()
    http.async_register_static_paths = AsyncMock()
    hass.http = http
    hass.config.components.add("frontend")
    with patch("homeassistant.components.frontend.add_extra_js_url") as add_js:
        await async_register_card(hass)

    (config,) = http.async_register_static_paths.await_args.args[0]
    assert config.url_path == "/hid_edge_solo/zugangs-uebersicht-card.js"
    assert Path(config.path).is_file()
    url = add_js.call_args.args[1]
    assert url.startswith("/hid_edge_solo/zugangs-uebersicht-card.js?v=")


async def test_card_not_registered_without_frontend(hass: HomeAssistant) -> None:
    from custom_components.hid_edge_solo.frontend import async_register_card

    hass.http = None
    await async_register_card(hass)  # darf nicht fehlschlagen
