"""Raum-Logik der Lichtsteuerung.

Ein RoomController steuert die Lichter eines Raums anhand von Präsenz,
Dunkelheit und Tagesphase. Manuelle Bedienung (Schalter, App, Sprache)
hat immer Vorrang: Sobald jemand ein Licht selbst ändert, hält sich die
Automatik in diesem Raum zurück, bis der Raum leer ist und das Licht
nach der Ausschaltverzögerung aus ist.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging
import random
import time as monotonic_time
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_BRIGHTNESS_PCT,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    ColorMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    ADAPTIVE_ELEVATION_DAY,
    ADAPTIVE_ELEVATION_EVENING,
    ADAPTIVE_INTERVAL_MINUTES,
    CONF_ADAPTIVE,
    CONF_AWAY_STATES,
    CONF_BLOCKER_ENTITIES,
    CONF_EXTENDED_AFTER,
    CONF_EXTENDED_OFF_DELAY,
    CONF_HOUSE_MODE_ENTITY,
    CONF_OVERRIDE_TIMEOUT,
    CONF_TRIGGER_SENSORS,
    CONF_VACATION_STATES,
    DEFAULT_AWAY_STATES,
    DEFAULT_EXTENDED_AFTER,
    DEFAULT_EXTENDED_OFF_DELAY,
    DEFAULT_OVERRIDE_TIMEOUT,
    DEFAULT_VACATION_STATES,
    SIM_OFF_MINUTES,
    SIM_ON_MINUTES,
    STATE_AWAY,
    STATE_SIMULATION,
    conf_scene,
    CONF_DARK_SENSOR,
    CONF_DIM_BEFORE_OFF,
    CONF_LIGHTS,
    CONF_LUX_SENSOR,
    CONF_LUX_THRESHOLD,
    CONF_MEDIA_ENTITY,
    CONF_NIGHT_END,
    CONF_NIGHT_LIGHTS,
    CONF_NIGHT_START,
    CONF_OFF_DELAY,
    CONF_PRESENCE_SENSORS,
    CONF_SLEEP_ENTITY,
    CONF_TRANSITION,
    DEFAULT_DIM_BEFORE_OFF,
    DEFAULT_LUX_THRESHOLD,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_OFF_DELAY,
    DEFAULT_PHASE_SETTINGS,
    DEFAULT_TRANSITION,
    DIM_FACTOR,
    MEDIA_ACTIVE_STATES,
    NIGHT_LIGHT_PHASES,
    OWN_CHANGE_GRACE_SECONDS,
    PHASE_DAY,
    PHASE_EVENING,
    PHASE_NIGHT,
    PHASE_SLEEP,
    PHASE_TV,
    SIGNAL_ROOM_UPDATED,
    STATE_DIMMED,
    STATE_DISABLED,
    STATE_MANUAL,
    STATE_OFF,
    STATE_ON as ROOM_STATE_ON,
    conf_brightness,
    conf_kelvin,
)

_LOGGER = logging.getLogger(__name__)

SUN_ENTITY = "sun.sun"
_NO_COLOR_TEMP_MODES = {ColorMode.ONOFF, ColorMode.BRIGHTNESS, ColorMode.WHITE}


def in_window(now: time, start: time, end: time) -> bool:
    """Liegt `now` im Zeitfenster [start, end)? Fenster über Mitternacht erlaubt."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


