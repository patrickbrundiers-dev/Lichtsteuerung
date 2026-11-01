"""Einrichtung per UI.

Neuer Raum: ein kurzer Schritt mit dem Nötigsten, alles andere hat
sinnvolle Standardwerte. Ändern: ein Menü mit thematischen Bereichen,
jeder Bereich ist ein eigenes, kurzes Formular.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .const import (
    CONF_ADAPTIVE,
    CONF_AWAY_STATES,
    CONF_BEDTIME,
    CONF_BLOCKER_ENTITIES,
    CONF_DARK_SENSOR,
    CONF_DIM_BEFORE_OFF,
    CONF_EXTENDED_AFTER,
    CONF_EXTENDED_OFF_DELAY,
    CONF_HOUSE_MODE_ENTITY,
    CONF_LATE_ENTITY,
    CONF_LEARNING,
    CONF_LIGHTS,
    CONF_LUX_SENSOR,
    CONF_LUX_THRESHOLD,
    CONF_MEDIA_ENTITY,
    CONF_NIGHT_END,
    CONF_NIGHT_LIGHTS,
    CONF_NIGHT_START,
    CONF_OFF_DELAY,
    CONF_OVERRIDE_TIMEOUT,
    CONF_PATH_SENSORS,
    CONF_PRESENCE_SENSORS,
    CONF_SLEEP_ENTITY,
    CONF_TRANSITION,
    CONF_TRIGGER_SENSORS,
    CONF_VACATION_STATES,
    CONF_WELCOME_PERSONS,
    CONF_WINDDOWN,
    DEFAULT_AWAY_STATES,
    DEFAULT_DIM_BEFORE_OFF,
    DEFAULT_EXTENDED_AFTER,
    DEFAULT_EXTENDED_OFF_DELAY,
    DEFAULT_LUX_THRESHOLD,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_OFF_DELAY,
    DEFAULT_OVERRIDE_TIMEOUT,
    DEFAULT_PHASE_SETTINGS,
    DEFAULT_TRANSITION,
    DEFAULT_VACATION_STATES,
    DEFAULT_WINDDOWN,
    DOMAIN,
    PHASES,
    conf_brightness,
    conf_kelvin,
    conf_scene,
)

Fields = dict[Any, Any]

# ----------------------------------------------------------------------
# Bausteine
# ----------------------------------------------------------------------


def _entities(domain: str | list[str], multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domain, multiple=multiple)
    )


def _number(
    minimum: float, maximum: float, step: float, unit: str, box: bool = True
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX
            if box
            else selector.NumberSelectorMode.SLIDER,
        )
    )


def _req(key: str, current: dict[str, Any], default: Any) -> vol.Required:
    return vol.Required(key, default=current.get(key, default))


def _opt(key: str, current: dict[str, Any]) -> vol.Optional:
    """Optionales Feld, das einen vorhandenen Wert vorbelegt und leerbar bleibt."""
    if current.get(key):
        return vol.Optional(key, description={"suggested_value": current[key]})
    return vol.Optional(key)


SECONDS = _number(0, 7200, 5, "s")
MINUTES = _number(0, 1440, 1, "min")

# ----------------------------------------------------------------------
# Bereiche
# ----------------------------------------------------------------------


def _basis(c: dict[str, Any]) -> Fields:
    """Lichter und Melder."""
    return {
        _req(CONF_LIGHTS, c, []): _entities("light", True),
        _opt(CONF_NIGHT_LIGHTS, c): _entities("light", True),
        _req(CONF_PRESENCE_SENSORS, c, []): _entities("binary_sensor", True),
    }


def _darkness(c: dict[str, Any]) -> Fields:
    """Wann ist es dunkel?"""
    return {
        _opt(CONF_DARK_SENSOR, c): _entities("binary_sensor"),
        _opt(CONF_LUX_SENSOR, c): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor", device_class=SensorDeviceClass.ILLUMINANCE
            )
        ),
        _req(CONF_LUX_THRESHOLD, c, DEFAULT_LUX_THRESHOLD): _number(0, 5000, 1, "lx"),
    }


def _timing(c: dict[str, Any]) -> Fields:
    """Ausschalten und Zeiten."""
    return {
        _req(CONF_OFF_DELAY, c, DEFAULT_OFF_DELAY): SECONDS,
        _req(CONF_DIM_BEFORE_OFF, c, DEFAULT_DIM_BEFORE_OFF): SECONDS,
        _req(CONF_LEARNING, c, True): selector.BooleanSelector(),
        _req(CONF_EXTENDED_AFTER, c, DEFAULT_EXTENDED_AFTER): MINUTES,
        _req(CONF_EXTENDED_OFF_DELAY, c, DEFAULT_EXTENDED_OFF_DELAY): SECONDS,
        _req(CONF_OVERRIDE_TIMEOUT, c, DEFAULT_OVERRIDE_TIMEOUT): MINUTES,
        _req(CONF_NIGHT_START, c, DEFAULT_NIGHT_START): selector.TimeSelector(),
        _req(CONF_NIGHT_END, c, DEFAULT_NIGHT_END): selector.TimeSelector(),
    }


def _phase_fields(phase: str, c: dict[str, Any]) -> Fields:
    brightness, kelvin = DEFAULT_PHASE_SETTINGS[phase]
    return {
        _req(conf_brightness(phase), c, brightness): _number(1, 100, 1, "%", box=False),
        _req(conf_kelvin(phase), c, kelvin): _number(2000, 6500, 100, "K", box=False),
        _opt(conf_scene(phase), c): _entities("scene"),
    }


def _light(c: dict[str, Any]) -> Fields:
    """Helligkeit und Farbe, ein aufklappbarer Abschnitt pro Modus."""
    fields: Fields = {
        _req(CONF_ADAPTIVE, c, False): selector.BooleanSelector(),
        _req(CONF_TRANSITION, c, DEFAULT_TRANSITION): _number(0, 10, 0.5, "s", box=False),
    }
    for phase in PHASES:
        fields[vol.Required(phase)] = section(
            vol.Schema(_phase_fields(phase, c)), {"collapsed": True}
        )
    return fields


def _modes(c: dict[str, Any]) -> Fields:
    """Fernsehen und Schlafen."""
    return {
        _opt(CONF_MEDIA_ENTITY, c): _entities(
            ["media_player", "input_boolean", "binary_sensor", "switch"]
        ),
        _opt(CONF_SLEEP_ENTITY, c): _entities(
            ["input_boolean", "binary_sensor", "switch", "schedule"]
        ),
        _opt(CONF_BEDTIME, c): selector.TimeSelector(),
        _req(CONF_WINDDOWN, c, DEFAULT_WINDDOWN): MINUTES,
        _opt(CONF_LATE_ENTITY, c): _entities(["binary_sensor", "input_boolean", "calendar"]),
    }


def _triggers(c: dict[str, Any]) -> Fields:
    """Weitere Auslöser und Sperren."""
    return {
        _opt(CONF_TRIGGER_SENSORS, c): _entities("binary_sensor", True),
        _opt(CONF_PATH_SENSORS, c): _entities("binary_sensor", True),
        _opt(CONF_WELCOME_PERSONS, c): _entities("person", True),
        _opt(CONF_BLOCKER_ENTITIES, c): _entities(
            ["media_player", "binary_sensor", "input_boolean", "switch"], True
        ),
    }


def _house(c: dict[str, Any]) -> Fields:
    """Hausmodus."""
    return {
        _opt(CONF_HOUSE_MODE_ENTITY, c): _entities(["input_select", "select"]),
        _req(CONF_AWAY_STATES, c, DEFAULT_AWAY_STATES): str,
        _req(CONF_VACATION_STATES, c, DEFAULT_VACATION_STATES): str,
    }


AREAS: dict[str, Callable[[dict[str, Any]], Fields]] = {
    "basis": _basis,
    "dunkelheit": _darkness,
    "zeiten": _timing,
    "licht": _light,
    "modi": _modes,
    "ausloeser": _triggers,
    "haus": _house,
}


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    """Abschnitte (verschachtelte dicts) auf flache Schlüssel bringen."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in PHASES and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _keys(fields: Fields) -> set[str]:
    """Alle Konfigurationsschlüssel eines Bereichs, auch in Abschnitten."""
    keys: set[str] = set()
    for marker, value in fields.items():
        if isinstance(value, section):
            keys |= {str(k) for k in value.schema.schema}
        else:
            keys.add(str(marker))
    return keys


