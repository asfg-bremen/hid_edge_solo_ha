"""Kleiner Client für die VertX-XML-Schnittstelle (vertx_xml.cgi) des HID Edge Solo."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Der Edge Solo schneidet Antworten bei etwa 14 KB ab. 50 Personen im
# Format "expanded" liegen knapp darüber, 20 sicher darunter.
PAGE_SIZE = 20
# Kleinste Seitengröße, auf die nach abgeschnittenen Antworten verkleinert wird
MIN_PAGE_SIZE = 5
# Notbremse gegen Endlosschleifen bei fehlerhaften Antworten. Liegt bei 20
# Datensätzen pro Seite weit über der Kapazität eines Edge Solo.
MAX_REQUESTS = 1000


class EdgeSoloError(Exception):
    """Allgemeiner Kommunikationsfehler."""


class EdgeSoloAuthError(EdgeSoloError):
    """Benutzername oder Passwort falsch."""


class EdgeSoloParseError(EdgeSoloError):
    """Antwort ist kein gültiges XML, meist weil der Controller sie abschneidet."""


class EdgeSoloResponseError(EdgeSoloError):
    """Der Controller hat die Anfrage mit <hid:Error> abgelehnt."""

    def __init__(self, code: str | None, message: str | None, element: str | None) -> None:
        self.code = code
        self.message = message
        self.element = element
        super().__init__(
            f"Controller meldet Fehler {code or '?'}"
            f"{f' ({element})' if element else ''}: {message or 'ohne Text'}"
        )


@dataclass(slots=True)
class CardholderList:
    """Ergebnis einer vollständigen Abfrage der Personenliste."""

    people: list[dict[str, Any]]
    # False, wenn das Blättern vorzeitig abgebrochen wurde (Notbremse oder
    # der Controller ignoriert recordOffset). Die Liste ist dann ein Ausschnitt.
    complete: bool
    requests: int


def _local(tag: str) -> str:
    """Tag-Namen ohne XML-Namespace."""
    return tag.rsplit("}", 1)[-1]


def _find_all(root: ET.Element, name: str) -> list[ET.Element]:
    return [el for el in root.iter() if _local(el.tag) == name]


def _find_first(root: ET.Element, name: str) -> ET.Element | None:
    found = _find_all(root, name)
    return found[0] if found else None


def _check_error(root: ET.Element) -> None:
    """Fehlerantworten (<hid:Error .../>) als Ausnahme melden.

    Ohne diese Prüfung sieht eine abgelehnte Anfrage wie eine leere Antwort aus.
    Beim Blättern hieß das: Abbruch mitten in der Liste, ohne Fehlermeldung.
    """
    for el in [root, *root]:
        if _local(el.tag) == "Error":
            raise EdgeSoloResponseError(
                el.get("errorCode"), el.get("errorMessage"), el.get("elementType")
            )


def _parse_cardholder(ch: ET.Element) -> dict[str, Any]:
    """Eine Person aus dem Format responseFormat="expanded" (ohne Kartennummern)."""
    roles = [
        {
            "rolle_id": role.get("roleID"),
            "zeitplan_id": role.get("scheduleID"),
            "zeitplan": role.get("scheduleName"),
            "start": role.get("startTime"),
            "ende": role.get("endTime"),
        }
        for role in _find_all(ch, "Role")
    ]
    credentials = [
        {
            "karte": cred.get("isCard", "true").lower() != "false",
            "start": cred.get("startTime"),
            "ende": cred.get("endTime"),
        }
        for cred in _find_all(ch, "Credential")
    ]
    return {
        "id": ch.get("cardholderID"),
        "vorname": ch.get("forename", ""),
        "nachname": ch.get("surname", ""),
        # erster Zeitplan, wie bisher als einzelner Wert
        "zeitplan": roles[0]["zeitplan"] if roles else None,
        "rollen": roles,
        "ausweise": credentials,
    }


def _require_id(value: str, what: str) -> str:
    """IDs des Controllers sind Ganzzahlen. Alles andere wird nicht gesendet."""
    value = str(value).strip()
    if not value.isdigit():
        raise ValueError(f"Ungültige {what}: {value!r}")
    return value


def _require_name(value: str, what: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{what} darf nicht leer sein")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{what} enthält Steuerzeichen")
    return value


class EdgeSoloClient:
    """Fragt einen HID Edge Solo per HTTP + Basic-Auth ab."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._url = f"http://{host}/cgi-bin/vertx_xml.cgi"
        self._auth = aiohttp.BasicAuth(username, password)
        # Der Controller verträgt keine parallelen Anfragen gut, und Schreib-
        # zugriffe dürfen nicht mitten in eine laufende Listenabfrage fallen.
        self._lock = asyncio.Lock()

    async def _query(self, inner: str) -> ET.Element:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?><VertXMessage>'
            f"{inner}</VertXMessage>"
        )
        async with self._lock:
            try:
                async with asyncio.timeout(15):
                    async with self._session.get(
                        self._url, params={"XML": xml}, auth=self._auth
                    ) as resp:
                        if resp.status == 401:
                            raise EdgeSoloAuthError("Anmeldung abgelehnt (401)")
                        if resp.status != 200:
                            raise EdgeSoloError(f"HTTP {resp.status}")
                        body = await resp.read()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise EdgeSoloError(f"Controller nicht erreichbar: {err}") from err
        try:
            root = ET.fromstring(body)
        except ET.ParseError as err:
            raise EdgeSoloParseError(f"Ungültige XML-Antwort: {err}") from err
        _check_error(root)
        return root

    # ------------------------------------------------------------------ lesen

    async def get_parameters(self) -> dict[str, str]:
        """Geräteparameter (u. a. doorName, Firmware, Uhrzeit)."""
        root = await self._query('<hid:EdgeSoloParameters action="DR"/>')
        el = _find_first(root, "EdgeSoloParameters")
        return dict(el.attrib) if el is not None else {}

    async def get_door(self) -> dict[str, str]:
        """Tür-/Alarmstatus (relayState, doorForcedAlarmState, ...)."""
        root = await self._query('<hid:Doors action="LR" responseFormat="status"/>')
        el = _find_first(root, "Door")
        return dict(el.attrib) if el is not None else {}

    async def get_events(self, count: int) -> list[dict[str, str]]:
        """Die letzten Ereignisse, neuestes zuerst."""
        # 1. Aufruf liefert nur die aktuelle Position im Ereignisspeicher
        root = await self._query('<hid:EventMessages action="LR" recordCount="1"/>')
        head = _find_first(root, "EventMessages")
        if head is None:
            return []
        marker = head.get("currentRecordMarker")
        stamp = head.get("currentTimestamp")
        if not marker or not stamp:
            return []
        try:
            marker_i, stamp_i = int(marker), int(stamp)
        except ValueError as err:
            raise EdgeSoloError(f"Ungültige Ereignisposition: {err}") from err
        # 2. Aufruf liest ab dieser Position rückwärts
        root = await self._query(
            f'<hid:EventMessages action="LR" recordCount="{int(count)}" '
            f'historyRecordMarker="{marker_i}" historyTimestamp="{stamp_i}"/>'
        )
        return [dict(el.attrib) for el in _find_all(root, "EventMessage")]

    async def get_cardholders(self, page_size: int = PAGE_SIZE) -> CardholderList:
        """Alle Personen, seitenweise geladen.

        Ende der Liste ist erreicht, wenn eine Seite leer ist oder der
        Controller moreRecords="false" bei einer nicht vollen Seite meldet.
        Bei einer vollen Seite wird moreRecords="false" nicht geglaubt: Der
        Edge Solo meldet es auch, wenn weitere Personen folgen. Ein fehlendes
        moreRecords oder eine kürzere Seite (der Controller kürzt recordCount
        teils selbst) beendet das Blättern ebenfalls nicht.

        Schneidet der Controller eine Antwort ab (ungültiges XML), wird dieselbe
        Seite mit halber Größe erneut angefragt. Personen werden über
        cardholderID entdoppelt, falls sich die Liste beim Blättern verschiebt.
        """
        by_id: dict[str, dict[str, Any]] = {}
        offset = 0
        requests = 0
        complete = False
        while requests < MAX_REQUESTS:
            requests += 1
            try:
                root = await self._query(
                    '<hid:Cardholders action="LR" responseFormat="expanded" '
                    f'recordOffset="{offset}" recordCount="{int(page_size)}"/>'
                )
            except EdgeSoloParseError:
                if page_size <= MIN_PAGE_SIZE:
                    raise
                page_size = max(MIN_PAGE_SIZE, page_size // 2)
                _LOGGER.debug(
                    "Personenliste: Antwort ab Offset %s abgeschnitten, "
                    "neuer Versuch mit %s Personen pro Seite",
                    offset,
                    page_size,
                )
                continue
            page = _find_all(root, "Cardholder")
            container = _find_first(root, "Cardholders")
            more = container.get("moreRecords") if container is not None else None

            added = 0
            for index, ch in enumerate(page):
                person = _parse_cardholder(ch)
                key = person["id"] or f"_ohne_id_{offset + index}"
                if key not in by_id:
                    by_id[key] = person
                    added += 1

            if not page:
                complete = True
                break
            if (
                more is not None
                and more.strip().lower() == "false"
                and len(page) < page_size
            ):
                complete = True
                break
            if added == 0:
                _LOGGER.error(
                    "Personenliste: Seite ab Offset %s enthält nur bereits "
                    "bekannte Personen. Der Controller scheint recordOffset zu "
                    "ignorieren, die Liste ist unvollständig (%s Personen)",
                    offset,
                    len(by_id),
                )
                break
            offset += len(page)
        else:
            _LOGGER.error(
                "Personenliste nach %s Anfragen abgebrochen, die Liste ist "
                "unvollständig (%s Personen)",
                requests,
                len(by_id),
            )

        people = sorted(
            by_id.values(),
            key=lambda p: (p["nachname"].lower(), p["vorname"].lower(), p["id"] or ""),
        )
        return CardholderList(people=people, complete=complete, requests=requests)

    # -------------------------------------------------------------- schreiben
    # Achtung: Diese Aufrufe ändern die Zutrittsdaten am Controller.

    async def add_cardholder(self, forename: str, surname: str) -> str:
        """Legt eine Person an und gibt ihre cardholderID zurück."""
        forename = _require_name(forename, "Vorname")
        surname = _require_name(surname, "Nachname")
        root = await self._query(
            '<hid:Cardholders action="AD">'
            f"<hid:Cardholder forename={quoteattr(forename)} "
            f"surname={quoteattr(surname)}/>"
            "</hid:Cardholders>"
        )
        ch = _find_first(root, "Cardholder")
        cardholder_id = ch.get("cardholderID") if ch is not None else None
        if not cardholder_id:
            raise EdgeSoloError(
                "Controller hat keine cardholderID zurückgegeben. Bitte die "
                "Personenliste prüfen, die Person wurde eventuell trotzdem angelegt"
            )
        return cardholder_id

    async def assign_schedule(self, cardholder_id: str, schedule_id: str) -> None:
        """Weist der Person genau einen Zeitplan zu (ersetzt ihr RoleSet)."""
        cardholder_id = _require_id(cardholder_id, "cardholderID")
        schedule_id = _require_id(schedule_id, "scheduleID")
        await self._query(
            f'<hid:RoleSet action="UD" roleSetID="{cardholder_id}">'
            "<hid:Roles>"
            f'<hid:Role roleID="{cardholder_id}" scheduleID="{schedule_id}" '
            'resourceID="0"/>'
            "</hid:Roles></hid:RoleSet>"
        )

    async def delete_cardholder(self, cardholder_id: str) -> None:
        """Löscht eine Person."""
        cardholder_id = _require_id(cardholder_id, "cardholderID")
        await self._query(
            f'<hid:Cardholders action="DD" cardholderID="{cardholder_id}"/>'
        )
