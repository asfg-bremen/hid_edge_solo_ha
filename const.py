"""Konstanten für die HID-Edge-Solo-Integration."""

from datetime import timedelta

DOMAIN = "hid_edge_solo"

# Wie oft Status und Ereignisse abgefragt werden
SCAN_INTERVAL = timedelta(seconds=30)
# Wie oft die (große) Personenliste neu geladen wird
CARDHOLDER_REFRESH = timedelta(hours=1)
# Anzahl der letzten Zutritte, die als Verlauf angezeigt werden
EVENT_COUNT = 20

# Bekannte Ereignistypen; unbekannte werden als "Ereignis <Code>" angezeigt
EVENT_TYPES: dict[int, str] = {
    2020: "Zutritt gewährt",
}
