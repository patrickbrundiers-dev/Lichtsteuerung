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


async def test_learning_off_delay(hass, setup):
    """Kommt jemand kurz nach dem Aus zurück, wird die Verzögerung länger."""
    turn_on, turn_off = setup
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    _own(hass, turn_on[1], "on", {**LIGHT_ATTRS, "brightness": 54})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=75))
    await hass.async_block_till_done()
    assert len(turn_off) == 1
    hass.states.async_set(
        LIGHT, "off", {"supported_color_modes": ["color_temp"]}, context=turn_off[0].context
    )

    # 30 s später ist wieder jemand da: Fehlabschaltung
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    status = hass.states.get(STATUS)
    assert status.attributes["gelernter_zuschlag_s"] == 30
    assert len(turn_on) == 3  # und das Licht ist wieder an


PATH = "binary_sensor.bett"


async def test_night_path(hass, freezer):
    """Nachts aufstehen: Flur geht an, zurück im Bett: aus."""
    freezer.move_to(dt_util.now().replace(hour=2, minute=0, second=0))
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(DARK, "on")
    hass.states.async_set(PATH, "on")
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]})
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "light", "turn_off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Flur",
        data={},
        options={
            CONF_LIGHTS: [LIGHT],
            CONF_PRESENCE_SENSORS: [PRESENCE],
            CONF_DARK_SENSOR: DARK,
            CONF_OFF_DELAY: 60,
            CONF_DIM_BEFORE_OFF: 0,
            "path_sensors": [PATH],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set(PATH, "off")
    await hass.async_block_till_done()
    assert len(turn_on) == 1
    assert turn_on[0].data["brightness_pct"] == 5
    _own(hass, turn_on[0], "on")

    # Nach 2 Minuten noch an (Mindestdauer 10 Minuten)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=120))
    await hass.async_block_till_done()
    assert turn_off == []

    hass.states.async_set(PATH, "on")
    await hass.async_block_till_done()
    assert len(turn_off) == 1


async def test_house_services(hass, setup):
    """Haus-weite Aktion setzt den Schlafmodus in allen Räumen."""
    await hass.services.async_call(
        DOMAIN, "set_sleep_mode", {"sleep": True}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).attributes["modus"] == "schlaf"
    await hass.services.async_call(
        DOMAIN, "set_enabled", {"enabled": False, "rooms": ["wohnzimmer"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "deaktiviert"


async def test_welcome_light(hass, setup):
    """Person kommt im Dunkeln heim: Licht an."""
    turn_on, _ = setup
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.states.async_set("person.patrick", "not_home", {"friendly_name": "Patrick"})
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "welcome_persons": ["person.patrick"]}
    )
    await hass.async_block_till_done()
    hass.states.async_set("person.patrick", "home", {"friendly_name": "Patrick"})
    await hass.async_block_till_done()
    assert len(turn_on) == 1
    assert "Willkommen" in hass.states.get(STATUS).attributes["letzte_aktion"]


async def test_bedtime_winddown(hass, setup, freezer):
    """Vor der Schlafenszeit wird langsam gedimmt, dann Schlafmodus."""
    turn_on, _ = setup
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "bedtime": "19:30:00", "winddown": 20}
    )
    await hass.async_block_till_done()
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[-1], "on")
    count = len(turn_on)

    freezer.move_to(dt_util.now().replace(hour=19, minute=10, second=0))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(turn_on) == count + 1
    assert turn_on[-1].data["transition"] == 1200
    assert turn_on[-1].data["brightness_pct"] == 2

    freezer.tick(timedelta(minutes=21))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    status = hass.states.get(STATUS)
    assert status.attributes["modus"] == "schlaf"
    assert status.attributes["schlafenszeit_aktiv"] is True


