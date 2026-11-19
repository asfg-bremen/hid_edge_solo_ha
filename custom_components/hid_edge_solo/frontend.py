"""Liefert die Dashboard-Karten "Zugangsübersicht" und "Zutritte" mit aus.

Die Karten liegen in www/ und werden beim Start automatisch im Frontend
geladen. Eine Ressource in den Dashboard-Einstellungen ist nicht nötig.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CARD_FILENAMES, CARD_URL_BASE, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_register_card(hass: HomeAssistant) -> None:
    """Statische Pfade anlegen und die Karten als Frontend-Module eintragen.

    Ohne http/frontend (z. B. in Tests) wird nichts registriert.
    """
    if hass.http is None or "frontend" not in hass.config.components:
        return

    # Import erst hier: frontend ist nur after_dependency
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    www = Path(__file__).parent / "www"
    urls = [f"{CARD_URL_BASE}/{name}" for name in CARD_FILENAMES]
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(url, str(www / name), cache_headers=False)
            for url, name in zip(urls, CARD_FILENAMES)
        ]
    )
    integration = await async_get_integration(hass, DOMAIN)
    for url in urls:
        # Versionsparameter, damit Browser nach einem Update die neue Datei laden
        add_extra_js_url(hass, f"{url}?v={integration.version}")
    _LOGGER.debug("Dashboard-Karten registriert: %s", ", ".join(urls))
