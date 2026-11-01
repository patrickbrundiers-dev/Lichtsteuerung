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

## Einstellungen

**Raum anlegen** fragt nur das Nötigste ab: Name, Lichter, Nachtlichter, Melder und Dunkel-Sensor. Alles andere startet mit sinnvollen Standardwerten.

**Konfigurieren** öffnet ein Menü mit Bereichen. Jeder Bereich ist ein kurzes Formular, übernommen wird alles mit **Speichern und schließen**:

| Bereich | Inhalt |
| --- | --- |
| 💡 Lichter und Melder | Lichter, Nachtlichter, Präsenzmelder |
| 🌙 Wann ist es dunkel? | Dunkel-Sensor, Lux-Sensor, Lux-Schwelle |
| ⏱️ Ausschalten und Zeiten | Ausschalt- und Dimmzeit, Lernen, längere Anwesenheit, manueller Modus, Nachtfenster |
| 🎨 Helligkeit, Farbe und Szenen | Fließendes Licht, Übergang, pro Modus aufklappbar: Helligkeit, Farbtemperatur, Szene |
| 📺 Fernsehen und Schlafen | Fernseher, Schlafmodus-Entität, Schlafenszeit, Runterdimmen, später ins Bett |
| 🚪 Weitere Auslöser | Vorab-Auslöser, Nachtpfad, Willkommenslicht, „nicht ausschalten, solange …“ |
| 🏠 Hausmodus | Hausmodus-Entität, Werte für abwesend und Urlaub |

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

**Zusatzfunktionen** (alles optional, über **Konfigurieren**):

| Funktion | Was sie macht |
| --- | --- |
| Fließendes Licht | Zwischen Tag und Abend folgen Helligkeit und Farbtemperatur der Sonnenhöhe (von −6° bis 15°), alle 5 Minuten nachgeführt |
| Szenen pro Modus | Statt Helligkeit/Farbtemperatur wird für Tag, Abend, Nacht, TV oder Schlaf eine eigene Szene aktiviert |
| Vorab-Auslöser | z. B. ein Türkontakt schaltet das Licht schon beim Öffnen ein, zählt aber nicht als Anwesenheit |
| Nicht ausschalten, solange … | Spielkonsole, Lautsprecher, Gäste-Schalter: solange eine davon läuft, bleibt das Licht an |
| Länger anwesend | Wer länger als X Minuten im Raum war, bekommt eine längere Ausschaltverzögerung |
| Manuell spätestens beenden | Der manuelle Modus endet nach X Minuten, auch wenn ein Melder hängt |
| Ausschaltzeit lernen | Standard an. Wird das Licht innerhalb von 2 Minuten nach dem automatischen Aus wieder gebraucht, steigt die Verzögerung des Raums um 50 % (bis zum 4-fachen). Nach richtigen Abschaltungen sinkt der Zuschlag um 10 %. Der Wert überlebt Neustarts |
| Nachtpfad | Bettsensoren wählen: Wird nachts (oder im Schlafmodus) einer frei, gehen die Nachtlichter des Raums an, mindestens 10 Minuten. Ist die Person zurück im Bett, gehen sie aus |
| Hausmodus | Bei „Abwesend“ geht alles aus und bleibt aus. Bei „Urlaub“ läuft abends eine zufällige Anwesenheitssimulation |

**Dunkelheit:** Dunkel ist es, wenn der Dunkel-Sensor an ist (z. B. `binary_sensor.helper_dunkel`) oder ein Lux-Sensor im Raum unter der Schwelle liegt. Ohne beides zählt der Sonnenstand.

## Entitäten pro Raum

- `switch.lichtsteuerung_<raum>_automatik`: Automatik an/aus. Bleibt über Neustarts erhalten.
- `switch.lichtsteuerung_<raum>_schlafmodus`: Schlafmodus an/aus. Bleibt über Neustarts erhalten.
- `button.lichtsteuerung_<raum>_automatik_zurucksetzen`: beendet den manuellen Modus sofort.
- `sensor.lichtsteuerung_<raum>_status`: `aus`, `an`, `gedimmt`, `manuell`, `abwesend`, `simulation` oder `deaktiviert`, mit Attributen für Modus, Tagesphase, Anwesenheit, Dunkelheit und **letzte Aktion**.

Jede Aktion steht mit Begründung im Logbuch, z. B. „an, weil Anwesenheit erkannt und es dunkel ist (abend)“.

## Aktionen für das ganze Haus

| Aktion | Wirkung |
| --- | --- |
| `lichtsteuerung.set_sleep_mode` | Schlafmodus an/aus, z. B. für eine „Gute Nacht“-Routine mit Alexa |
| `lichtsteuerung.reset` | Manuellen Modus beenden |
| `lichtsteuerung.set_enabled` | Automatik an/aus |

Alle drei nehmen optional `rooms` (Raumnamen). Ohne `rooms` gelten sie für alle Räume.

```yaml
action: lichtsteuerung.set_sleep_mode
data:
  sleep: true
```

## Umstieg von den alten Automationen

Pro Raum: Raum in der Lichtsteuerung anlegen, dann die alte Automation (z. B. „Wohnzimmer Test“) **deaktivieren**, nicht löschen. Läuft alles ein paar Tage, kann die alte Automation weg. „Alle Lichter aus prüfen“ wird überflüssig, sobald alle Räume umgestellt sind.

## Entwicklung

```bash
python -m venv venv && venv/bin/pip install -r requirements_test.txt
venv/bin/pytest
```

## Geplant

- Wecklicht an Schul- und Arbeitstagen
- Anwesenheitssimulation nach echtem Verlauf (wie presence_simulation)
- Taster und Szenen direkt pro Raum
