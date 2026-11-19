"""Liefert die Dashboard-Karte "Zugangsübersicht" mit aus.

Die Karte liegt in www/ und wird beim Start automatisch im Frontend geladen.
Eine Ressource in den Dashboard-Einstellungen ist dafür nicht nötig.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import CARD_FILENAME, CARD_URL_BASE, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_register_card(hass: HomeAssistant) -> None:
    """Statischen Pfad anlegen und die Karte als Frontend-Modul eintragen.

    Ohne http/frontend (z. B. in Tests) wird nichts registriert.
    """
    if hass.http is None or "frontend" not in hass.config.components:
        return

    # Import erst hier: frontend ist nur after_dependency
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    path = Path(__file__).parent / "www" / CARD_FILENAME
    url = f"{CARD_URL_BASE}/{CARD_FILENAME}"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(url, str(path), cache_headers=False)]
    )
    integration = await async_get_integration(hass, DOMAIN)
    # Versionsparameter, damit Browser nach einem Update die neue Datei laden
    add_extra_js_url(hass, f"{url}?v={integration.version}")
    _LOGGER.debug("Dashboard-Karte unter %s registriert", url)