async def test_usage_and_flash(hass, setup, freezer):
    """Leuchtdauer zählt mit, Blinken stellt den Zustand wieder her."""
    turn_on, turn_off = setup
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=30))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    usage_id = next(
        e.entity_id
        for e in er.async_get(hass).entities.values()
        if e.unique_id.endswith("_leuchtdauer_heute")
    )
    usage = hass.states.get(usage_id)
    assert float(usage.state) == pytest.approx(0.5, abs=0.02)

    await hass.services.async_call(DOMAIN, "flash", {"count": 1}, blocking=True)
    await hass.async_block_till_done()
    # einmal aus, einmal an, dann Wiederherstellung (an)
    assert turn_off[-1].data["entity_id"] == [LIGHT]
    assert turn_on[-1].data["brightness"] == 180


async def test_health_issue(hass, setup, freezer):
    """Hängender Präsenzmelder erzeugt eine Reparaturmeldung."""
    from homeassistant.helpers import issue_registry as ir

    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=7))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    issues = [i for i in ir.async_get(hass).issues.values() if i.domain == DOMAIN]
    assert [i.translation_key for i in issues] == ["presence_stuck"]


async def test_health_issue_missing_entity(hass, setup, freezer):
    """Umbenannter Melder (Entität fehlt) erzeugt eine Reparaturmeldung."""
    from homeassistant.helpers import issue_registry as ir

    hass.states.async_remove(PRESENCE)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    issues = [i for i in ir.async_get(hass).issues.values() if i.domain == DOMAIN]
    assert [i.translation_key for i in issues] == ["entity_missing"]
    assert issues[0].translation_placeholders["entity"] == PRESENCE

    hass.states.async_set(PRESENCE, "off")
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not [i for i in ir.async_get(hass).issues.values() if i.domain == DOMAIN]


LUX = "sensor.wohnzimmer_lux"


async def test_lux_sensor(hass: HomeAssistant, freezer):
    """Träger Lux-Sensor nach dem Aus und Ausschalten bei Tageslicht."""
    freezer.move_to(dt_util.now().replace(hour=19, minute=0, second=0))
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(LUX, "10")
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
            "lux_sensor": LUX,
            "lux_threshold": 30,
            CONF_OFF_DELAY: 60,
            CONF_DIM_BEFORE_OFF: 0,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # An bei 10 lx, Lampe hebt den Sensor auf 80 lx
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1
    _own(hass, turn_on[-1], "on")
    hass.states.async_set(LUX, "80")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=130))
    hass.states.async_set(LUX, "81")  # gesetzter Wert mit Lampe
    await hass.async_block_till_done()
    assert len(turn_off) == 0

    # Raum leer -> aus, Sensor zeigt noch 81 lx
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(turn_off) == 1
    _own(hass, turn_off[-1], "off", {"supported_color_modes": ["color_temp"]})
    await hass.async_block_till_done()

    # Sofort zurück: trotz 81 lx gilt es als dunkel
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 2
    _own(hass, turn_on[-1], "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=130))
    hass.states.async_set(LUX, "82")
    await hass.async_block_till_done()
    assert len(turn_off) == 1

    # Tageslicht: Lampe ~70 lx, gemessen 150 -> ohne Lampe ~80 lx >= 60
    hass.states.async_set(LUX, "150")
    await hass.async_block_till_done()
    assert len(turn_off) == 1  # erst bestätigen
    freezer.tick(timedelta(seconds=61))
    hass.states.async_set(LUX, "152")
    await hass.async_block_till_done()
    assert len(turn_off) == 2
    _own(hass, turn_off[-1], "off", {"supported_color_modes": ["color_temp"]})
    await hass.async_block_till_done()

    # Danach bleibt es aus, weil es wirklich hell ist
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 2


async def test_lux_bright_after_restart_with_light_on(hass: HomeAssistant, freezer):
    """Neustart bei brennendem Licht: morgens trotzdem aus, wenn es hell wird."""
    freezer.move_to(dt_util.now().replace(hour=19, minute=0, second=0))
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set(PRESENCE, "on")
    hass.states.async_set(DARK, "on")
    hass.states.async_set(LUX, "8")
    hass.states.async_set(LIGHT, "on", LIGHT_ATTRS)
    async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "light", "turn_off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer",
        data={},
        options={
            CONF_LIGHTS: [LIGHT],
            CONF_PRESENCE_SENSORS: [PRESENCE],
            CONF_DARK_SENSOR: DARK,
            "lux_sensor": LUX,
            "lux_threshold": 30,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Melder bleibt an, morgens wird es hell
    freezer.tick(timedelta(seconds=130))
    hass.states.async_set(LUX, "11")  # erster Wert mit Lampe
    await hass.async_block_till_done()
    hass.states.async_set(LUX, "50")
    await hass.async_block_till_done()
    assert len(turn_off) == 0  # 50 - 11 = 39 lx Tageslicht, noch zu wenig
    hass.states.async_set(LUX, "80")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=61))
    hass.states.async_set(LUX, "82")
    await hass.async_block_till_done()
    assert len(turn_off) == 1


