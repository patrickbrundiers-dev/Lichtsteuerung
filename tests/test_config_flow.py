"""Tests für die Einrichtung per UI."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.lichtsteuerung.const import DOMAIN


async def test_create_room(hass: HomeAssistant):
    """Raum in zwei Schritten anlegen und Optionen ändern."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Küche",
            "lights": ["light.kochfeld"],
            "presence_sensors": ["binary_sensor.kueche"],
            "lux_threshold": 30,
            "off_delay": 120,
            "dim_before_off": 20,
            "night_start": "22:30:00",
            "night_end": "05:30:00",
        },
    )
    assert result["step_id"] == "light"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "extras"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"adaptive": True, "abend_scene": "scene.kueche_abend"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["adaptive"] is True
    assert result["options"]["abend_scene"] == "scene.kueche_abend"
    assert result["title"] == "Küche"
    assert result["options"]["lights"] == ["light.kochfeld"]
    assert result["options"]["abend_brightness"] == 70

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "lights": ["light.kochfeld", "light.unterschrank"],
            "presence_sensors": ["binary_sensor.kueche"],
            "lux_threshold": 30,
            "off_delay": 300,
            "dim_before_off": 0,
            "night_start": "23:00:00",
            "night_end": "05:00:00",
        },
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"nacht_brightness": 10}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"override_timeout": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["off_delay"] == 300
    assert entry.options["nacht_brightness"] == 10
    assert len(entry.options["lights"]) == 2
    assert entry.options["override_timeout"] == 30
    assert "abend_scene" not in entry.options


async def test_requires_lights(hass: HomeAssistant):
    """Ohne Licht kein Raum."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Leer",
            "lights": [],
            "presence_sensors": ["binary_sensor.x"],
            "lux_threshold": 30,
            "off_delay": 120,
            "dim_before_off": 20,
            "night_start": "22:30:00",
            "night_end": "05:30:00",
        },
    )
    assert result["errors"] == {"lights": "no_lights"}
