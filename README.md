# Lichtsteuerung

Eigene, raumbasierte Lichtautomatik für Home Assistant, installierbar über HACS.
Jeder Raum wird per UI eingerichtet und verhält sich gleich: Licht an bei Präsenz
und Dunkelheit, passend zur Tageszeit, gedimmt als Warnung vor dem Ausschalten.
Manuelle Bedienung hat immer Vorrang.

## Installation über HACS

1. HACS öffnen, oben rechts **⋮ → Benutzerdefinierte Repositories**.
2. Repository `https://github.com/patrickbrundiers-dev/Lichtsteuerung`, Typ **Integration**, hinzufügen.
3. **Lichtsteuerung** in HACS herunterladen und Home Assistant neu starten.
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Lichtsteuerung**. Pro Raum einen Eintrag anlegen.

## So funktioniert ein Raum

| Situation | Verhalten |
| --- | --- |
| Jemand kommt, es ist dunkel | Licht geht mit den Werten der aktuellen Tagesphase an |
| Raum ist leer | Nach der Ausschaltverzögerung wird gedimmt (30 %), nach der Dimmzeit geht das Licht aus |
| Jemand kommt während des Dimmens zurück | Licht wird wieder normal hell |
| Tagesphase wechselt bei brennendem Licht | Helligkeit und Farbtemperatur werden angepasst |
| Dunkel-Sensor meldet „hell“ | Automatisch eingeschaltetes Licht geht aus (nur ohne Lux-Sensor im Raum) |
| Jemand schaltet oder dimmt selbst (Schalter, App, Alexa) | Raum wechselt auf **manuell**: keine automatischen Änderungen, bis der Raum leer war und die Ausschaltverzögerung abgelaufen ist |

**Modi:** In dieser Reihenfolge gilt der erste passende Modus. Für jeden Modus sind Helligkeit und Farbtemperatur einstellbar.

1. *Schlaf*: Schalter „Schlafmodus“ des Raums oder eine eigene Entität (z. B. ein Zeitplan) ist an. Nur die Nachtlichter leuchten.
2. *TV*: Der gewählte Fernseher bzw. Medienplayer läuft. Der Raum gilt dann als belegt, das Licht geht beim Fernsehen also nicht aus.
3. *Nacht*: im eingestellten Nachtfenster (Standard 22:30–05:30). Nur die Nachtlichter leuchten.
4. *Abend*: Die Sonne ist unter dem Horizont.
5. *Tag*: sonst.

**Lichtrollen:** Unter „Nachtlichter“ wählst du die Lichter, die nachts und im Schlafmodus leuchten. Die übrigen werden dann ausgeschaltet. Ohne Auswahl leuchten alle.

**Dunkelheit:** Dunkel ist es, wenn der Dunkel-Sensor an ist (z. B. `binary_sensor.helper_dunkel`) oder ein Lux-Sensor im Raum unter der Schwelle liegt. Ohne beides zählt der Sonnenstand.

## Entitäten pro Raum

- `switch.lichtsteuerung_<raum>_automatik`: Automatik an/aus. Bleibt über Neustarts erhalten.
- `switch.lichtsteuerung_<raum>_schlafmodus`: Schlafmodus an/aus. Bleibt über Neustarts erhalten.
- `sensor.lichtsteuerung_<raum>_status`: `aus`, `an`, `gedimmt`, `manuell` oder `deaktiviert`, mit Attributen für Modus, Tagesphase, Anwesenheit, Dunkelheit und **letzte Aktion**.

Jede Aktion steht mit Begründung im Logbuch, z. B. „an, weil Anwesenheit erkannt und es dunkel ist (abend)“.

## Umstieg von den alten Automationen

Pro Raum: Raum in der Lichtsteuerung anlegen, dann die alte Automation (z. B. „Wohnzimmer Test“) **deaktivieren**, nicht löschen. Läuft alles ein paar Tage, kann die alte Automation weg. „Alle Lichter aus prüfen“ wird überflüssig, sobald alle Räume umgestellt sind.

## Entwicklung

```bash
python -m venv venv && venv/bin/pip install -r requirements_test.txt
venv/bin/pytest
```

## Geplant

- Fließende Farbtemperatur nach Sonnenstand
- Hausmodus (Abwesend, Urlaub mit Anwesenheitssimulation)
- Wecklicht an Schul- und Arbeitstagen
- Taster und Szenen direkt pro Raum
