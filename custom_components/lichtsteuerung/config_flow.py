"""Einrichtung per UI: ein Eintrag pro Raum."""

from __future__ import annotations

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
from homeassistant.helpers import selector

from .const import (
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
    DOMAIN,
    PHASES,
    conf_brightness,
    conf_kelvin,
)


def _optional(key: str, current: dict[str, Any]) -> vol.Optional:
    """Optionales Feld, das einen vorhandenen Wert vorbelegt."""
    if current.get(key):
        return vol.Optional(key, description={"suggested_value": current[key]})
    return vol.Optional(key)


def _room_schema(current: dict[str, Any]) -> dict[Any, Any]:
    """Felder für Lichter, Sensoren und Zeiten eines Raums."""
    seconds = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=3600, step=5, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
        )
    )
    return {
        vol.Required(CONF_LIGHTS, default=current.get(CONF_LIGHTS, [])): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="light", multiple=True)
        ),
        vol.Required(
            CONF_PRESENCE_SENSORS, default=current.get(CONF_PRESENCE_SENSORS, [])
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor", multiple=True)
        ),
        _optional(CONF_NIGHT_LIGHTS, current): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="light", multiple=True)
        ),
        _optional(CONF_MEDIA_ENTITY, current): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["media_player", "input_boolean", "binary_sensor", "switch"]
            )
        ),
        _optional(CONF_SLEEP_ENTITY, current): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["input_boolean", "binary_sensor", "switch", "schedule"]
            )
        ),
        _optional(CONF_DARK_SENSOR, current): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor")
        ),
        _optional(CONF_LUX_SENSOR, current): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor", device_class=SensorDeviceClass.ILLUMINANCE
            )
        ),
        vol.Required(
            CONF_LUX_THRESHOLD,
            default=current.get(CONF_LUX_THRESHOLD, DEFAULT_LUX_THRESHOLD),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=5000, step=1, unit_of_measurement="lx", mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Required(
            CONF_OFF_DELAY, default=current.get(CONF_OFF_DELAY, DEFAULT_OFF_DELAY)
        ): seconds,
        vol.Required(
            CONF_DIM_BEFORE_OFF,
            default=current.get(CONF_DIM_BEFORE_OFF, DEFAULT_DIM_BEFORE_OFF),
        ): seconds,
        vol.Required(
            CONF_NIGHT_START, default=current.get(CONF_NIGHT_START, DEFAULT_NIGHT_START)
        ): selector.TimeSelector(),
        vol.Required(
            CONF_NIGHT_END, default=current.get(CONF_NIGHT_END, DEFAULT_NIGHT_END)
        ): selector.TimeSelector(),
    }


def _light_schema(current: dict[str, Any]) -> dict[Any, Any]:
    """Helligkeit und Farbtemperatur pro Tagesphase."""
    percent = selector.NumberSelector(
        selector.NumberSelectorConfig(min=1, max=100, step=1, unit_of_measurement="%")
    )
    kelvin = selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=2000, max=6500, step=100, unit_of_measurement="K"
        )
    )
    fields: dict[Any, Any] = {}
    for phase in PHASES:
        default_brightness, default_kelvin = DEFAULT_PHASE_SETTINGS[phase]
        fields[
            vol.Required(
                conf_brightness(phase),
                default=current.get(conf_brightness(phase), default_brightness),
            )
        ] = percent
        fields[
            vol.Required(
                conf_kelvin(phase), default=current.get(conf_kelvin(phase), default_kelvin)
            )
        ] = kelvin
    fields[
        vol.Required(CONF_TRANSITION, default=current.get(CONF_TRANSITION, DEFAULT_TRANSITION))
    ] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=0, max=10, step=0.5, unit_of_measurement="s")
    )
    return fields


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not user_input.get(CONF_LIGHTS):
        errors[CONF_LIGHTS] = "no_lights"
    if not user_input.get(CONF_PRESENCE_SENSORS):
        errors[CONF_PRESENCE_SENSORS] = "no_presence"
    lights = set(user_input.get(CONF_LIGHTS) or [])
    if not set(user_input.get(CONF_NIGHT_LIGHTS) or []) <= lights:
        errors[CONF_NIGHT_LIGHTS] = "night_lights_not_in_room"
    return errors


class LichtsteuerungConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einen Raum anlegen."""

    VERSION = 1

    def __init__(self) -> None:
        """Flow-Zustand."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 1: Name, Lichter, Sensoren, Zeiten."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_NAME].strip().lower())
                self._abort_if_unique_id_configured()
                self._data = user_input
                return await self.async_step_light()

        current = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=current.get(CONF_NAME, "")): str,
                **_room_schema(current),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_light(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 2: Licht pro Tagesphase."""
        if user_input is not None:
            data = {**self._data}
            name = data.pop(CONF_NAME).strip()
            return self.async_create_entry(title=name, data={}, options={**data, **user_input})

        return self.async_show_form(
            step_id="light", data_schema=vol.Schema(_light_schema({}))
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Optionen bearbeiten."""
        return LichtsteuerungOptionsFlow()


class LichtsteuerungOptionsFlow(OptionsFlow):
    """Einen bestehenden Raum ändern."""

    def __init__(self) -> None:
        """Flow-Zustand."""
        self._data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 1: Lichter, Sensoren, Zeiten."""
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                self._data = user_input
                return await self.async_step_light()
            current = user_input

        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(_room_schema(current)), errors=errors
        )

    async def async_step_light(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 2: Licht pro Tagesphase."""
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            return self.async_create_entry(data={**self._data, **user_input})

        return self.async_show_form(
            step_id="light", data_schema=vol.Schema(_light_schema(current))
        )
