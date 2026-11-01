"""Tests für die Raum-Logik."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.lichtsteuerung.const import (
    CONF_DARK_SENSOR,
    CONF_DIM_BEFORE_OFF,
    CONF_LIGHTS,
    CONF_NIGHT_END,
    CONF_NIGHT_START,
    CONF_OFF_DELAY,
    CONF_PRESENCE_SENSORS,
    DOMAIN,
)
from custom_components.lichtsteuerung.controller import in_window

LIGHT = "light.sofa"
PRESENCE = "binary_sensor.wohnzimmer_presence"
DARK = "binary_sensor.helper_dunkel"
STATUS = "sensor.lichtsteuerung_wohnzimmer_status"
LIGHT_ATTRS = {"supported_color_modes": ["color_temp"], "brightness": 180}


@pytest.fixture
async def setup(hass: HomeAssistant, freezer):
    """Wohnzimmer mit einem Licht, einem Präsenzmelder und Dunkel-Sensor."""
    freezer.move_to(dt_util.now().replace(hour=19, minute=0, second=0))
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(DARK, "on")
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]})

    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "light", "turn_off")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer",
        data={},
        options={
            CONF_LIGHTS: [LIGHT],
            CONF_PRESENCE_SENSORS: [PRESENCE],
            CONF_DARK_SENSOR: DARK,
            CONF_OFF_DELAY: 60,
            CONF_DIM_BEFORE_OFF: 10,
            CONF_NIGHT_START: "22:30:00",
            CONF_NIGHT_END: "05:30:00",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return turn_on, turn_off


def _own(hass, call, state, attrs=LIGHT_ATTRS):
    """Licht meldet den Zustand, den die Integration angefordert hat."""
    hass.states.async_set(LIGHT, state, attrs, context=call.context)


async def test_window():
    """Nachtfenster über Mitternacht."""
    from datetime import time

    assert in_window(time(23), time(22, 30), time(5, 30))
    assert in_window(time(3), time(22, 30), time(5, 30))
    assert not in_window(time(12), time(22, 30), time(5, 30))
    assert in_window(time(12), time(9), time(17))


async def test_presence_turns_on_with_evening_settings(hass, setup):
    """Präsenz bei Dunkelheit schaltet das Licht mit Abend-Werten an."""
    turn_on, _ = setup
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()

    assert len(turn_on) == 1
    assert turn_on[0].data["brightness_pct"] == 70
    assert turn_on[0].data["color_temp_kelvin"] == 2900


async def test_no_light_when_bright(hass, setup):
    """Tagsüber und hell: kein Licht."""
    turn_on, _ = setup
    hass.states.async_set(DARK, "off")
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert turn_on == []


async def test_empty_room_dims_then_turns_off(hass, setup):
    """Leerer Raum: erst dimmen, dann aus."""
    turn_on, turn_off = setup
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert len(turn_on) == 2
    assert turn_on[1].data["brightness"] == int(180 * 0.3)
    assert hass.states.get(STATUS).state == "gedimmt"
    _own(hass, turn_on[1], "on", {**LIGHT_ATTRS, "brightness": 54})

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=75))
    await hass.async_block_till_done()
    assert len(turn_off) == 1


async def test_presence_during_dim_restores(hass, setup):
    """Kommt jemand während des Dimmens zurück, wird wieder hell."""
    turn_on, turn_off = setup
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 3
    assert turn_on[2].data["brightness_pct"] == 70
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=200))
    await hass.async_block_till_done()
    assert turn_off == []


async def test_manual_change_wins(hass, setup):
    """Manuelles Dimmen wird nicht überschrieben, auch nicht beim Phasenwechsel."""
    turn_on, turn_off = setup
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")

    # Jemand dimmt per App
    hass.states.async_set(LIGHT, "on", {**LIGHT_ATTRS, "brightness": 40})
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "manuell"

    # Sonnenstand ändert sich -> keine Anpassung
    hass.states.async_set("sun.sun", "above_horizon")
    await hass.async_block_till_done()
    assert len(turn_on) == 1


async def test_manual_off_stays_off_while_occupied(hass, setup):
    """Manuell ausgeschaltet bleibt aus, solange jemand im Raum ist."""
    turn_on, _ = setup
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]})
    await hass.async_block_till_done()

    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1

    # Nach Ablauf der Verzögerung im leeren Raum ist die Automatik wieder normal
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "aus"
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 2


async def test_bright_turns_off_auto_light(hass, setup):
    """Wird es hell, geht automatisch eingeschaltetes Licht aus."""
    turn_on, turn_off = setup
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    hass.states.async_set(DARK, "off")
    await hass.async_block_till_done()
    assert len(turn_off) == 1


async def test_switch_disables(hass, setup):
    """Automatik aus: nichts passiert."""
    turn_on, _ = setup
    switch = next(
        e.entity_id
        for e in er.async_get(hass).entities.values()
        if e.unique_id.endswith("_automatik")
    )
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": switch}, blocking=True
    )
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert turn_on == []
    assert hass.states.get(STATUS).state == "deaktiviert"
