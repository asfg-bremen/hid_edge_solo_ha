"""Tests für api.py und access.py mit simulierten Controller-Antworten.

Beide Module werden direkt per Pfad geladen, damit die Tests auch ohne
installiertes Home Assistant laufen (nur aiohttp + pytest nötig).
Es wird nie ein echter Controller angesprochen.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET

import pytest

_PKG = Path(__file__).resolve().parents[1] / "custom_components" / "hid_edge_solo"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"hid_test_{name}", _PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


api = _load("api")
access = _load("access")

NS = 'xmlns:hid="http://www.hidcorp.com/VertX"'


class _Resp:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode()

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Beantwortet Anfragen über eine Funktion (inneres XML -> Antwort-XML)."""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.requests: list[ET.Element] = []

    def get(self, url, params, auth):
        # Die Integration sendet hid:-Elemente ohne xmlns-Deklaration (das
        # akzeptiert der Controller); für den Test-Parser ergänzen.
        xml = params["XML"].replace("<VertXMessage>", f"<VertXMessage {NS}>", 1)
        req = ET.fromstring(xml)
        self.requests.append(req)
        status, body = self.handler(req)
        return _Resp(status, body)


def _client(handler) -> tuple[object, FakeSession]:
    session = FakeSession(handler)
    return api.EdgeSoloClient(session, "192.0.2.1", "user", "pw"), session


def _cardholder_xml(i: int, *, end: str | None = None) -> str:
    end_attr = f' endTime="{end}"' if end else ""
    return (
        f'<hid:Cardholder cardholderID="{i}" forename="Vor{i}" surname="Nach{i:04d}">'
        f'<hid:RoleSet roleSetID="{i}"><hid:Roles>'
        f'<hid:Role roleID="{i}" scheduleID="1" scheduleName="Immer" resourceID="0"/>'
        "</hid:Roles></hid:RoleSet>"
        f'<hid:Credentials><hid:Credential isCard="true" cardNumber="SECRET{i}"{end_attr}/>'
        "</hid:Credentials></hid:Cardholder>"
    )


def _list_handler(total: int, *, cap: int | None = None, more_attr: str = "standard",
                  ignore_offset: bool = False):
    """Simuliert action="LR" für Cardholders.

    cap: Controller kürzt recordCount selbst auf diesen Wert.
    more_attr: "standard" = moreRecords korrekt, "missing" = Attribut fehlt.
    """
    ids = list(range(1, total + 1))

    def handler(req: ET.Element):
        el = req[0]
        offset = 0 if ignore_offset else int(el.get("recordOffset", "0"))
        count = int(el.get("recordCount", "50"))
        if cap is not None:
            count = min(count, cap)
        chunk = ids[offset : offset + count]
        more = offset + len(chunk) < total
        more_xml = f' moreRecords="{str(more).lower()}"' if more_attr == "standard" else ""
        body = (
            f'<VertXMessage {NS}><hid:Cardholders action="RL" recordOffset="{offset}" '
            f'recordCount="{len(chunk)}"{more_xml}>'
            + "".join(_cardholder_xml(i) for i in chunk)
            + "</hid:Cardholders></VertXMessage>"
        )
        return 200, body

    return handler


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------- Paginierung


@pytest.mark.parametrize("total", [0, 1, 49, 50, 51, 237, 2500])
def test_pagination_complete(total):
    client, session = _client(_list_handler(total))
    result = run(client.get_cardholders())
    assert result.complete
    assert len(result.people) == total
    assert len({p["id"] for p in result.people}) == total


def test_pagination_beyond_old_limit_of_2000():
    """Früher brach die Schleife nach 40 Seiten (2000 Personen) still ab."""
    client, _ = _client(_list_handler(2001))
    result = run(client.get_cardholders())
    assert len(result.people) == 2001 and result.complete


def test_pagination_without_more_records_attribute():
    """Fehlt moreRecords, muss trotzdem weitergeblättert werden."""
    client, session = _client(_list_handler(120, more_attr="missing"))
    result = run(client.get_cardholders())
    assert len(result.people) == 120
    assert result.complete
    # 3 volle/teilweise Seiten + 1 leere Seite als Endekennung
    assert result.requests == 4


def test_pagination_controller_caps_page_size():
    """Controller liefert weniger als angefordert, auch ohne moreRecords."""
    client, _ = _client(_list_handler(75, cap=10, more_attr="missing"))
    result = run(client.get_cardholders())
    assert len(result.people) == 75 and result.complete


def test_pagination_offset_ignored_stops_and_flags_incomplete():
    client, session = _client(_list_handler(120, ignore_offset=True))
    result = run(client.get_cardholders())
    assert not result.complete
    assert len(result.people) == 50
    assert len(session.requests) == 2


def test_pagination_offsets_are_sequential():
    client, session = _client(_list_handler(130))
    run(client.get_cardholders())
    offsets = [int(r[0].get("recordOffset")) for r in session.requests]
    assert offsets == [0, 50, 100]


