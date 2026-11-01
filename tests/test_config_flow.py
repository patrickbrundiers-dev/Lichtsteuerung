"""Tests für die Einrichtung per UI."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.lichtsteuerung.const import DOMAIN


async def _create(hass: HomeAssistant, **extra):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Küche",
            "lights": ["light.kochfeld"],
            "presence_sensors": ["binary_sensor.kueche"],
            **extra,
        },
    )


async def test_create_room_in_one_step(hass: HomeAssistant):
    """Raum mit dem Nötigsten in einem Schritt anlegen."""
    result = await _create(hass, dark_sensor="binary_sensor.dunkel")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Küche"
    assert result["options"] == {
        "lights": ["light.kochfeld"],
        "presence_sensors": ["binary_sensor.kueche"],
        "dark_sensor": "binary_sensor.dunkel",
    }


async def test_options_menu(hass: HomeAssistant):
    """Bereiche einzeln ändern, erst Speichern übernimmt alles."""
    await _create(hass, night_lights=["light.kochfeld"])
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert "speichern" in result["menu_options"]

    # Lichter und Melder: Nachtlichter leeren, zweites Licht dazu
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "basis"}
    )
    assert result["step_id"] == "basis"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "lights": ["light.kochfeld", "light.unterschrank"],
            "presence_sensors": ["binary_sensor.kueche"],
        },
    )
    assert result["type"] is FlowResultType.MENU

    # Licht: Abschnitte pro Modus
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "licht"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "adaptive": True,
            "transition": 1,
            "tag": {"tag_brightness": 100, "tag_kelvin": 4000},
            "abend": {"abend_brightness": 50, "abend_kelvin": 2900, "abend_scene": "scene.abend"},
            "nacht": {"nacht_brightness": 10, "nacht_kelvin": 2200},
            "tv": {"tv_brightness": 30, "tv_kelvin": 2700},
            "schlaf": {"schlaf_brightness": 2, "schlaf_kelvin": 2000},
        },
    )
    assert result["type"] is FlowResultType.MENU

    # Zeiten
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "zeiten"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "off_delay": 300,
            "dim_before_off": 0,
            "learning": True,
            "extended_after": 0,
            "extended_off_delay": 600,
            "override_timeout": 30,
            "night_start": "23:00:00",
            "night_end": "05:00:00",
        },
    )
    assert entry.options.get("off_delay") is None  # noch nicht gespeichert

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "speichern"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["off_delay"] == 300
    assert entry.options["override_timeout"] == 30
    assert entry.options["abend_brightness"] == 50
    assert entry.options["abend_scene"] == "scene.abend"
    assert entry.options["adaptive"] is True
    assert len(entry.options["lights"]) == 2
    assert "night_lights" not in entry.options
    assert "abend" not in entry.options

    # Szene wieder leeren
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "licht"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "adaptive": True,
            "transition": 1,
            "tag": {"tag_brightness": 100, "tag_kelvin": 4000},
            "abend": {"abend_brightness": 50, "abend_kelvin": 2900},
            "nacht": {"nacht_brightness": 10, "nacht_kelvin": 2200},
            "tv": {"tv_brightness": 30, "tv_kelvin": 2700},
            "schlaf": {"schlaf_brightness": 2, "schlaf_kelvin": 2000},
        },
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "speichern"}
    )
    assert "abend_scene" not in entry.options
    assert entry.options["off_delay"] == 300


async def test_options_validation(hass: HomeAssistant):
    """Nachtlichter müssen zum Raum gehören."""
    await _create(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "basis"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "lights": ["light.kochfeld"],
            "night_lights": ["light.flur"],
            "presence_sensors": ["binary_sensor.kueche"],
        },
    )
    assert result["errors"] == {"night_lights": "night_lights_not_in_room"}


async def test_requires_lights(hass: HomeAssistant):
    """Ohne Licht kein Raum."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Leer", "lights": [], "presence_sensors": ["binary_sensor.x"]},
    )
    assert result["errors"] == {"lights": "no_lights"}
