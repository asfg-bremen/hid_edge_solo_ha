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
| Zutrittsberechtigte | Sensor | Anzahl der Personen, Liste im Attribut `personen` |

Status und Ereignisse werden alle 30 Sekunden abgefragt, die Personenliste einmal pro Stunde.

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
