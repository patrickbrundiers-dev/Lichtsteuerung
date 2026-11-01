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
    CONF_MEDIA_ENTITY,
    CONF_NIGHT_END,
    CONF_NIGHT_LIGHTS,
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


LIGHT2 = "light.bilderleiste"
TV = "input_boolean.fernseher_an"


@pytest.fixture
async def setup_v2(hass: HomeAssistant, freezer):
    """Wohnzimmer mit Haupt- und Nachtlicht und Fernseher."""
    freezer.move_to(dt_util.now().replace(hour=19, minute=0, second=0))
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(DARK, "on")
    hass.states.async_set(TV, "off")
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]})
    hass.states.async_set(LIGHT2, "off", {"supported_color_modes": ["brightness"]})

    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "light", "turn_off")
    logbook = async_mock_service(hass, "logbook", "log")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer",
        data={},
        options={
            CONF_LIGHTS: [LIGHT, LIGHT2],
            CONF_NIGHT_LIGHTS: [LIGHT],
            CONF_MEDIA_ENTITY: TV,
            CONF_PRESENCE_SENSORS: [PRESENCE],
            CONF_DARK_SENSOR: DARK,
            CONF_OFF_DELAY: 60,
            CONF_DIM_BEFORE_OFF: 0,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return turn_on, turn_off, logbook


def _sleep_switch(hass):
    return next(
        e.entity_id
        for e in er.async_get(hass).entities.values()
        if e.unique_id.endswith("_schlafmodus")
    )


async def test_tv_mode(hass, setup_v2):
    """Fernseher an: TV-Werte, und das Licht geht trotz leerem Melder nicht aus."""
    turn_on, turn_off, _ = setup_v2
    hass.states.async_set(TV, "on")
    await hass.async_block_till_done()
    assert {c.data["entity_id"] for c in turn_on} == {LIGHT, LIGHT2}
    assert all(c.data["brightness_pct"] == 30 for c in turn_on)
    assert "color_temp_kelvin" not in next(
        c.data for c in turn_on if c.data["entity_id"] == LIGHT2
    )
    for c in turn_on:
        hass.states.async_set(
            c.data["entity_id"], "on", LIGHT_ATTRS, context=c.context
        )
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).attributes["modus"] == "tv"

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=300))
    await hass.async_block_till_done()
    assert turn_off == []


async def test_sleep_uses_night_lights_only(hass, setup_v2):
    """Schlafmodus: nur das Nachtlicht, das Hauptlicht geht aus."""
    turn_on, turn_off, logbook = setup_v2
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    for c in turn_on:
        hass.states.async_set(
            c.data["entity_id"], "on", LIGHT_ATTRS, context=c.context
        )
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": _sleep_switch(hass)}, blocking=True
    )
    await hass.async_block_till_done()
    sleep_calls = turn_on[2:]
    assert [c.data["entity_id"] for c in sleep_calls] == [LIGHT]
    assert sleep_calls[0].data["brightness_pct"] == 2
    assert turn_off[-1].data["entity_id"] == [LIGHT2]

    status = hass.states.get(STATUS)
    assert status.attributes["modus"] == "schlaf"
    assert "schlaf" in status.attributes["letzte_aktion"]
    assert any("Anwesenheit erkannt" in c.data["message"] for c in logbook)


async def test_night_phase_uses_night_lights(hass, setup_v2, freezer):
    """Nachts schaltet Präsenz nur das Nachtlicht."""
    turn_on, _, _ = setup_v2
    freezer.move_to(dt_util.now().replace(hour=23, minute=0))
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert [c.data["entity_id"] for c in turn_on] == [LIGHT]
    assert turn_on[0].data["brightness_pct"] == 5


HOUSE = "input_select.hausmodus"
DOOR = "binary_sensor.tuer"


