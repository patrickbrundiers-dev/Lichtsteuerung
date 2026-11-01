"""Taste zum Zurücksetzen der Automatik eines Raums."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LichtsteuerungConfigEntry
from .entity import RoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LichtsteuerungConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Taste anlegen."""
    async_add_entities([RoomResetButton(entry.runtime_data, "zuruecksetzen")])


class RoomResetButton(RoomEntity, ButtonEntity):
    """Beendet den manuellen Modus, die Automatik übernimmt sofort wieder."""

    _attr_icon = "mdi:restore"

    async def async_press(self) -> None:
        """Automatik zurücksetzen."""
        self.controller.async_reset()
