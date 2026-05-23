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
    # Initial refresh — picks up whichever battery sensors are already
    # registered. Sensors that load later are caught by the post-start refresh.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, _platforms_for_entry(entry)
    )

    # If HA is still starting up, trigger an additional refresh once it's
    # done. Battery-providing integrations (mobile_app, Zigbee, Xiaomi, …)
    # may load after BatteryBrain — without this second pass, those sensors
    # would only be picked up at the next coordinator tick (15 min later).
    if hass.state != CoreState.running:
        async def _refresh_after_start(_hass: HomeAssistant) -> None:
            await coordinator.async_refresh()

        entry.async_on_unload(async_at_started(hass, _refresh_after_start))

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BatteryBrainConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(
        entry, _platforms_for_entry(entry)
    )
