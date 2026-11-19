# HID Edge Solo für Home Assistant

Benutzerdefinierte Integration für den Zutrittscontroller **HID Edge Solo**.
Sie fragt den Controller lokal über die VertX-XML-Schnittstelle (`/cgi-bin/vertx_xml.cgi`, HTTP + Basic-Auth) ab.

## Entitäten

| Entität | Typ | Beschreibung |
|---|---|---|
| Verbindung | Binärsensor (connectivity) | an = Controller antwortet; bleibt bei Ausfall verfügbar und zeigt „getrennt“, Fehler im Attribut `fehler` |
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

Die Liste wird seitenweise (20 Personen pro Anfrage) vollständig geladen. Der
Edge Solo meldet `moreRecords="false"` auch dann, wenn weitere Personen folgen,
und schneidet Antworten ab etwa 14 KB ab. Deshalb wird erst bei einer leeren oder
nicht vollen Seite aufgehört, und nach einer abgeschnittenen Antwort wird dieselbe
Seite mit halber Größe erneut angefragt. Meldet der Controller einen Fehler
oder lässt sich die Liste nicht vollständig laden, bleibt die zuletzt geladene Liste
erhalten und das Attribut `vollstaendig` bzw. `fehler` zeigt das an.

Attribute von **Zutrittsberechtigte**:

- `gesamt`: alle Personen am Controller
- `anzahl_aktiv`, `anzahl_geplant`, `anzahl_abgelaufen`, `anzahl_kein_ausweis`, `anzahl_kein_zeitplan`
- `vollstaendig`, `stand` (Zeitpunkt der letzten erfolgreichen Abfrage), `fehler`
- `config_entry_id`, `controller`: welcher Controller (für die Dashboard-Karten,
  ebenso am Sensor *Letzter Zutritt*)
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
| `hid_edge_solo.get_events` | optional `anzahl` (1–500, Standard 100) | `ereignisse` (je `name`, `zeit`, `ereignis`), `config_entry_id`, `controller` |

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

## Dashboard-Karten

Die Integration bringt zwei Karten mit. Sie werden automatisch geladen, eine
Ressource muss nicht angelegt werden (nach einem Update die Seite neu laden).

### Zutritte

Alle Zutritte der Türen in einer Liste, neueste zuerst.

- **Zeitleiste** der letzten Tage mit Anzahl je Tag; Klick auf einen Tag filtert
  auf diesen Tag, ein zweiter Klick hebt den Filter auf. Schraffierte Tage liegen
  vor dem Beginn der geladenen Daten.
- **Bereiche** (Türen) per Klick ein- und ausblenden, **Personensuche**,
  **Zeitfilter** von/bis; Klick auf einen Namen zeigt nur diese Person.
- Spalten per Klick sortierbar, Standard ist die Zeit (neueste zuerst).
- Die Sensoren *Letzter Zutritt* liefern je Tür die letzten 20 Zutritte. Weiter
  zurück lädt die Karte über den Dienst `get_events` (Option `anzahl`, Standard 200).

```yaml
type: custom:zutritte-card
tage: 14        # Länge der Zeitleiste
anzahl: 200     # je Tür vom Controller nachladen, 0 = nur die letzten 20
bereiche:       # optional, sonst alle Türen
  - entity: sensor.neue_halle_letzter_zutritt
    name: Neue Halle
```

Kompakt, z. B. in einer Übersicht je Tür (`max_zeilen`, Standard 5):

```yaml
type: custom:zutritte-card
kompakt: true
bereiche: [sensor.neue_halle_letzter_zutritt]
```

### Zugangsübersicht

- **eine Zeile je Mitglied, eine Spalte je Zugangssystem** mit Status
  (aktiv, geplant, abgelaufen, kein Ausweis, kein Zeitplan, kein Zugang)
- Kopfzeile je System: aktive/alle Personen, Warnung bei unvollständiger Liste
- Suche und Filter: *Nicht aktiv*, *Nicht überall*, *Neu*
- **Klick auf ein Mitglied** öffnet einen Dialog: Zugang je System **entfernen**
  oder **aus allen Systemen entfernen** (jeweils mit Rückfrage), fehlenden Zugang
  anlegen (optional mit Zeitplan)
- **+ Person** legt eine neue Person an, ↻ lädt alle Listen neu

Personen verschiedener Systeme werden über den Namen zusammengeführt
(Groß-/Kleinschreibung und doppelte Leerzeichen zählen nicht). Schreibende
Schaltflächen sehen nur Administratoren.

Minimal, alle Controller dieser Integration als Spalten:

```yaml
type: custom:zugangs-uebersicht-card
```

Mit festen Spalten und einem weiteren System, das kein HID-Controller ist:

```yaml
type: custom:zugangs-uebersicht-card
titel: Zugänge Mitglieder
spalten:
  - entity: sensor.halle_zutrittsberechtigte
    name: Halle
  - entity: sensor.werkstatt_zutrittsberechtigte
    name: Werkstatt
  # Beliebiger Sensor mit einer Personenliste im Attribut (Texte oder Objekte
  # mit name/id/status). Entfernen ruft hier ein eigenes Skript auf.
  - entity: sensor.schluesseltresor
    name: Schlüsseltresor
    attribut: personen
    entfernen:
      action: script.tresor_zugang_entfernen
      data:
        person: "{name}"
```

| Option | Beschreibung |
|---|---|
| `titel` | Überschrift (Standard „Zugangsübersicht“) |
| `spalten` | Liste von Entitäten oder Objekten; ohne Angabe alle Controller |
| `spalten[].name` | Spaltenname (Standard: Gerätename) |
| `spalten[].attribut` | Attribut mit der Personenliste (Standard `personen`) |
| `spalten[].entfernen` / `hinzufuegen` / `aktualisieren` | eigene Aktion (`action`, `data`) oder `false` zum Abschalten. Platzhalter: `{id}`, `{name}`, `{vorname}`, `{nachname}`, `{zeitplan_id}`, `{config_entry_id}`, `{entity}`. Leere Werte werden weggelassen. |
| `nur_lesen` | `true` blendet alle schreibenden Schaltflächen aus |
| `nur_admins` | `false` zeigt die Schaltflächen auch Nicht-Administratoren |

Für HID-Edge-Solo-Spalten sind Entfernen, Anlegen und Aktualisieren bereits
vorbelegt (`delete_cardholder`, `add_cardholder`, `refresh_cardholders` mit dem
passenden Controller). Ein vollständiges Beispiel-Dashboard liegt in
[`dashboards/zugaenge.yaml`](dashboards/zugaenge.yaml).

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
