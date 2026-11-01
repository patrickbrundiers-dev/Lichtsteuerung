"""Lichtsteuerung: individuelle, raumbasierte Lichtautomatik für Home Assistant."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .controller import RoomController

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_ROOMS = "rooms"
ATTR_SLEEP = "sleep"
SERVICE_SET_SLEEP = "set_sleep_mode"
SERVICE_RESET = "reset"
SERVICE_SET_ENABLED = "set_enabled"
SERVICE_FLASH = "flash"
ATTR_COUNT = "count"
ATTR_ONLY_OCCUPIED = "only_occupied"
ATTR_ENABLED = "enabled"

_ROOMS_SCHEMA = {vol.Optional(ATTR_ROOMS): vol.All(cv.ensure_list, [cv.string])}

type LichtsteuerungConfigEntry = ConfigEntry[RoomController]


def _controllers(hass: HomeAssistant, call: ServiceCall) -> list[RoomController]:
    """Geladene Räume, optional gefiltert nach Name."""
    wanted = {r.strip().casefold() for r in call.data.get(ATTR_ROOMS, [])}
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and (not wanted or entry.title.strip().casefold() in wanted)
    ]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Haus-weite Aktionen registrieren."""

    async def set_sleep(call: ServiceCall) -> None:
        for controller in _controllers(hass, call):
            controller.async_set_sleep(call.data[ATTR_SLEEP])

    async def reset(call: ServiceCall) -> None:
        for controller in _controllers(hass, call):
            controller.async_reset()

    async def set_enabled(call: ServiceCall) -> None:
        for controller in _controllers(hass, call):
            controller.async_set_enabled(call.data[ATTR_ENABLED])

    async def flash(call: ServiceCall) -> None:
        targets = [
            c
            for c in _controllers(hass, call)
            if not call.data[ATTR_ONLY_OCCUPIED] or c.occupied()
        ]
        await asyncio.gather(*(c.async_flash(call.data[ATTR_COUNT]) for c in targets))

    hass.services.async_register(
        DOMAIN,
        SERVICE_FLASH,
        flash,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_COUNT, default=3): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=10)
                ),
                vol.Optional(ATTR_ONLY_OCCUPIED, default=True): cv.boolean,
                **_ROOMS_SCHEMA,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SLEEP,
        set_sleep,
        schema=vol.Schema({vol.Required(ATTR_SLEEP): cv.boolean, **_ROOMS_SCHEMA}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET, reset, schema=vol.Schema(_ROOMS_SCHEMA)
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ENABLED,
        set_enabled,
        schema=vol.Schema({vol.Required(ATTR_ENABLED): cv.boolean, **_ROOMS_SCHEMA}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LichtsteuerungConfigEntry) -> bool:
    """Einen Raum einrichten."""
    controller = RoomController(hass, entry)
    await controller.async_load()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    controller.async_start()
    entry.async_on_unload(controller.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LichtsteuerungConfigEntry) -> bool:
    """Einen Raum entfernen."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: LichtsteuerungConfigEntry) -> None:
    """Nach Änderung der Optionen neu laden."""
    await hass.config_entries.async_reload(entry.entry_id)