def test_error_response_raises_instead_of_empty_list():
    """<hid:Error> mitten im Blättern darf keine verkürzte Liste ergeben."""
    good = _list_handler(200)

    def handler(req):
        if int(req[0].get("recordOffset")) >= 100:
            return 200, (
                f'<VertXMessage {NS}><hid:Error action="RE" elementType="hid:Cardholders" '
                'errorCode="12" errorReporter="vertx" errorMessage="busy"/></VertXMessage>'
            )
        return good(req)

    client, _ = _client(handler)
    with pytest.raises(api.EdgeSoloResponseError) as exc:
        run(client.get_cardholders())
    assert exc.value.code == "12"


def test_auth_error():
    client, _ = _client(lambda req: (401, ""))
    with pytest.raises(api.EdgeSoloAuthError):
        run(client.get_cardholders())


def test_no_card_numbers_in_result():
    client, _ = _client(_list_handler(3))
    result = run(client.get_cardholders())
    assert "SECRET" not in repr(result.people)
    person = result.people[0]
    assert person["zeitplan"] == "Immer"
    assert person["rollen"][0]["zeitplan_id"] == "1"
    assert len(person["ausweise"]) == 1


# --------------------------------------------------------------- Schreiben


def test_add_cardholder_escapes_names():
    def handler(req):
        return 200, (
            f'<VertXMessage {NS}><hid:Cardholders action="RS">'
            '<hid:Cardholder cardholderID="4711"/></hid:Cardholders></VertXMessage>'
        )

    client, session = _client(handler)
    new_id = run(client.add_cardholder('Ann"e', "Mü<ller> & Co"))
    assert new_id == "4711"
    ch = session.requests[0][0][0]
    assert ch.get("forename") == 'Ann"e'
    assert ch.get("surname") == "Mü<ller> & Co"
    assert session.requests[0][0].get("action") == "AD"


@pytest.mark.parametrize("bad", ["", "   ", "12a", "1 OR 1", '1"/><x a="'])
def test_delete_rejects_invalid_ids_without_request(bad):
    client, session = _client(lambda req: (200, f"<VertXMessage {NS}/>"))
    with pytest.raises(ValueError):
        run(client.delete_cardholder(bad))
    assert session.requests == []


def test_delete_sends_dd():
    client, session = _client(lambda req: (200, f"<VertXMessage {NS}/>"))
    run(client.delete_cardholder("42"))
    el = session.requests[0][0]
    assert el.get("action") == "DD" and el.get("cardholderID") == "42"


def test_write_error_is_raised():
    client, _ = _client(lambda req: (200, (
        f'<VertXMessage {NS}><hid:Error action="RE" errorCode="7" '
        'errorMessage="not found"/></VertXMessage>'
    )))
    with pytest.raises(api.EdgeSoloResponseError):
        run(client.delete_cardholder("42"))


# --------------------------------------------------------------- Status

TZ = UTC
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=TZ)


def _person(roles=None, creds=None):
    return {"rollen": roles if roles is not None else [{}],
            "ausweise": creds if creds is not None else [{}]}


@pytest.mark.parametrize(
    ("creds", "expected"),
    [
        ([{}], access.STATUS_ACTIVE),
        ([{"ende": "2027-01-01T00:00:00"}], access.STATUS_ACTIVE),
        ([{"ende": "2026-11-19T11:59:59"}], access.STATUS_EXPIRED),
        ([{"start": "2026-12-01T00:00:00"}], access.STATUS_PLANNED),
        ([{"ende": "2026-01-01T00:00:00"}, {}], access.STATUS_ACTIVE),
        ([], access.STATUS_NO_CREDENTIAL),
    ],
)
def test_access_status(creds, expected):
    status = access.access_status(
        _person(creds=creds), NOW, TZ, check_roles=True, check_credentials=True
    )
    assert status == expected


def test_access_status_without_role():
    p = _person(roles=[])
    assert access.access_status(p, NOW, TZ, check_roles=True, check_credentials=True) == access.STATUS_NO_SCHEDULE
    assert access.access_status(p, NOW, TZ, check_roles=False, check_credentials=True) == access.STATUS_ACTIVE


def test_naive_device_time_uses_local_tz():
    berlin = datetime.now().astimezone().tzinfo
    parsed = access.parse_device_time("2026-11-19T10:00:00", berlin)
    assert parsed.tzinfo is berlin


# --------------------------------------------------------------- neu


def test_first_load_is_baseline():
    seen, added, removed = access.merge_first_seen(None, ["1", "2"], NOW, remove_missing=True)
    assert seen == {"1": None, "2": None} and added == [] and removed == []


def test_added_and_removed():
    known = {"1": None, "2": "2026-11-01T00:00:00+00:00"}
    seen, added, removed = access.merge_first_seen(known, ["2", "3"], NOW, remove_missing=True)
    assert added == ["3"] and removed == ["1"]
    assert seen["3"] == NOW.isoformat()
    assert seen["2"] == known["2"]


def test_incomplete_list_reports_no_removals():
    known = {"1": None, "2": None}
    seen, added, removed = access.merge_first_seen(known, ["2"], NOW, remove_missing=False)
    assert removed == [] and "1" in seen


def test_is_new_window():
    window = timedelta(days=7)
    assert access.is_new((NOW - timedelta(days=1)).isoformat(), NOW, window)
    assert not access.is_new((NOW - timedelta(days=8)).isoformat(), NOW, window)
    assert not access.is_new(None, NOW, window)
