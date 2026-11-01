"""Gemeinsame Fixtures."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Eigene Integration in allen Tests laden."""
    yield


@pytest.fixture(autouse=True)
def no_grace_window():
    """In Tests zählen nur die Kontexte als eigene Änderung, nicht das Zeitfenster."""
    with (
        patch("custom_components.lichtsteuerung.controller.OWN_CHANGE_GRACE_SECONDS", 0),
        patch("custom_components.lichtsteuerung.controller.FLASH_STEP_SECONDS", 0),
    ):
        yield
