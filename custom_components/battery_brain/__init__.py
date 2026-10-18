"""The BatteryBrain integration."""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store

from .const import CONF_DEVELOPER_MODE, LOGGER, STORAGE_KEY, STORAGE_VERSION
from .coordinator import BatteryBrainCoordinator
from .event_log import DEBUG_LOG_FILE, PRODUCTION_LOG_DIR
from .frontend import async_register_frontend

if TYPE_CHECKING:
    BatteryBrainConfigEntry = ConfigEntry[BatteryBrainCoordinator]
else:
    BatteryBrainConfigEntry = ConfigEntry


PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON]


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Migrate config entry from v1 to v2."""
    if entry.version == 1:
        new_options = dict(entry.options)
        new_data = dict(entry.data)
        dev_mode = new_data.pop(CONF_DEVELOPER_MODE, False)
        new_options.setdefault(CONF_DEVELOPER_MODE, dev_mode)
        hass.config_entries.async_update_entry(
            entry, data=new_data, options=new_options, version=2, minor_version=1
        )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: BatteryBrainConfigEntry
) -> bool:
    """Set up BatteryBrain from a config entry."""
    coordinator = BatteryBrainCoordinator(hass, entry)
    # Before the first refresh (which can take a while when importing recorder
    # history): a dashboard opened during startup should get the cards early.
    await async_register_frontend(hass)
    # Initial refresh — picks up whichever battery sensors are already
    # registered. Sensors that load later are caught by the post-start refresh.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(
        entry, PLATFORMS
    )

    # If HA is still starting up, trigger an additional refresh once it's
    # done. Battery-providing integrations (mobile_app, Zigbee, Xiaomi, …)
    # may load after BatteryBrain — without this second pass, those sensors
    # would only be picked up at the next update cycle (5 min later).
    if hass.state != CoreState.running:
        async def _refresh_after_start(_hass: HomeAssistant) -> None:
            try:
                await coordinator.async_refresh()
            finally:
                coordinator.mark_startup_complete()

        entry.async_on_unload(async_at_started(hass, _refresh_after_start))
    else:
        coordinator.mark_startup_complete()

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BatteryBrainConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )
    if unloaded:
        # The store saves with a delay; without this, a reload (e.g. after
        # changing options) would load data that is up to 5 minutes old.
        await entry.runtime_data.async_persist()
    return unloaded


async def async_remove_entry(
    hass: HomeAssistant, entry: BatteryBrainConfigEntry
) -> None:
    """Delete the collected history and logs when BatteryBrain is removed.

    Otherwise adding it again would pick up the old history (and skip the
    recorder import), and the logs would stay in the config folder.
    """
    await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_remove()
    await hass.async_add_executor_job(
        _remove_files,
        hass.config.path(PRODUCTION_LOG_DIR),
        hass.config.path(DEBUG_LOG_FILE),
    )
    LOGGER.info("Removed BatteryBrain history and logs")


def _remove_files(log_dir: str, debug_log: str) -> None:
    shutil.rmtree(log_dir, ignore_errors=True)
    parent = os.path.dirname(log_dir)
    try:
        os.rmdir(parent)  # only if nothing else is in it
    except OSError:
        pass
    for path in (debug_log, debug_log + ".old"):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