async def test_lux_ambient_from_unchanged_sensor(hass: HomeAssistant, freezer):
    """Konstanter Wert ohne neue Meldung zählt beim Einschalten als Wert ohne Lampe."""
    freezer.move_to(dt_util.now().replace(hour=19, minute=0, second=0))
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(LUX, "20")
    hass.states.async_set(LIGHT, "on", LIGHT_ATTRS)  # z. B. nach Neustart
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "light", "turn_off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer",
        data={},
        options={
            CONF_LIGHTS: [LIGHT],
            CONF_PRESENCE_SENSORS: [PRESENCE],
            "lux_sensor": LUX,
            "lux_threshold": 30,
            CONF_OFF_DELAY: 60,
            CONF_DIM_BEFORE_OFF: 0,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Raum leer -> aus; der Sensor meldet danach nichts Neues (bleibt 20 lx)
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(turn_off) == 1
    _own(hass, turn_off[-1], "off", {"supported_color_modes": ["color_temp"]})
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=10))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # Wieder an: 20 lx gelten als Wert ohne Lampe, Lampe bringt 10 lx dazu
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1
    _own(hass, turn_on[-1], "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=130))
    hass.states.async_set(LUX, "30")
    await hass.async_block_till_done()
    hass.states.async_set(LUX, "75")  # 75 - 10 = 65 lx Tageslicht
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=61))
    hass.states.async_set(LUX, "76")
    await hass.async_block_till_done()
    assert len(turn_off) == 2
    assert "hell genug" in hass.states.get(STATUS).attributes["letzte_aktion"]


async def test_lux_spike_does_not_turn_off(hass: HomeAssistant, freezer):
    """Kurzer heller Ausreißer im Dunkeln schaltet nicht aus."""
    freezer.move_to(dt_util.now().replace(hour=6, minute=0, second=0))
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(LUX, "3")
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
            "lux_sensor": LUX,
            "lux_threshold": 30,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[-1], "on")
    await hass.async_block_till_done()
    freezer.tick(timedelta(seconds=130))
    hass.states.async_set(LUX, "6")
    await hass.async_block_till_done()

    # 06:23-Fall: 86, 80, 79 lx innerhalb von 40 s, danach wieder dunkel
    for value, wait in (("86", 0), ("80", 22), ("79", 19), ("6", 120)):
        freezer.tick(timedelta(seconds=wait))
        hass.states.async_set(LUX, value)
        await hass.async_block_till_done()
    assert len(turn_off) == 0


