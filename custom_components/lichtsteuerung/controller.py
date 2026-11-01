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
from datetime import time
import logging
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
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DARK_SENSOR,
    CONF_DIM_BEFORE_OFF,
    CONF_LIGHTS,
    CONF_LUX_SENSOR,
    CONF_LUX_THRESHOLD,
    CONF_NIGHT_END,
    CONF_NIGHT_START,
    CONF_OFF_DELAY,
    CONF_PRESENCE_SENSORS,
    CONF_TRANSITION,
    DEFAULT_DIM_BEFORE_OFF,
    DEFAULT_LUX_THRESHOLD,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_OFF_DELAY,
    DEFAULT_PHASE_SETTINGS,
    DEFAULT_TRANSITION,
    DIM_FACTOR,
    OWN_CHANGE_GRACE_SECONDS,
    PHASE_DAY,
    PHASE_EVENING,
    PHASE_NIGHT,
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
        self._override = False
        self._dimmed = False
        self._own_until: dict[str, float] = {}
        self._own_contexts: deque[str] = deque(maxlen=50)
        self._off_timer: CALLBACK_TYPE | None = None
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
    def presence_sensors(self) -> list[str]:
        """Präsenz- und Bewegungsmelder."""
        return list(self.config.get(CONF_PRESENCE_SENSORS, []))

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
                hass, self.presence_sensors, self._handle_presence_event
            )
        )
        self._unsubs.append(
            async_track_state_change_event(hass, self.lights, self._handle_light_event)
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

    @callback
    def async_stop(self) -> None:
        """Alle Listener und Timer entfernen."""
        self._cancel_off_timer()
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
        """Ist jemand im Raum?"""
        return any(
            (s := self.hass.states.get(e)) is not None and s.state == STATE_ON
            for e in self.presence_sensors
        )

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
        """Aktuelle Tagesphase: Nacht im Nachtfenster, sonst Abend oder Tag nach Sonne."""
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
            "tagesphase": self.phase(),
            "anwesend": self.occupied(),
            "dunkel": self.is_dark(),
            "manuell": self._override,
            "ausschalt_timer_aktiv": self._off_timer is not None,
        }

    @callback
    def async_set_enabled(self, enabled: bool) -> None:
        """Automatik ein- oder ausschalten."""
        self._enabled = enabled
        self._override = False
        self._dimmed = False
        self._cancel_off_timer()
        if enabled:
            self._evaluate()
        self._notify()

    # ------------------------------------------------------------------
    # Ereignisse
    # ------------------------------------------------------------------
    @callback
    def _handle_presence_event(self, event: Event[EventStateChangedData]) -> None:
        if not self._enabled:
            return
        self._evaluate()
        self._notify()

    @callback
    def _handle_darkness_event(self, event: Event[EventStateChangedData]) -> None:
        if not self._enabled:
            return
        entity_id = event.data["entity_id"]
        old: State | None = event.data["old_state"]
        new: State | None = event.data["new_state"]

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
            self.hass.async_create_task(self._async_turn_off())
            self._notify()
            return

        if entity_id == SUN_ENTITY:
            self._apply_phase_if_on()

        self._evaluate()
        self._notify()

    @callback
    def _handle_phase_change(self, now: Any) -> None:
        if not self._enabled:
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
        if self._enabled:
            self._override = True
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
        if self.occupied():
            self._cancel_off_timer()
            if self._dimmed:
                self._dimmed = False
                self.hass.async_create_task(self._async_turn_on())
                return
            if self._override:
                return
            if not self.any_light_on() and self.is_dark():
                self.hass.async_create_task(self._async_turn_on())
            return

        # Raum ist leer
        if self._off_timer is None and (self.any_light_on() or self._override):
            self._start_off_timer()

    @callback
    def _apply_phase_if_on(self) -> None:
        if self._override or self._dimmed or not self.any_light_on():
            return
        self.hass.async_create_task(self._async_turn_on())

    @callback
    def _start_off_timer(self) -> None:
        self._cancel_off_timer()
        delay = float(self.config.get(CONF_OFF_DELAY, DEFAULT_OFF_DELAY))
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
            self._override = False
            self.hass.async_create_task(self._async_dim())
            self._off_timer = async_call_later(
                self.hass, dim_seconds, self._handle_off_timer
            )
            self._notify()
            return

        self._dimmed = False
        self._override = False
        if self.any_light_on():
            self.hass.async_create_task(self._async_turn_off())
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

    def _light_on_data(self, entity_id: str) -> dict[str, Any]:
        phase = self.phase()
        default_brightness, default_kelvin = DEFAULT_PHASE_SETTINGS[phase]
        brightness = int(self.config.get(conf_brightness(phase), default_brightness))
        kelvin = int(self.config.get(conf_kelvin(phase), default_kelvin))

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

    async def _async_turn_on(self) -> None:
        lights = self.lights
        context = self._new_context(lights)
        for entity_id in lights:
            await self.hass.services.async_call(
                "light",
                "turn_on",
                {ATTR_ENTITY_ID: entity_id, **self._light_on_data(entity_id)},
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

    async def _async_turn_off(self) -> None:
        lights = self.lights
        context = self._new_context(lights)
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
