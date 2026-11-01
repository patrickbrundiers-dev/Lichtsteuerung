"""Lichtsteuerung: individuelle, raumbasierte Lichtautomatik für Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .controller import RoomController

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]

type LichtsteuerungConfigEntry = ConfigEntry[RoomController]


async def async_setup_entry(hass: HomeAssistant, entry: LichtsteuerungConfigEntry) -> bool:
    """Einen Raum einrichten."""
    controller = RoomController(hass, entry)
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
