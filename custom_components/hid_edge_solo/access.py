"""Auswertung der Personenliste: Freigabestatus und neu hinzugekommene Personen.

Bewusst ohne Home-Assistant-Importe, damit die Logik einzeln testbar ist.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, tzinfo
from typing import Any

STATUS_ACTIVE = "aktiv"
STATUS_PLANNED = "geplant"
STATUS_EXPIRED = "abgelaufen"
STATUS_NO_CREDENTIAL = "kein_ausweis"
STATUS_NO_SCHEDULE = "kein_zeitplan"

ALL_STATUSES = (
    STATUS_ACTIVE,
    STATUS_PLANNED,
    STATUS_EXPIRED,
    STATUS_NO_CREDENTIAL,
    STATUS_NO_SCHEDULE,
)


def parse_device_time(value: str | None, tz: tzinfo) -> datetime | None:
    """Gerätezeit (ISO, meist ohne Zeitzone = Ortszeit des Controllers) lesen."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _window_state(
    items: Iterable[dict[str, Any]], now: datetime, tz: tzinfo
) -> str:
    """Gültigkeit einer Gruppe (Ausweise oder Rollen) zum Zeitpunkt now.

    Gültig ist die Gruppe, sobald ein Eintrag jetzt gültig ist. Ein Eintrag
    ohne Start/Ende gilt unbegrenzt.
    """
    planned = False
    for item in items:
        start = parse_device_time(item.get("start"), tz)
        end = parse_device_time(item.get("ende"), tz)
        if start is not None and start > now:
            planned = True
            continue
        if end is not None and end <= now:
            continue
        return STATUS_ACTIVE
    return STATUS_PLANNED if planned else STATUS_EXPIRED


def access_status(
    person: dict[str, Any],
    now: datetime,
    tz: tzinfo,
    *,
    check_roles: bool,
    check_credentials: bool,
) -> str:
    """Freigabestatus einer Person.

    check_roles/check_credentials schalten die jeweilige Prüfung ab, wenn der
    Controller diese Angaben im Listenformat gar nicht mitliefert. Sonst würde
    jede Person fälschlich als "ohne Ausweis" bzw. "ohne Zeitplan" gelten.
    """
    roles = person.get("rollen") or []
    credentials = person.get("ausweise") or []
    if check_roles and not roles:
        return STATUS_NO_SCHEDULE
    if check_credentials and not credentials:
        return STATUS_NO_CREDENTIAL

    states = []
    if check_roles:
        states.append(_window_state(roles, now, tz))
    if check_credentials:
        states.append(_window_state(credentials, now, tz))
    if STATUS_EXPIRED in states:
        return STATUS_EXPIRED
    if STATUS_PLANNED in states:
        return STATUS_PLANNED
    return STATUS_ACTIVE


def merge_first_seen(
    known: dict[str, str | None] | None,
    current_ids: Iterable[str],
    now: datetime,
    *,
    remove_missing: bool,
    adopt_new: bool = False,
) -> tuple[dict[str, str | None], list[str], list[str]]:
    """Merkt sich, wann eine Person zum ersten Mal in der Liste auftauchte.

    known ist None beim allerersten Laden. Dann gelten alle Personen als
    Bestand (Wert None) und nicht als neu, sonst wäre nach der Installation
    jede Person eine "neue Freigabe".

    remove_missing=False für unvollständig geladene Listen: Wer nur wegen
    eines Abbruchs fehlt, darf nicht als gelöscht gemeldet werden.

    adopt_new=True übernimmt unbekannte Personen als Bestand statt als neu,
    z. B. wenn die Liste früher wegen eines Fehlers zu kurz geladen wurde.

    Rückgabe: (neue Zuordnung, hinzugekommene IDs, entfernte IDs)
    """
    ids = list(dict.fromkeys(current_ids))
    if known is None:
        return {pid: None for pid in ids}, [], []

    stamp = now.isoformat()
    result: dict[str, str | None] = {}
    added: list[str] = []
    for pid in ids:
        if pid in known:
            result[pid] = known[pid]
        elif adopt_new:
            result[pid] = None
        else:
            result[pid] = stamp
            added.append(pid)

    removed: list[str] = []
    current = set(ids)
    for pid, seen in known.items():
        if pid in current:
            continue
        if remove_missing:
            removed.append(pid)
        else:
            result[pid] = seen
    return result, added, removed


def is_new(first_seen: str | None, now: datetime, window: timedelta) -> bool:
    """Neu = erstmals innerhalb des Zeitfensters in der Liste aufgetaucht."""
    if not first_seen:
        return False
    try:
        seen = datetime.fromisoformat(first_seen)
    except ValueError:
        return False
    return now - seen < window
