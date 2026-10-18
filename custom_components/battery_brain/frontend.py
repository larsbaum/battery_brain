"""Serve the bundled dashboard cards to the Home Assistant frontend."""

from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOGGER

CARDS_FILENAME = "battery-brain-cards.js"
CARDS_URL = f"/{DOMAIN}/{CARDS_FILENAME}"
_DATA_REGISTERED = f"{DOMAIN}_frontend_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the card module once per HA run.

    Static paths can't be removed again, so a reload of the config entry must
    not register them a second time. The module is loaded on every dashboard,
    which makes both cards show up in the card picker without a manual
    Lovelace resource.
    """
    if hass.data.get(_DATA_REGISTERED):
        return
    if hass.http is None or "frontend" not in hass.config.components:
        # No web UI (e.g. a headless setup): nothing to serve the cards to.
        LOGGER.debug("Frontend not loaded, dashboard cards not registered")
        return

    # Imported lazily: frontend is only an after_dependency.
    from homeassistant.components.frontend import add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    path = Path(__file__).parent / "www" / CARDS_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARDS_URL, str(path), cache_headers=True)]
    )
    # A content hash makes browsers fetch the file again whenever it changed,
    # despite the cache headers — also between releases with the same version.
    digest = await hass.async_add_executor_job(_file_hash, path)
    add_extra_js_url(hass, f"{CARDS_URL}?v={digest}")
    hass.data[_DATA_REGISTERED] = True


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
