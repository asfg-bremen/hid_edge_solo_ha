# HID Edge Solo für Home Assistant

Benutzerdefinierte Integration für den Zutrittscontroller **HID Edge Solo**.
Sie fragt den Controller lokal über die VertX-XML-Schnittstelle (`/cgi-bin/vertx_xml.cgi`, HTTP + Basic-Auth) ab.

## Entitäten

| Entität | Typ | Beschreibung |
|---|---|---|
| Schloss | Binärsensor (lock) | an = entriegelt, aus = verriegelt |
| Tür aufgebrochen | Binärsensor (safety) | Alarm „Door Forced“ |
| Tür zu lange offen | Binärsensor (problem) | Alarm „Door Held“ |
| Sabotage | Binärsensor (tamper) | Sabotagealarm |
| Netzstörung, Batterie, Relaisstörung | Binärsensor (Diagnose) | Gerätezustand |
| Letzter Zutritt | Sensor | Name der letzten Person, Verlauf der letzten 20 Ereignisse im Attribut `verlauf` |
| Letzter Zutritt Zeit | Sensor (timestamp) | Zeitpunkt des letzten Ereignisses |
| Zutrittsberechtigte | Sensor | Anzahl der Personen mit **aktuell gültiger** Freigabe, alle Personen mit Status im Attribut `personen` |
| Neue Freigaben | Sensor | Personen, die in den letzten 7 Tagen neu hinzugekommen sind |
| Personenliste aktualisieren | Button (Diagnose) | Lädt die Personenliste sofort neu (nur lesend) |

Status und Ereignisse werden alle 30 Sekunden abgefragt, die Personenliste alle 10 Minuten.
Nach Änderungen über die Dienste dieser Integration wird die Liste sofort neu geladen.

### Personenliste

Die Liste wird seitenweise vollständig geladen. Meldet der Controller einen Fehler
oder lässt sich die Liste nicht vollständig laden, bleibt die zuletzt geladene Liste
erhalten und das Attribut `vollstaendig` bzw. `fehler` zeigt das an.

Attribute von **Zutrittsberechtigte**:

- `gesamt`: alle Personen am Controller
- `anzahl_aktiv`, `anzahl_geplant`, `anzahl_abgelaufen`, `anzahl_kein_ausweis`, `anzahl_kein_zeitplan`
- `vollstaendig`, `stand` (Zeitpunkt der letzten erfolgreichen Abfrage), `fehler`
- `zeitplaene`: in der Liste vorkommende Zeitpläne (`id`, `name`), z. B. für eine Auswahl im Dashboard
- `personen`: je Person `id`, `name`, `status`, `neu`, `zeitplan`, `ausweise` (Anzahl),
  `gueltig_bis` und `erstmals_gesehen`. Kartennummern werden bewusst nicht übernommen.

| Status | Bedeutung |
|---|---|
| `aktiv` | Zeitplan und mindestens ein Ausweis sind jetzt gültig |
| `geplant` | Gültigkeit beginnt erst in der Zukunft |
| `abgelaufen` | alle Ausweise bzw. Rollen sind abgelaufen |
| `kein_ausweis` | Person hat keinen Ausweis |
| `kein_zeitplan` | Person hat keinen Zeitplan bzw. keine Rolle |

`kein_ausweis` und `kein_zeitplan` werden nur vergeben, wenn der Controller Ausweise
bzw. Rollen im Listenformat überhaupt mitliefert.

„Neu“ heißt: Die Person tauchte erstmals innerhalb der letzten 7 Tage in der Liste auf.
Beim allerersten Laden nach der Installation gelten alle Personen als Bestand.

### Ereignisse

- `hid_edge_solo_cardholder_added` mit `config_entry_id`, `cardholder_id`, `name`
- `hid_edge_solo_cardholder_removed`, gleiche Felder

Sie werden nur ausgelöst, wenn die Liste vollständig geladen wurde. Wer wegen eines
Abbruchs fehlt, wird also nicht als gelöscht gemeldet.

## Dienste

> **Achtung:** `add_cardholder` und `delete_cardholder` ändern die Zutrittsdaten am
> Controller. Die XML-Befehle zum Schreiben sind noch nicht an einem Gerät geprüft.
> Bitte zuerst mit einer Testperson ausprobieren.

| Dienst | Felder | Antwort |
|---|---|---|
| `hid_edge_solo.refresh_cardholders` | – | – |
| `hid_edge_solo.add_cardholder` | `forename`, `surname`, optional `schedule_id` | `cardholder_id`, `name` |
| `hid_edge_solo.delete_cardholder` | `cardholder_id` | `cardholder_id`, `name` |

- `config_entry_id` ist nur nötig, wenn mehrere Controller eingerichtet sind.
- `delete_cardholder` löscht nur IDs, die in der zuletzt geladenen Liste stehen.
- `add_cardholder` akzeptiert nur Zeitplan-IDs, die in der Liste vorkommen.
- Ausweise (Kartennummern) lassen sich noch nicht zuweisen.

Beispiel für einen Löschen-Button mit Rückfrage im Dashboard:

```yaml
type: button
name: Person löschen
tap_action:
  action: perform-action
  perform_action: hid_edge_solo.delete_cardholder
  data:
    cardholder_id: "1234"
  confirmation:
    text: Person 1234 wirklich am Controller löschen?
```

## Installation

### Über HACS (empfohlen)

1. In HACS oben rechts auf **⋮ → Benutzerdefinierte Repositories** klicken.
2. Repository `https://github.com/asfg-bremen/hid_edge_solo_ha` mit dem Typ **Integration** hinzufügen.
3. **HID Edge Solo** suchen, herunterladen und Home Assistant neu starten.

### Manuell

Den Ordner `custom_components/hid_edge_solo` nach `<config>/custom_components/hid_edge_solo` kopieren und Home Assistant neu starten.

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → HID Edge Solo**, dann IP-Adresse, Benutzername und Passwort der Weboberfläche des Controllers eingeben.

Hinweis: Die Kommunikation läuft unverschlüsselt per HTTP. Der Controller sollte nur in einem vertrauenswürdigen Netz erreichbar sein.

## Tests

Die Tests simulieren den Controller und senden keine Anfragen an ein Gerät.

```bash
pip install pytest-homeassistant-custom-component
pytest
```

Nur mit `aiohttp` und `pytest` installiert laufen die Tests in `tests/test_api.py`.
Die Integrationstests in `tests/test_init.py` werden dann übersprungen.