async def test_dark_sensor_off_turns_off_with_lux(hass: HomeAssistant, freezer):
    """Mit Dunkel- und Lux-Sensor: Dunkel-Sensor meldet hell -> aus."""
    freezer.move_to(dt_util.now().replace(hour=7, minute=0, second=0))
    hass.states.async_set("sun.sun", "above_horizon")
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(DARK, "on")
    hass.states.async_set(LUX, "10")
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
            "lux_sensor": LUX,
            "lux_threshold": 30,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1
    _own(hass, turn_on[-1], "on")
    await hass.async_block_till_done()

    hass.states.async_set(DARK, "off")
    await hass.async_block_till_done()
    assert len(turn_off) == 1
    _own(hass, turn_off[-1], "off", {"supported_color_modes": ["color_temp"]})
    await hass.async_block_till_done()

    # Bleibt aus, auch bei Bewegung
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1


async def test_nobody_home(hass: HomeAssistant, freezer):
    """Niemand zu Hause: nach 5 Minuten aus, kein Einschalten bis jemand kommt."""
    freezer.move_to(dt_util.now().replace(hour=19, minute=0, second=0))
    hass.states.async_set("sun.sun", "below_horizon")
    hass.states.async_set("zone.home", "1")
    hass.states.async_set(PRESENCE, "on")
    hass.states.async_set(DARK, "on")
    hass.states.async_set(LIGHT, "on", LIGHT_ATTRS)
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
            "away_when_empty": True,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set("zone.home", "0")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=4))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(turn_off) == 0

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(turn_off) == 1
    assert hass.states.get(STATUS).state == "abwesend"
    _own(hass, turn_off[-1], "off", {"supported_color_modes": ["color_temp"]})

    # Melder hängt / Haustier: kein Einschalten
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 0

    # Jemand kommt heim
    hass.states.async_set("zone.home", "1")
    await hass.async_block_till_done()
    assert len(turn_on) == 1


async def test_dark_sensor_and_lux_both_needed(hass: HomeAssistant, freezer):
    """Mit Dunkel- und Lux-Sensor: nur an, wenn draußen UND im Raum dunkel."""
    freezer.move_to(dt_util.now().replace(hour=15, minute=0, second=0))
    hass.states.async_set("sun.sun", "above_horizon")
    hass.states.async_set(PRESENCE, "on")
    hass.states.async_set(DARK, "off")
    hass.states.async_set(LUX, "25")  # trüber Tag, Raum unter Schwelle
    hass.states.async_set(LIGHT, "off", {"supported_color_modes": ["color_temp"]})
    turn_on = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer",
        data={},
        options={
            CONF_LIGHTS: [LIGHT],
            CONF_PRESENCE_SENSORS: [PRESENCE],
            CONF_DARK_SENSOR: DARK,
            "lux_sensor": LUX,
            "lux_threshold": 30,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(turn_on) == 0

    # Automatik aus und wieder an -> bleibt aus, draußen ist es hell
    switch = "switch.lichtsteuerung_wohnzimmer_automatik"
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    await hass.async_block_till_done()
    assert len(turn_on) == 0

    # Abends: draußen dunkel, Raum dunkel -> an
    hass.states.async_set(DARK, "on")
    await hass.async_block_till_done()
    assert len(turn_on) == 1


async def test_small_fluctuation_is_not_manual(hass, setup, freezer):
    """Lampen, die schwankende Werte nachmelden, gelten nicht als bedient."""
    turn_on, _ = setup
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    _own(hass, turn_on[0], "on", {**LIGHT_ATTRS, "color_temp_kelvin": 2700})
    await hass.async_block_till_done()

    freezer.tick(timedelta(seconds=30))
    hass.states.async_set(
        LIGHT, "on", {**LIGHT_ATTRS, "brightness": 182, "color_temp_kelvin": 2702}
    )
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state != "manuell"

    # Deutliche Änderung bleibt manuelle Bedienung
    hass.states.async_set(
        LIGHT, "on", {**LIGHT_ATTRS, "brightness": 60, "color_temp_kelvin": 2702}
    )
    await hass.async_block_till_done()
    assert hass.states.get(STATUS).state == "manuell"
