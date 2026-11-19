"""Gemeinsame Fixtures. HA-Tests laufen nur, wenn pytest-homeassistant-custom-component installiert ist."""

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:  # nur test_api.py ausführbar
    collect_ignore = ["test_init.py"]
else:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        yield
