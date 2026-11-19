"""Konstanten für die HID-Edge-Solo-Integration."""

from datetime import timedelta

DOMAIN = "hid_edge_solo"

# Wie oft Status und Ereignisse abgefragt werden
SCAN_INTERVAL = timedelta(seconds=30)
# Wie oft die Personenliste neu geladen wird. Änderungen über die Dienste
# dieser Integration und der Button "Personenliste aktualisieren" laden sofort.
CARDHOLDER_REFRESH = timedelta(minutes=10)
# Wartezeit bis zum nächsten Versuch, wenn das Laden der Liste fehlschlug
CARDHOLDER_RETRY = timedelta(minutes=2)
# Wie lange eine neu aufgetauchte Person als "neue Freigabe" gilt
NEW_GRANT_WINDOW = timedelta(days=7)
# Anzahl der letzten Zutritte, die als Verlauf angezeigt werden
EVENT_COUNT = 20

# Speicher für "erstmals gesehen" je Person
STORAGE_VERSION = 1

# Ereignisse auf dem HA-Event-Bus
EVENT_CARDHOLDER_ADDED = f"{DOMAIN}_cardholder_added"
EVENT_CARDHOLDER_REMOVED = f"{DOMAIN}_cardholder_removed"

# Bekannte Ereignistypen; unbekannte werden als "Ereignis <Code>" angezeigt
EVENT_TYPES: dict[int, str] = {
    2020: "Zutritt gewährt",
}
