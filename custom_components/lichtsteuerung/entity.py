"""Gemeinsame Basis für die Entitäten eines Raums."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_ROOM_UPDATED
from .controller import RoomController


class RoomEntity(Entity):
    """Entität, die zu einem Raum gehört und sich bei Änderungen aktualisiert."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: RoomController, key: str) -> None:
        """Entität anlegen."""
        self.controller = controller
        entry = controller.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Lichtsteuerung {entry.title}",
            manufacturer="Lichtsteuerung",
            model="Raum",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Auf Raum-Updates hören."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ROOM_UPDATED.format(self.controller.entry.entry_id),
                self._handle_room_update,
            )
        )

    @callback
    def _handle_room_update(self) -> None:
        self.async_write_ha_state()
