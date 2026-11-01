"""Konstanten für die Lichtsteuerung."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "lichtsteuerung"

# Konfiguration eines Raums
CONF_LIGHTS: Final = "lights"
CONF_PRESENCE_SENSORS: Final = "presence_sensors"
CONF_DARK_SENSOR: Final = "dark_sensor"
CONF_LUX_SENSOR: Final = "lux_sensor"
CONF_LUX_THRESHOLD: Final = "lux_threshold"
CONF_OFF_DELAY: Final = "off_delay"
CONF_DIM_BEFORE_OFF: Final = "dim_before_off"
CONF_NIGHT_START: Final = "night_start"
CONF_NIGHT_END: Final = "night_end"
CONF_TRANSITION: Final = "transition"
CONF_NIGHT_LIGHTS: Final = "night_lights"
CONF_MEDIA_ENTITY: Final = "media_entity"
CONF_SLEEP_ENTITY: Final = "sleep_entity"
CONF_ADAPTIVE: Final = "adaptive"
CONF_HOUSE_MODE_ENTITY: Final = "house_mode_entity"
CONF_AWAY_STATES: Final = "away_states"
CONF_VACATION_STATES: Final = "vacation_states"
CONF_EXTENDED_AFTER: Final = "extended_after"
CONF_EXTENDED_OFF_DELAY: Final = "extended_off_delay"
CONF_OVERRIDE_TIMEOUT: Final = "override_timeout"
CONF_TRIGGER_SENSORS: Final = "trigger_sensors"
CONF_BLOCKER_ENTITIES: Final = "blocker_entities"
CONF_LEARNING: Final = "learning"
CONF_PATH_SENSORS: Final = "path_sensors"
CONF_WELCOME_PERSONS: Final = "welcome_persons"
CONF_BEDTIME: Final = "bedtime"
CONF_WINDDOWN: Final = "winddown"
CONF_LATE_ENTITY: Final = "late_entity"
DEFAULT_WINDDOWN: Final = 20
LATE_MINUTES: Final = 60
WELCOME_MIN_SECONDS: Final = 300
# Blinken: Dauer eines Schritts in Sekunden
FLASH_STEP_SECONDS: Final = 0.7
# Gesundheits-Check
HEALTH_INTERVAL_MINUTES: Final = 10
PRESENCE_STUCK_HOURS: Final = 6
LIGHT_UNAVAILABLE_MINUTES: Final = 60


def conf_scene(phase: str) -> str:
    """Konfigurationsschlüssel für die Szene einer Phase."""
    return f"{phase}_scene"


# Licht pro Tagesphase
PHASE_DAY: Final = "tag"
PHASE_EVENING: Final = "abend"
PHASE_NIGHT: Final = "nacht"
PHASE_TV: Final = "tv"
PHASE_SLEEP: Final = "schlaf"
PHASES: Final = (PHASE_DAY, PHASE_EVENING, PHASE_NIGHT, PHASE_TV, PHASE_SLEEP)
# Phasen, in denen nur die Nachtlichter leuchten
NIGHT_LIGHT_PHASES: Final = (PHASE_NIGHT, PHASE_SLEEP)
# Zustände, bei denen ein Fernseher/Medienplayer als "läuft" gilt
MEDIA_ACTIVE_STATES: Final = ("on", "playing", "paused", "buffering")


def conf_brightness(phase: str) -> str:
    """Konfigurationsschlüssel für die Helligkeit einer Phase."""
    return f"{phase}_brightness"


def conf_kelvin(phase: str) -> str:
    """Konfigurationsschlüssel für die Farbtemperatur einer Phase."""
    return f"{phase}_kelvin"


DEFAULT_LUX_THRESHOLD: Final = 30
DEFAULT_OFF_DELAY: Final = 120
DEFAULT_DIM_BEFORE_OFF: Final = 20
DEFAULT_NIGHT_START: Final = "22:30:00"
DEFAULT_NIGHT_END: Final = "05:30:00"
DEFAULT_TRANSITION: Final = 1
DEFAULT_AWAY_STATES: Final = "Abwesend"
DEFAULT_VACATION_STATES: Final = "Urlaub"
DEFAULT_EXTENDED_AFTER: Final = 0
DEFAULT_EXTENDED_OFF_DELAY: Final = 600
DEFAULT_OVERRIDE_TIMEOUT: Final = 0
# Sonnenhöhe (Grad), ab der die Tag- bzw. Abendwerte voll gelten
ADAPTIVE_ELEVATION_DAY: Final = 15.0
ADAPTIVE_ELEVATION_EVENING: Final = -6.0
ADAPTIVE_INTERVAL_MINUTES: Final = 5
# Lernende Ausschaltzeit: Wiedereinschalten innerhalb dieses Fensters nach
# dem automatischen Aus gilt als Fehlabschaltung.
LEARN_WINDOW_SECONDS: Final = 120
LEARN_STEP: Final = 0.5  # pro Fehlabschaltung + 50 % der Grundverzögerung
LEARN_MAX_FACTOR: Final = 4.0  # höchstens 4-fache Grundverzögerung
LEARN_DECAY: Final = 0.1  # pro korrekter Abschaltung 10 % weniger Zuschlag
# Nachtpfad: so lange bleibt das Licht mindestens an
PATH_MIN_SECONDS: Final = 600
# Anwesenheitssimulation: Minuten an / aus (zufällig im Bereich)
SIM_ON_MINUTES: Final = (15, 45)
SIM_OFF_MINUTES: Final = (10, 40)
DEFAULT_PHASE_SETTINGS: Final = {
    PHASE_DAY: (100, 4000),
    PHASE_EVENING: (70, 2900),
    PHASE_NIGHT: (5, 2200),
    PHASE_TV: (30, 2700),
    PHASE_SLEEP: (2, 2000),
}

# Wie lange nach einem eigenen Befehl Zustandsmeldungen eines Lichts
# noch als "eigene" gelten (Geräte melden oft verzögert oder mehrfach).
OWN_CHANGE_GRACE_SECONDS: Final = 5
# Helligkeit beim Dimmen vor dem Ausschalten (Anteil der aktuellen Helligkeit)
DIM_FACTOR: Final = 0.3

# Raumzustände (Status-Sensor)
STATE_DISABLED: Final = "deaktiviert"
STATE_OFF: Final = "aus"
STATE_ON: Final = "an"
STATE_DIMMED: Final = "gedimmt"
STATE_MANUAL: Final = "manuell"
STATE_AWAY: Final = "abwesend"
STATE_SIMULATION: Final = "simulation"
ROOM_STATES: Final = (
    STATE_DISABLED,
    STATE_OFF,
    STATE_ON,
    STATE_DIMMED,
    STATE_MANUAL,
    STATE_AWAY,
    STATE_SIMULATION,
)

SIGNAL_ROOM_UPDATED: Final = f"{DOMAIN}_room_updated_{{}}"
