"""Base entity for BatteryBrain."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BatteryBrainCoordinator


class BatteryBrainEntity(CoordinatorEntity[BatteryBrainCoordinator]):
    """An entity of the "BatteryBrain" service device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BatteryBrainCoordinator, platform: str, key: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{key}"
        # Fixed entity IDs (e.g. sensor.battery_brain_batteries_critical) in
        # every language, so dashboards and docs work everywhere. HA would
        # otherwise derive them from the translated name; already registered
        # entities keep their IDs.
        self.entity_id = f"{platform}.{DOMAIN}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="BatteryBrain",
            entry_type=DeviceEntryType.SERVICE,
        )