class RoomController:
    """Steuert die Lichter eines Raums."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Controller für einen Config-Entry (einen Raum) anlegen."""
        self.hass = hass
        self.entry = entry
        self.config: dict[str, Any] = {**entry.data, **entry.options}

        self._enabled = True
        self._sleep = False
        self._last_action: str | None = None
        self.status_entity_id: str | None = None
        self._override = False
        self._dimmed = False
        self._own_until: dict[str, float] = {}
        self._own_contexts: deque[str] = deque(maxlen=50)
        self._off_timer: CALLBACK_TYPE | None = None
        self._override_timer: CALLBACK_TYPE | None = None
        self._sim_timer: CALLBACK_TYPE | None = None
        self._occupied_since: datetime | None = None
        self._extended = False
        self._unsubs: list[Callable[[], None]] = []

    # ------------------------------------------------------------------
    # Konfiguration
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        """Name des Raums."""
        return self.entry.title

    @property
    def lights(self) -> list[str]:
        """Gesteuerte Lichter."""
        return list(self.config.get(CONF_LIGHTS, []))

    @property
    def night_lights(self) -> list[str]:
        """Lichter für Nacht und Schlaf. Ohne Auswahl: alle Lichter."""
        chosen = [e for e in self.config.get(CONF_NIGHT_LIGHTS) or [] if e in self.lights]
        return chosen or self.lights

    @property
    def presence_sensors(self) -> list[str]:
        """Präsenz- und Bewegungsmelder."""
        return list(self.config.get(CONF_PRESENCE_SENSORS, []))

    @property
    def trigger_sensors(self) -> list[str]:
        """Vorab-Auslöser wie Türkontakte: schalten an, zählen aber nicht als belegt."""
        return list(self.config.get(CONF_TRIGGER_SENSORS) or [])

    @property
    def blocker_entities(self) -> list[str]:
        """Solange eine davon an ist, geht das Licht nicht aus."""
        return list(self.config.get(CONF_BLOCKER_ENTITIES) or [])

    def _time(self, key: str, default: str) -> time:
        value = self.config.get(key) or default
        parsed = dt_util.parse_time(value)
        return parsed if parsed is not None else dt_util.parse_time(default)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    @callback
    def async_start(self) -> None:
        """Auf Zustandsänderungen und Zeitpunkte hören."""
        hass = self.hass

        self._unsubs.append(
            async_track_state_change_event(
                hass,
                self.presence_sensors + self.blocker_entities,
                self._handle_presence_event,
            )
        )
        if self.trigger_sensors:
            self._unsubs.append(
                async_track_state_change_event(
                    hass, self.trigger_sensors, self._handle_trigger_event
                )
            )
        if self.config.get(CONF_HOUSE_MODE_ENTITY):
            self._unsubs.append(
                async_track_state_change_event(
                    hass,
                    [self.config[CONF_HOUSE_MODE_ENTITY]],
                    self._handle_house_mode_event,
                )
            )
        if self.config.get(CONF_ADAPTIVE):
            self._unsubs.append(
                async_track_time_interval(
                    hass,
                    self._handle_adaptive_tick,
                    timedelta(minutes=ADAPTIVE_INTERVAL_MINUTES),
                )
            )
        self._unsubs.append(
            async_track_state_change_event(hass, self.lights, self._handle_light_event)
        )

        mode_entities = [
            e
            for e in (
                self.config.get(CONF_MEDIA_ENTITY),
                self.config.get(CONF_SLEEP_ENTITY),
            )
            if e
        ]
        if mode_entities:
            self._unsubs.append(
                async_track_state_change_event(
                    hass, mode_entities, self._handle_mode_event
                )
            )

        darkness_entities = [
            e
            for e in (
                self.config.get(CONF_DARK_SENSOR),
                self.config.get(CONF_LUX_SENSOR),
            )
            if e
        ]
        darkness_entities.append(SUN_ENTITY)
        self._unsubs.append(
            async_track_state_change_event(
                hass, darkness_entities, self._handle_darkness_event
            )
        )

        for key, default in (
            (CONF_NIGHT_START, DEFAULT_NIGHT_START),
            (CONF_NIGHT_END, DEFAULT_NIGHT_END),
        ):
            t = self._time(key, default)
            self._unsubs.append(
                async_track_time_change(
                    hass,
                    self._handle_phase_change,
                    hour=t.hour,
                    minute=t.minute,
                    second=t.second,
                )
            )

        if self.vacation():
            self._start_simulation()

    @callback
    def async_stop(self) -> None:
        """Alle Listener und Timer entfernen."""
        self._cancel_off_timer()
        self._cancel_override_timer()
        self._stop_simulation()
        while self._unsubs:
            self._unsubs.pop()()

    # ------------------------------------------------------------------
    # Zustand
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        """Ist die Automatik für diesen Raum aktiv?"""
        return self._enabled

    @property
    def override(self) -> bool:
        """Wurde das Licht manuell bedient?"""
        return self._override

    def occupied(self) -> bool:
        """Ist jemand im Raum? Fernseher und Blocker zählen als anwesend."""
        return (
            self.tv_active()
            or any(
                (s := self.hass.states.get(e)) is not None and s.state == STATE_ON
                for e in self.presence_sensors
            )
            or any(
                (s := self.hass.states.get(e)) is not None
                and s.state in MEDIA_ACTIVE_STATES
                for e in self.blocker_entities
            )
        )

    def _house_mode_in(self, key: str, default: str) -> bool:
        entity = self.config.get(CONF_HOUSE_MODE_ENTITY)
        if not entity:
            return False
        state = self.hass.states.get(entity)
        if state is None:
            return False
        wanted = {
            v.strip().casefold()
            for v in str(self.config.get(key, default) or "").split(",")
            if v.strip()
        }
        return state.state.strip().casefold() in wanted

    def away(self) -> bool:
        """Hausmodus steht auf abwesend (ohne Simulation)."""
        return self._house_mode_in(CONF_AWAY_STATES, DEFAULT_AWAY_STATES)

    def vacation(self) -> bool:
        """Hausmodus steht auf Urlaub: Anwesenheitssimulation."""
        return self._house_mode_in(CONF_VACATION_STATES, DEFAULT_VACATION_STATES)

    def tv_active(self) -> bool:
        """Läuft der Fernseher bzw. der Medienplayer?"""
        media = self.config.get(CONF_MEDIA_ENTITY)
        if not media:
            return False
        state = self.hass.states.get(media)
        return state is not None and state.state in MEDIA_ACTIVE_STATES

    def sleep_active(self) -> bool:
        """Ist der Schlafmodus an (Schalter des Raums oder externe Entität)?"""
        if self._sleep:
            return True
        entity = self.config.get(CONF_SLEEP_ENTITY)
        if not entity:
            return False
        state = self.hass.states.get(entity)
        return state is not None and state.state == STATE_ON

    @property
    def sleep(self) -> bool:
        """Zustand des Schlafmodus-Schalters."""
        return self._sleep

    def any_light_on(self) -> bool:
        """Ist mindestens ein Licht an?"""
        return any(
            (s := self.hass.states.get(e)) is not None and s.state == STATE_ON
            for e in self.lights
        )

    def is_dark(self) -> bool:
        """Ist es dunkel genug für Licht?

        Dunkel ist es, wenn der Dunkel-Sensor an ist oder der Lux-Sensor
        im Raum unter dem Schwellwert liegt. Ist keins von beiden
        eingerichtet, zählt der Sonnenstand.
        """
        dark_sensor = self.config.get(CONF_DARK_SENSOR)
        lux_sensor = self.config.get(CONF_LUX_SENSOR)

        if not dark_sensor and not lux_sensor:
            sun = self.hass.states.get(SUN_ENTITY)
            return sun is None or sun.state != "above_horizon"

        if dark_sensor:
            state = self.hass.states.get(dark_sensor)
            if state is not None and state.state == STATE_ON:
                return True

        if lux_sensor:
            state = self.hass.states.get(lux_sensor)
            if state is not None and state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                try:
                    lux = float(state.state)
                except ValueError:
                    return False
                threshold = float(
                    self.config.get(CONF_LUX_THRESHOLD, DEFAULT_LUX_THRESHOLD)
                )
                return lux < threshold

        return False

    def phase(self) -> str:
        """Aktiver Lichtmodus: Schlaf vor TV vor Nacht vor Abend/Tag."""
        if self.sleep_active():
            return PHASE_SLEEP
        if self.tv_active():
            return PHASE_TV
        return self.time_phase()

    def time_phase(self) -> str:
        """Tagesphase: Nacht im Nachtfenster, sonst Abend oder Tag nach Sonne."""
        now = dt_util.now().time()
        start = self._time(CONF_NIGHT_START, DEFAULT_NIGHT_START)
        end = self._time(CONF_NIGHT_END, DEFAULT_NIGHT_END)
        if in_window(now, start, end):
            return PHASE_NIGHT
        sun = self.hass.states.get(SUN_ENTITY)
        if sun is not None and sun.state == "above_horizon":
            return PHASE_DAY
        return PHASE_EVENING

    def room_state(self) -> str:
        """Zustand für den Status-Sensor."""
        if not self._enabled:
            return STATE_DISABLED
        if self.vacation():
            return STATE_SIMULATION
        if self.away():
            return STATE_AWAY
        if self._override:
            return STATE_MANUAL
        if self._dimmed:
            return STATE_DIMMED
        if self.any_light_on():
            return ROOM_STATE_ON
        return STATE_OFF

    def attributes(self) -> dict[str, Any]:
        """Zusatzinfos für den Status-Sensor."""
        return {
            "modus": self.phase(),
            "tagesphase": self.time_phase(),
            "schlafmodus": self.sleep_active(),
            "tv": self.tv_active(),
            "letzte_aktion": self._last_action,
            "anwesend": self.occupied(),
            "dunkel": self.is_dark(),
            "manuell": self._override,
            "ausschalt_timer_aktiv": self._off_timer is not None,
            "laenger_anwesend": self._is_extended(),
        }

    @callback
    def async_set_sleep(self, sleep: bool) -> None:
        """Schlafmodus des Raums ein- oder ausschalten."""
        if self._sleep == sleep:
            return
        self._sleep = sleep
        self._mode_changed()

    @callback
    def async_set_enabled(self, enabled: bool) -> None:
        """Automatik ein- oder ausschalten."""
        self._enabled = enabled
        self._set_override(False)
        self._dimmed = False
        self._cancel_off_timer()
        self._stop_simulation()
        if enabled:
            if self.vacation():
                self._start_simulation()
            self._evaluate()
        self._notify()

    @callback
    def async_reset(self) -> None:
        """Manuellen Modus beenden und neu entscheiden."""
        self._set_override(False)
        self._dimmed = False
        self._cancel_off_timer()
        self._log("Automatik zurückgesetzt")
        if self._enabled:
            self._apply_phase_if_on()
            self._evaluate()
        self._notify()

    # ------------------------------------------------------------------
    # Ereignisse
    # ------------------------------------------------------------------
    @callback
    def _handle_presence_event(self, event: Event[EventStateChangedData]) -> None:
        if not self._enabled or self.away() or self.vacation():
            return
        self._evaluate()
        self._notify()

    @callback
    def _handle_darkness_event(self, event: Event[EventStateChangedData]) -> None:
        if not self._enabled or self.away() or self.vacation():
            return
        entity_id = event.data["entity_id"]
        old: State | None = event.data["old_state"]
        new: State | None = event.data["new_state"]
        if entity_id == SUN_ENTITY and (
            old is None or new is None or old.state == new.state
        ):
            return  # Nur Attribut-Update (Sonnenhöhe), kein Auf-/Untergang

        # Hell geworden (Dunkel-Sensor geht aus): automatisch eingeschaltetes
        # Licht ausschalten. Gilt nur ohne Lux-Sensor im Raum, denn ein
        # dunkler Flur bleibt dunkel, auch wenn draußen die Sonne scheint.
        if (
            entity_id == self.config.get(CONF_DARK_SENSOR)
            and old is not None
            and old.state == STATE_ON
            and new is not None
            and new.state != STATE_ON
            and not self.config.get(CONF_LUX_SENSOR)
            and not self._override
            and self.any_light_on()
        ):
            self._cancel_off_timer()
            self._dimmed = False
            self.hass.async_create_task(self._async_turn_off("aus, weil es hell geworden ist"))
            self._notify()
            return

        if entity_id == SUN_ENTITY:
            self._apply_phase_if_on()

        self._evaluate()
        self._notify()

    @callback
    def _handle_mode_event(self, event: Event[EventStateChangedData]) -> None:
        self._mode_changed()

    @callback
    def _handle_trigger_event(self, event: Event[EventStateChangedData]) -> None:
        new: State | None = event.data["new_state"]
        old: State | None = event.data["old_state"]
        if new is None or new.state != STATE_ON or (old is not None and old.state == STATE_ON):
            return
        if not self._enabled or self.away() or self.vacation() or self._override:
            return
        if self._dimmed or (not self.any_light_on() and self.is_dark()):
            self._dimmed = False
            self.hass.async_create_task(
                self._async_turn_on("an, weil ein Vorab-Auslöser (z. B. Tür) aktiv wurde")
            )
            if not self.occupied():
                self._start_off_timer()
            self._notify()

    @callback
    def _handle_house_mode_event(self, event: Event[EventStateChangedData]) -> None:
        if not self._enabled:
            return
        self._stop_simulation()
        self._cancel_off_timer()
        self._set_override(False)
        self._dimmed = False
        if self.vacation():
            self._log("Urlaub: Anwesenheitssimulation gestartet")
            self._start_simulation()
        elif self.away():
            if self.any_light_on():
                self.hass.async_create_task(
                    self._async_turn_off("aus, weil niemand zu Hause ist")
                )
        else:
            if self.any_light_on() and not self.occupied():
                self.hass.async_create_task(
                    self._async_turn_off("aus, Simulation beendet")
                )
            self._evaluate()
        self._notify()

    @callback
    def _handle_adaptive_tick(self, now: Any) -> None:
        if (
            self._enabled
            and not self.away()
            and not self.vacation()
            and self.phase() in (PHASE_DAY, PHASE_EVENING)
        ):
            self._apply_phase_if_on(log=False)

    @callback
    def _mode_changed(self) -> None:
        """TV oder Schlafmodus hat sich geändert."""
        if self._enabled and not self.away() and not self.vacation():
            self._apply_phase_if_on()
            self._evaluate()
        self._notify()

    @callback
    def _handle_phase_change(self, now: Any) -> None:
        if not self._enabled or self.away() or self.vacation():
            return
        self._apply_phase_if_on()
        self._notify()

    @callback
    def _handle_light_event(self, event: Event[EventStateChangedData]) -> None:
        old: State | None = event.data["old_state"]
        new: State | None = event.data["new_state"]
        if old is None or new is None:
            return
        if new.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) or old.state in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            return
        if self._is_own_change(event.data["entity_id"], new):
            self._notify()
            return
        if not _meaningful_change(old, new):
            return

        _LOGGER.debug(
            "%s: manuelle Änderung an %s erkannt", self.name, event.data["entity_id"]
        )
        if self._enabled and not self.vacation():
            if not self._override:
                self._log(f"manuell bedient ({event.data['entity_id']}), Automatik pausiert")
            self._set_override(True)
            self._dimmed = False
            self._cancel_off_timer()
            if not self.occupied():
                # Raum ist leer: trotzdem nach der Verzögerung aufräumen,
                # damit der manuelle Modus nicht ewig hängen bleibt.
                self._start_off_timer()
        self._notify()

    # ------------------------------------------------------------------
    # Entscheidungslogik
    # ------------------------------------------------------------------
    @callback
    def _evaluate(self) -> None:
        """Licht passend zu Präsenz und Dunkelheit schalten."""
        if self.away() or self.vacation():
            return
        if self.occupied():
            if self._occupied_since is None:
                self._occupied_since = dt_util.utcnow()
                self._extended = False
            self._cancel_off_timer()
            if self._dimmed:
                self._dimmed = False
                self.hass.async_create_task(
                    self._async_turn_on("wieder hell, weil jemand zurückgekommen ist")
                )
                return
            if self._override:
                return
            if not self.any_light_on() and self.is_dark():
                reason = "Fernseher läuft" if self.tv_active() else "Anwesenheit erkannt"
                self.hass.async_create_task(
                    self._async_turn_on(f"an, weil {reason} und es dunkel ist")
                )
            return

        # Raum ist leer
        if self._occupied_since is not None:
            self._extended = self._is_extended()
            self._occupied_since = None
        if self._off_timer is None and (self.any_light_on() or self._override):
            self._start_off_timer()

    def _is_extended(self) -> bool:
        """War bzw. ist jemand länger als die eingestellte Zeit im Raum?"""
        minutes = float(self.config.get(CONF_EXTENDED_AFTER, DEFAULT_EXTENDED_AFTER) or 0)
        if minutes <= 0:
            return False
        if self._occupied_since is None:
            return self._extended
        return dt_util.utcnow() - self._occupied_since >= timedelta(minutes=minutes)

    @callback
    def _apply_phase_if_on(self, log: bool = True) -> None:
        if self._override or self._dimmed or not self.any_light_on():
            return
        self.hass.async_create_task(
            self._async_turn_on(
                f"angepasst an Modus {self.phase()}" if log else None
            )
        )

    @callback
    def _set_override(self, value: bool) -> None:
        self._override = value
        self._cancel_override_timer()
        minutes = float(self.config.get(CONF_OVERRIDE_TIMEOUT, DEFAULT_OVERRIDE_TIMEOUT) or 0)
        if value and minutes > 0:
            self._override_timer = async_call_later(
                self.hass, minutes * 60, self._handle_override_timeout
            )

    @callback
    def _cancel_override_timer(self) -> None:
        if self._override_timer is not None:
            self._override_timer()
            self._override_timer = None

    @callback
    def _handle_override_timeout(self, _now: Any) -> None:
        self._override_timer = None
        if not self._override:
            return
        self._override = False
        self._log("manueller Modus abgelaufen, Automatik übernimmt wieder")
        self._apply_phase_if_on(log=False)
        self._evaluate()
        self._notify()

    @callback
    def _start_off_timer(self) -> None:
        self._cancel_off_timer()
        delay = float(self.config.get(CONF_OFF_DELAY, DEFAULT_OFF_DELAY))
        if self._extended:
            delay = max(
                delay,
                float(self.config.get(CONF_EXTENDED_OFF_DELAY, DEFAULT_EXTENDED_OFF_DELAY)),
            )
        self._off_timer = async_call_later(self.hass, delay, self._handle_off_timer)

    @callback
    def _cancel_off_timer(self) -> None:
        if self._off_timer is not None:
            self._off_timer()
            self._off_timer = None

    @callback
    def _handle_off_timer(self, _now: Any) -> None:
        self._off_timer = None
        if not self._enabled or self.occupied():
            return

        dim_seconds = float(self.config.get(CONF_DIM_BEFORE_OFF, DEFAULT_DIM_BEFORE_OFF))
        if not self._dimmed and dim_seconds > 0 and self.any_light_on():
            self._dimmed = True
            self._set_override(False)
            self.hass.async_create_task(self._async_dim())
            self._off_timer = async_call_later(
                self.hass, dim_seconds, self._handle_off_timer
            )
            self._notify()
            return

        self._dimmed = False
        self._set_override(False)
        self._extended = False
        if self.any_light_on():
            self.hass.async_create_task(
                self._async_turn_off("aus, weil der Raum leer ist")
            )
        self._notify()

    # ------------------------------------------------------------------
    # Anwesenheitssimulation (Hausmodus Urlaub)
    # ------------------------------------------------------------------
    @callback
    def _start_simulation(self) -> None:
        self._stop_simulation()
        self._sim_timer = async_call_later(
            self.hass, random.uniform(60, 600), self._handle_sim_step
        )

    @callback
    def _stop_simulation(self) -> None:
        if self._sim_timer is not None:
            self._sim_timer()
            self._sim_timer = None

    @callback
    def _handle_sim_step(self, _now: Any) -> None:
        self._sim_timer = None
        if not self._enabled or not self.vacation():
            return
        evening = self.is_dark() and self.time_phase() == PHASE_EVENING
        if self.any_light_on():
            self.hass.async_create_task(self._async_turn_off("Simulation: aus"))
            wait = random.uniform(*SIM_OFF_MINUTES) if evening else 10
        elif evening:
            self.hass.async_create_task(self._async_turn_on("Simulation: an"))
            wait = random.uniform(*SIM_ON_MINUTES)
        else:
            wait = 10
        self._sim_timer = async_call_later(self.hass, wait * 60, self._handle_sim_step)
        self._notify()

    # ------------------------------------------------------------------
    # Schalten
    # ------------------------------------------------------------------
    def _new_context(self, entity_ids: list[str]) -> Context:
        context = Context()
        self._own_contexts.append(context.id)
        until = monotonic_time.monotonic() + OWN_CHANGE_GRACE_SECONDS
        for entity_id in entity_ids:
            self._own_until[entity_id] = until
        return context

    def _is_own_change(self, entity_id: str, new: State) -> bool:
        if new.context.id in self._own_contexts:
            return True
        return monotonic_time.monotonic() < self._own_until.get(entity_id, 0)

    def _phase_values(self, phase: str) -> tuple[int, int]:
        default_brightness, default_kelvin = DEFAULT_PHASE_SETTINGS[phase]
        return (
            int(self.config.get(conf_brightness(phase), default_brightness)),
            int(self.config.get(conf_kelvin(phase), default_kelvin)),
        )

    def target_values(self, phase: str) -> tuple[int, int]:
        """Helligkeit und Farbtemperatur, bei Tag/Abend optional fließend nach Sonne."""
        if not self.config.get(CONF_ADAPTIVE) or phase not in (PHASE_DAY, PHASE_EVENING):
            return self._phase_values(phase)
        sun = self.hass.states.get(SUN_ENTITY)
        elevation = sun.attributes.get("elevation") if sun else None
        if elevation is None:
            return self._phase_values(phase)
        day_b, day_k = self._phase_values(PHASE_DAY)
        eve_b, eve_k = self._phase_values(PHASE_EVENING)
        span = ADAPTIVE_ELEVATION_DAY - ADAPTIVE_ELEVATION_EVENING
        f = min(1.0, max(0.0, (float(elevation) - ADAPTIVE_ELEVATION_EVENING) / span))
        return (round(eve_b + (day_b - eve_b) * f), round(eve_k + (day_k - eve_k) * f))

    def _light_on_data(self, entity_id: str, phase: str) -> dict[str, Any]:
        brightness, kelvin = self.target_values(phase)

        data: dict[str, Any] = {
            ATTR_TRANSITION: float(self.config.get(CONF_TRANSITION, DEFAULT_TRANSITION))
        }
        state = self.hass.states.get(entity_id)
        modes = set(state.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or []) if state else set()
        if modes and modes != {ColorMode.ONOFF}:
            data[ATTR_BRIGHTNESS_PCT] = brightness
        if modes - _NO_COLOR_TEMP_MODES:
            data[ATTR_COLOR_TEMP_KELVIN] = kelvin
        return data

    async def _async_turn_on(self, reason: str | None) -> None:
        phase = self.phase()
        scene = self.config.get(conf_scene(phase))
        if scene:
            context = self._new_context(self.lights)
            if reason:
                self._log(f"{reason} ({phase}, Szene)")
            await self.hass.services.async_call(
                "scene",
                "turn_on",
                {
                    ATTR_ENTITY_ID: scene,
                    ATTR_TRANSITION: float(
                        self.config.get(CONF_TRANSITION, DEFAULT_TRANSITION)
                    ),
                },
                blocking=False,
                context=context,
            )
            return
        targets = self.night_lights if phase in NIGHT_LIGHT_PHASES else self.lights
        others = [
            e
            for e in self.lights
            if e not in targets
            and (s := self.hass.states.get(e)) is not None
            and s.state == STATE_ON
        ]
        context = self._new_context(self.lights)
        if reason:
            self._log(f"{reason} ({phase})")
        for entity_id in targets:
            await self.hass.services.async_call(
                "light",
                "turn_on",
                {ATTR_ENTITY_ID: entity_id, **self._light_on_data(entity_id, phase)},
                blocking=False,
                context=context,
            )
        if others:
            await self.hass.services.async_call(
                "light",
                "turn_off",
                {ATTR_ENTITY_ID: others},
                blocking=False,
                context=context,
            )

    async def _async_dim(self) -> None:
        on_lights = [
            e
            for e in self.lights
            if (s := self.hass.states.get(e)) is not None and s.state == STATE_ON
        ]
        context = self._new_context(on_lights)
        self._log("gedimmt, weil der Raum leer ist")
        for entity_id in on_lights:
            state = self.hass.states.get(entity_id)
            brightness = state.attributes.get(ATTR_BRIGHTNESS) if state else None
            if brightness is None:
                continue  # Nur-An/Aus-Licht: bleibt an bis zum Ausschalten
            await self.hass.services.async_call(
                "light",
                "turn_on",
                {
                    ATTR_ENTITY_ID: entity_id,
                    ATTR_BRIGHTNESS: max(1, int(brightness * DIM_FACTOR)),
                    ATTR_TRANSITION: 2,
                },
                blocking=False,
                context=context,
            )

    async def _async_turn_off(self, reason: str) -> None:
        lights = self.lights
        context = self._new_context(lights)
        self._log(reason)
        await self.hass.services.async_call(
            "light",
            "turn_off",
            {
                ATTR_ENTITY_ID: lights,
                ATTR_TRANSITION: float(
                    self.config.get(CONF_TRANSITION, DEFAULT_TRANSITION)
                ),
            },
            blocking=False,
            context=context,
        )

    @callback
    def _log(self, message: str) -> None:
        """Begründung im Status-Attribut und im Logbuch festhalten."""
        self._last_action = message
        _LOGGER.debug("%s: %s", self.name, message)
        if self.status_entity_id and self.hass.services.has_service("logbook", "log"):
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "logbook",
                    "log",
                    {
                        "name": f"Lichtsteuerung {self.name}",
                        "message": message,
                        "entity_id": self.status_entity_id,
                        "domain": "lichtsteuerung",
                    },
                    blocking=False,
                )
            )

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(
            self.hass, SIGNAL_ROOM_UPDATED.format(self.entry.entry_id)
        )


def _meaningful_change(old: State, new: State) -> bool:
    """Hat sich etwas geändert, das ein Mensch ausgelöst haben kann?"""
    if old.state != new.state:
        return True
    if new.state != STATE_ON:
        return False
    for attr in (ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN, "rgb_color", "hs_color"):
        if old.attributes.get(attr) != new.attributes.get(attr):
            return True
    return False
