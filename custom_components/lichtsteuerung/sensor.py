"""Status-Sensor eines Raums."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LichtsteuerungConfigEntry
from .const import ROOM_STATES
from .entity import RoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LichtsteuerungConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Status-Sensor anlegen."""
    async_add_entities([RoomStatusSensor(entry.runtime_data, "status")])


class RoomStatusSensor(RoomEntity, SensorEntity):
    """Zeigt, was die Lichtsteuerung im Raum gerade macht."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(ROOM_STATES)

    async def async_added_to_hass(self) -> None:
        """Entity-ID für Logbuch-Einträge bekannt machen."""
        await super().async_added_to_hass()
        self.controller.status_entity_id = self.entity_id

    @property
    def native_value(self) -> str:
        """Aktueller Raumzustand."""
        return self.controller.room_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Tagesphase, Anwesenheit, Dunkelheit."""
        return self.controller.attributes()