def _validate(options: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not options.get(CONF_LIGHTS):
        errors[CONF_LIGHTS] = "no_lights"
    if not options.get(CONF_PRESENCE_SENSORS):
        errors[CONF_PRESENCE_SENSORS] = "no_presence"
    if not set(options.get(CONF_NIGHT_LIGHTS) or []) <= set(options.get(CONF_LIGHTS) or []):
        errors[CONF_NIGHT_LIGHTS] = "night_lights_not_in_room"
    return errors


# ----------------------------------------------------------------------
# Flows
# ----------------------------------------------------------------------


class LichtsteuerungConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einen Raum anlegen: nur das Nötigste."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name, Lichter, Melder und Dunkelheit."""
        errors: dict[str, str] = {}
        current = user_input or {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_NAME].strip().lower())
                self._abort_if_unique_id_configured()
                options = {k: v for k, v in user_input.items() if k != CONF_NAME}
                return self.async_create_entry(
                    title=user_input[CONF_NAME].strip(), data={}, options=options
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=current.get(CONF_NAME, "")): str,
                **_basis(current),
                _opt(CONF_DARK_SENSOR, current): _entities("binary_sensor"),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Einstellungen ändern."""
        return LichtsteuerungOptionsFlow()


class LichtsteuerungOptionsFlow(OptionsFlow):
    """Menü mit Bereichen; jeder Bereich ist ein kurzes Formular."""

    def __init__(self) -> None:
        """Flow-Zustand."""
        self._options: dict[str, Any] | None = None

    @property
    def options(self) -> dict[str, Any]:
        """Arbeitskopie der Optionen."""
        if self._options is None:
            self._options = {**self.config_entry.data, **self.config_entry.options}
        return self._options

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Hauptmenü."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[*AREAS, "speichern"],
            description_placeholders={"room": self.config_entry.title},
        )

    async def async_step_speichern(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Alle Änderungen übernehmen."""
        return self.async_create_entry(data=self.options)

    async def _async_area(
        self, area: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        fields = AREAS[area](self.options)
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {
                k: v for k, v in self.options.items() if k not in _keys(fields)
            }
            candidate.update(_flatten(user_input))
            errors = _validate(candidate)
            if not errors:
                self._options = candidate
                return await self.async_step_init()
            fields = AREAS[area]({**self.options, **_flatten(user_input)})
        return self.async_show_form(
            step_id=area, data_schema=vol.Schema(fields), errors=errors
        )

    async def async_step_basis(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Lichter und Melder."""
        return await self._async_area("basis", user_input)

    async def async_step_dunkelheit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dunkelheit."""
        return await self._async_area("dunkelheit", user_input)

    async def async_step_zeiten(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ausschalten und Zeiten."""
        return await self._async_area("zeiten", user_input)

    async def async_step_licht(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Helligkeit und Farbe."""
        return await self._async_area("licht", user_input)

    async def async_step_modi(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Fernsehen und Schlafen."""
        return await self._async_area("modi", user_input)

    async def async_step_ausloeser(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Weitere Auslöser."""
        return await self._async_area("ausloeser", user_input)

    async def async_step_haus(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Hausmodus."""
        return await self._async_area("haus", user_input)
