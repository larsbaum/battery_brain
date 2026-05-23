"""The BatteryBrain integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.start import async_at_started

from .const import CONF_DEVELOPER_MODE
from .coordinator import BatteryBrainCoordinator

if TYPE_CHECKING:
    BatteryBrainConfigEntry = ConfigEntry[BatteryBrainCoordinator]
else:
    BatteryBrainConfigEntry = ConfigEntry


def _platforms_for_entry(entry: ConfigEntry) -> list[Platform]:
    platforms: list[Platform] = [Platform.SENSOR]
    if entry.data.get(CONF_DEVELOPER_MODE, False):
        platforms.append(Platform.SWITCH)
    return platforms


async def async_setup_entry(
    hass: HomeAssistant, entry: BatteryBrainConfigEntry
) -> bool:
    """Set up BatteryBrain from a config entry."""
    coordinator = BatteryBrainCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, _platforms_for_entry(entry)
    )

    # Defer the first discovery+refresh until HA has finished starting up.
    # During HA startup, integrations load in parallel — many battery sensors
    # (mobile_app, Zigbee, etc.) may not yet be registered when BatteryBrain
    # initialises. Waiting for EVENT_HOMEASSISTANT_STARTED ensures the first
    # _discover_batteries() scan sees the complete entity state.
    async def _first_refresh(_hass: HomeAssistant) -> None:
        await coordinator.async_config_entry_first_refresh()

    if hass.state == CoreState.running:
        # HA already running (manual add or reload) — refresh immediately
        await coordinator.async_config_entry_first_refresh()
    else:
        entry.async_on_unload(async_at_started(hass, _first_refresh))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BatteryBrainConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, _platforms_for_entry(entry)
    )
