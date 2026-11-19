"""Integrationstest in einer Test-HA-Instanz. Der Controller-Client ist gemockt."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.hid_edge_solo.api import CardholderList, EdgeSoloError
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

    configs = http.async_register_static_paths.await_args.args[0]
    assert [c.url_path for c in configs] == [
        "/hid_edge_solo/zugangs-uebersicht-card.js",
        "/hid_edge_solo/zutritte-card.js",
    ]
    assert all(Path(c.path).is_file() for c in configs)
    urls = [c.args[1] for c in add_js.call_args_list]
    assert urls[0].startswith("/hid_edge_solo/zugangs-uebersicht-card.js?v=")
    assert urls[1].startswith("/hid_edge_solo/zutritte-card.js?v=")


async def test_card_not_registered_without_frontend(hass: HomeAssistant) -> None:
    from custom_components.hid_edge_solo.frontend import async_register_card

    hass.http = None
    await async_register_card(hass)  # darf nicht fehlschlagen


_EVENT = {"forename": "Anna", "surname": "A", "timestamp": "2026-11-18T14:32:00", "eventType": "2020", "cardNumber": "123"}


async def test_connection_sensor(hass: HomeAssistant, client) -> None:
    entry = await _setup(hass)
    assert hass.states.get("binary_sensor.tur_verbindung").state == "on"
    client.get_door.side_effect = EdgeSoloError("Controller nicht erreichbar")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.tur_verbindung")
    assert state.state == "off"  # bleibt verfügbar, zeigt "getrennt"
    assert "nicht erreichbar" in state.attributes["fehler"]
    assert hass.states.get("sensor.tur_letzter_zutritt").state == "unavailable"


async def test_last_access_attributes(hass: HomeAssistant, client) -> None:
    client.get_events.return_value = [_EVENT]
    entry = await _setup(hass)
    state = hass.states.get("sensor.tur_letzter_zutritt")
    assert state.state == "Anna A"
    assert state.attributes["config_entry_id"] == entry.entry_id
    assert state.attributes["verlauf"][0]["ereignis"] == "Zutritt gewährt"
    assert "cardNumber" not in state.attributes["verlauf"][0]


async def test_get_events_service(hass: HomeAssistant, client) -> None:
    entry = await _setup(hass)
    client.get_events.reset_mock()
    client.get_events.return_value = [_EVENT, {**_EVENT, "forename": "Bob", "eventType": "9999"}]
    resp = await hass.services.async_call(
        DOMAIN, "get_events", {"anzahl": 300}, blocking=True, return_response=True)
    client.get_events.assert_awaited_once_with(300)
    assert resp["config_entry_id"] == entry.entry_id
    assert [e["name"] for e in resp["ereignisse"]] == ["Anna A", "Bob A"]
    assert resp["ereignisse"][1]["ereignis"] == "Ereignis 9999"
    assert resp["ereignisse"][0]["zeit"].startswith("2026-11-18T14:32:00")
    assert all("cardNumber" not in e for e in resp["ereignisse"])


async def test_get_events_limits(hass: HomeAssistant, client) -> None:
    await _setup(hass)
    import voluptuous as vol
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "get_events", {"anzahl": 5000}, blocking=True, return_response=True)


async def test_people_beyond_old_limit_are_not_new_after_update(hass: HomeAssistant, client) -> None:
    """Gespeicherte Daten aus 0.0.5 (Format 1, max. 50 Personen): wer jetzt
    erstmals auftaucht, ist Bestand und löst keine Ereignisse aus."""
    from homeassistant.helpers.storage import Store

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "192.0.2.1", CONF_USERNAME: "u", CONF_PASSWORD: "p"}, title="Tür")
    entry.add_to_hass(hass)
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_save({"first_seen": {"1": None}})
    added = async_capture_events(hass, EVENT_CARDHOLDER_ADDED)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert added == []
    assert hass.states.get("sensor.tur_neue_freigaben").state == "0"

    # Danach gilt wieder: wer neu dazukommt, ist neu
    client.get_cardholders.return_value = CardholderList(
        people=[_p("1", "Anna", "A"), _p("2", "Bob", "B"), _p("3", "Cem", "C"), _p("5", "Eva", "E")],
        complete=True, requests=1)
    await hass.services.async_call(DOMAIN, "refresh_cardholders", {}, blocking=True)
    await hass.async_block_till_done()
    assert [e.data["cardholder_id"] for e in added] == ["5"]


def _ev(vor, nach, ts, cid=None):
    ev = {"forename": vor, "surname": nach, "timestamp": ts, "eventType": "2020"}
    if cid:
        ev["cardholderID"] = cid
    return ev


async def test_last_used_from_events(hass: HomeAssistant, client) -> None:
    """Letzte Verwendung je Person, über ID oder Namen, dauerhaft gespeichert."""
    client.get_events.return_value = [
        _ev("Anna", "A", "2026-11-18T10:00:00", cid="1"),
        _ev("Anna", "A", "2026-11-17T09:00:00", cid="1"),
        _ev("Bob", "B", "2026-11-10T08:00:00"),  # ohne ID: über den Namen
        _ev("", "", "2026-11-18T11:00:00"),  # unbekannte Karte zählt nicht
    ]
    entry = await _setup(hass)
    state = hass.states.get("sensor.tur_zutrittsberechtigte")
    used = {p["id"]: p["letzte_verwendung"] for p in state.attributes["personen"]}
    assert used["1"].startswith("2026-11-18T10:00:00")
    assert used["2"].startswith("2026-11-10T08:00:00")
    assert used["3"] is None
    assert state.attributes["verwendung_seit"].startswith("2026-11-10T08:00:00")

    # Neuer Zutritt kommt über die laufende Abfrage dazu
    client.get_events.return_value = [_ev("Cem", "C", "2026-11-19T07:30:00", cid="3")]
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("sensor.tur_zutrittsberechtigte")
    used = {p["id"]: p["letzte_verwendung"] for p in state.attributes["personen"]}
    assert used["3"].startswith("2026-11-19T07:30:00")
    assert used["1"].startswith("2026-11-18T10:00:00")  # bleibt erhalten


async def test_backfill_falls_back_to_fewer_events(hass: HomeAssistant, client) -> None:
    """Beim Start werden mehr Ereignisse geladen, notfalls weniger."""
    calls = []

    async def events(count):
        calls.append(count)
        if count > 50:
            raise EdgeSoloError("Ungültige XML-Antwort")
        return [_ev("Anna", "A", "2026-11-01T10:00:00", cid="1")]

    client.get_events.side_effect = events
    await _setup(hass)
    assert calls[:2] == [200, 50]
    state = hass.states.get("sensor.tur_zutrittsberechtigte")
    used = {p["id"]: p["letzte_verwendung"] for p in state.attributes["personen"]}
    assert used["1"].startswith("2026-11-01T10:00:00")


async def test_usage_stored_before_first_list_does_not_mark_everyone_new(hass: HomeAssistant, client) -> None:
    """Gespeicherte Verwendungen ohne Personenliste: erstes Laden bleibt Bestand."""
    from homeassistant.helpers.storage import Store

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "192.0.2.1", CONF_USERNAME: "u", CONF_PASSWORD: "p"}, title="Tür")
    entry.add_to_hass(hass)
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_save(
        {"format": 2, "first_seen": None, "last_used": {}, "verwendung_seit": None})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.tur_neue_freigaben").state == "0"