@pytest.fixture
async def setup_v3(hass: HomeAssistant, freezer):
    """Raum mit allen Zusatzfunktionen."""
    freezer.move_to(dt_util.now().replace(hour=19, minute=0, second=0))
    hass.states.async_set("sun.sun", "below_horizon", {"elevation": -10})
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(DARK, "on")
    hass.states.async_set(DOOR, "off")
    hass.states.async_set(HOUSE, "Zuhause ")
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]})

    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "light", "turn_off")
    scene_on = async_mock_service(hass, "scene", "turn_on")

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer",
        data={},
        options={
            CONF_LIGHTS: [LIGHT],
            CONF_PRESENCE_SENSORS: [PRESENCE],
            CONF_DARK_SENSOR: DARK,
            CONF_OFF_DELAY: 60,
            CONF_DIM_BEFORE_OFF: 0,
            "adaptive": True,
            "tv_scene": "scene.filmabend",
            "media_entity": "input_boolean.tv",
            "trigger_sensors": [DOOR],
            "extended_after": 10,
            "extended_off_delay": 900,
            "override_timeout": 30,
            "house_mode_entity": HOUSE,
            "away_states": "Abwesend",
            "vacation_states": "Urlaub",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return turn_on, turn_off, scene_on


async def test_adaptive_values(hass, setup_v3):
    """Sonnenhöhe zwischen Abend und Tag ergibt Zwischenwerte."""
    turn_on, _, _ = setup_v3
    hass.states.async_set("sun.sun", "below_horizon", {"elevation": 4.5})
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    # Hälfte zwischen -6° und 15°: zwischen 70 % / 2900 K und 100 % / 4000 K
    assert turn_on[0].data["brightness_pct"] == 85
    assert turn_on[0].data["color_temp_kelvin"] == 3450


async def test_sun_attribute_update_does_not_resend(hass, setup_v3):
    """Nur die Sonnenhöhe ändert sich: kein neuer Befehl außer im 5-Minuten-Takt."""
    turn_on, _, _ = setup_v3
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    hass.states.async_set("sun.sun", "below_horizon", {"elevation": -11})
    await hass.async_block_till_done()
    assert len(turn_on) == 1


async def test_tv_scene(hass, setup_v3):
    """Für TV ist eine Szene hinterlegt."""
    _, _, scene_on = setup_v3
    hass.states.async_set("input_boolean.tv", "on")
    await hass.async_block_till_done()
    assert scene_on[0].data["entity_id"] == "scene.filmabend"


async def test_door_trigger(hass, setup_v3):
    """Tür auf schaltet an; ohne Präsenz geht es nach der Verzögerung wieder aus."""
    turn_on, turn_off, _ = setup_v3
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1
    _own(hass, turn_on[0], "on")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert len(turn_off) == 1


async def test_extended_presence(hass, setup_v3, freezer):
    """Wer länger da war, bekommt die längere Ausschaltverzögerung."""
    turn_on, turn_off, _ = setup_v3
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    freezer.tick(timedelta(minutes=11))
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=120))
    await hass.async_block_till_done()
    assert turn_off == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=901))
    await hass.async_block_till_done()
    assert len(turn_off) == 1


async def test_override_timeout(hass, setup_v3, freezer):
    """Manueller Modus endet nach der eingestellten Zeit."""
    turn_on, _, _ = setup_v3
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    hass.states.async_set(LIGHT, "on", {**LIGHT_ATTRS, "brightness": 20})
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "manuell"
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "an"
    assert len(turn_on) == 2


async def test_away_turns_off_and_blocks(hass, setup_v3):
    """Hausmodus abwesend: Licht aus, Präsenz schaltet nicht ein."""
    turn_on, turn_off, _ = setup_v3
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    hass.states.async_set(HOUSE, "Abwesend ")
    await hass.async_block_till_done()
    assert len(turn_off) == 1
    assert hass.states.get(STATUS).state == "abwesend"
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]}, context=turn_off[0].context)
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1


async def test_vacation_simulation(hass, setup_v3, freezer):
    """Urlaub: abends wird das Licht zufällig geschaltet."""
    turn_on, _, _ = setup_v3
    hass.states.async_set(HOUSE, "Urlaub ")
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "simulation"
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(turn_on) == 1


async def test_reset_button(hass, setup_v3):
    """Taste beendet den manuellen Modus."""
    turn_on, _, _ = setup_v3
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    hass.states.async_set(LIGHT, "on", {**LIGHT_ATTRS, "brightness": 20})
    await hass.async_block_till_done()
    button = next(
        e.entity_id
        for e in er.async_get(hass).entities.values()
        if e.unique_id.endswith("_zuruecksetzen")
    )
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "an"
    assert len(turn_on) == 2
