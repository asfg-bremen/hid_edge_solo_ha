"""Kleiner Client für die VertX-XML-Schnittstelle (vertx_xml.cgi) des HID Edge Solo."""

from __future__ import annotations

import asyncio
from typing import Any
import xml.etree.ElementTree as ET

import aiohttp

_PAGE_SIZE = 50
_MAX_PAGES = 40


class EdgeSoloError(Exception):
    """Allgemeiner Kommunikationsfehler."""


class EdgeSoloAuthError(EdgeSoloError):
    """Benutzername oder Passwort falsch."""


def _local(tag: str) -> str:
    """Tag-Namen ohne XML-Namespace."""
    return tag.rsplit("}", 1)[-1]


def _find_all(root: ET.Element, name: str) -> list[ET.Element]:
    return [el for el in root.iter() if _local(el.tag) == name]


def _find_first(root: ET.Element, name: str) -> ET.Element | None:
    found = _find_all(root, name)
    return found[0] if found else None


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

    async def _query(self, inner: str) -> ET.Element:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?><VertXMessage>'
            f"{inner}</VertXMessage>"
        )
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
            return ET.fromstring(body)
        except ET.ParseError as err:
            raise EdgeSoloError(f"Ungültige XML-Antwort: {err}") from err

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
        # 2. Aufruf liest ab dieser Position rückwärts
        root = await self._query(
            f'<hid:EventMessages action="LR" recordCount="{int(count)}" '
            f'historyRecordMarker="{int(marker)}" historyTimestamp="{int(stamp)}"/>'
        )
        return [dict(el.attrib) for el in _find_all(root, "EventMessage")]

    async def get_cardholders(self) -> list[dict[str, Any]]:
        """Alle Personen mit Zutrittsberechtigung (ohne Kartennummern)."""
        people: list[dict[str, Any]] = []
        offset = 0
        for _ in range(_MAX_PAGES):
            root = await self._query(
                '<hid:Cardholders action="LR" responseFormat="expanded" '
                f'recordOffset="{offset}" recordCount="{_PAGE_SIZE}"/>'
            )
            page = _find_all(root, "Cardholder")
            for ch in page:
                role = _find_first(ch, "Role")
                people.append(
                    {
                        "id": ch.get("cardholderID"),
                        "vorname": ch.get("forename", ""),
                        "nachname": ch.get("surname", ""),
                        "zeitplan": role.get("scheduleName") if role is not None else None,
                    }
                )
            container = _find_first(root, "Cardholders")
            more = container is not None and container.get("moreRecords") == "true"
            if not page or not more:
                break
            offset += len(page)
        people.sort(key=lambda p: (p["nachname"].lower(), p["vorname"].lower()))
        return people
