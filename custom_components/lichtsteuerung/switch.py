"""Schalter, um die Automatik eines Raums ein- und auszuschalten."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import LichtsteuerungConfigEntry
from .entity import RoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LichtsteuerungConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Automatik-Schalter anlegen."""
    async_add_entities([RoomAutomationSwitch(entry.runtime_data, "automatik")])


class RoomAutomationSwitch(RoomEntity, SwitchEntity, RestoreEntity):
    """Automatik für den Raum an/aus. Der Zustand bleibt über Neustarts erhalten."""

    async def async_added_to_hass(self) -> None:
        """Letzten Zustand wiederherstellen."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_OFF:
            self.controller.async_set_enabled(False)

    @property
    def is_on(self) -> bool:
        """Ist die Automatik aktiv?"""
        return self.controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Automatik einschalten."""
        self.controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Automatik ausschalten. Lichter bleiben, wie sie sind."""
        self.controller.async_set_enabled(False)
