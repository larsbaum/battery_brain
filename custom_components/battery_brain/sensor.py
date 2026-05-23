"""Sensor platform for BatteryBrain."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BatteryBrainConfigEntry
from .const import (
    DOMAIN,
    STATUS_CRITICAL,
    STATUS_NORMAL,
    STATUS_WARNING,
)
from .coordinator import BatteryBrainCoordinator, BatteryBrainData

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BatteryBrainConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BatteryBrain sensor entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            BatteriesNormalSensor(coordinator),
            BatteriesWarningSensor(coordinator),
            BatteriesCriticalSensor(coordinator),
            AllBatteriesSensor(coordinator),
        ]
    )


class BatteryBrainSensor(CoordinatorEntity[BatteryBrainCoordinator], SensorEntity):
    """Base class for BatteryBrain sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BatteryBrainCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="BatteryBrain",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _data(self) -> BatteryBrainData:
        return self.coordinator.data


class BatteriesNormalSensor(BatteryBrainSensor):
    """Number of batteries in normal status."""

    _attr_translation_key = "batteries_normal"
    _attr_icon = "mdi:battery-check"

    def __init__(self, coordinator: BatteryBrainCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_normal"

    @property
    def native_value(self) -> int:
        return len(self._data.normal)

    @property
    def extra_state_attributes(self) -> dict[str, dict]:
        attrs: dict[str, dict] = {}
        for info in self._data.normal:
            attrs[info.name] = {
                "category": info.category,
                "status": info.status,
                "last_value": info.last_value,
                "confidence": info.confidence,
                "stale": info.stale,
                "source_entity": info.source_entity,
            }
        return attrs


class BatteriesWarningSensor(BatteryBrainSensor):
    """Number of batteries in warning status."""

    _attr_translation_key = "batteries_warning"
    _attr_icon = "mdi:battery-alert"

    def __init__(self, coordinator: BatteryBrainCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_warning"

    @property
    def native_value(self) -> int:
        return len(self._data.warning)

    @property
    def extra_state_attributes(self) -> dict[str, dict]:
        attrs: dict[str, dict] = {}
        for info in self._data.warning:
            attrs[info.name] = {
                "category": info.category,
                "status": info.status,
                "last_value": info.last_value,
                "confidence": info.confidence,
                "stale": info.stale,
                "source_entity": info.source_entity,
            }
        return attrs


class BatteriesCriticalSensor(BatteryBrainSensor):
    """Number of batteries in critical status."""

    _attr_translation_key = "batteries_critical"
    _attr_icon = "mdi:battery-alert-variant"

    def __init__(self, coordinator: BatteryBrainCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_critical"

    @property
    def native_value(self) -> int:
        return len(self._data.critical)

    @property
    def extra_state_attributes(self) -> dict[str, dict]:
        attrs: dict[str, dict] = {}
        for info in self._data.critical:
            attrs[info.name] = {
                "category": info.category,
                "status": info.status,
                "last_value": info.last_value,
                "confidence": info.confidence,
                "stale": info.stale,
                "source_entity": info.source_entity,
            }
        return attrs


class AllBatteriesSensor(BatteryBrainSensor):
    """Total number of monitored batteries with per-battery detail attributes."""

    _attr_translation_key = "all_batteries"
    _attr_icon = "mdi:battery-heart-variant"

    def __init__(self, coordinator: BatteryBrainCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_all"

    @property
    def native_value(self) -> int:
        return len(self._data.batteries)

    @property
    def extra_state_attributes(self) -> dict[str, dict]:
        attrs: dict[str, dict] = {}
        for info in self._data.batteries.values():
            attrs[info.name] = {
                "category": info.category,
                "status": info.status,
                "last_value": info.last_value,
                "confidence": info.confidence,
                "stale": info.stale,
                "source_entity": info.source_entity,
            }
        return attrs
