"""The BatteryBrain integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

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
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, _platforms_for_entry(entry)
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BatteryBrainConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, _platforms_for_entry(entry)
    )
