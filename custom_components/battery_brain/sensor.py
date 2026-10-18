"""Sensor platform for BatteryBrain."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BatteryBrainConfigEntry
from .coordinator import BatteryBrainCoordinator, BatteryBrainData, BatteryInfo
from .entity import BatteryBrainEntity

PARALLEL_UPDATES = 0


def _battery_attrs(batteries: Iterable[BatteryInfo]) -> dict[str, dict[str, Any]]:
    """Per-battery detail dicts, keyed by the battery's name.

    Batteries that share a name are keyed "Name (entity_id)" so that one
    doesn't overwrite the other.
    """
    batteries = list(batteries)
    name_count = Counter(info.name for info in batteries)
    return {
        (
            info.name
            if name_count[info.name] == 1
            else f"{info.name} ({info.source_entity})"
        ): {
            "category": info.category,
            "status": info.status,
            "last_value": info.last_value,
            "confidence": info.confidence,
            "stale": info.stale,
            "remaining_days": info.remaining_days,
            "estimated_empty": info.estimated_empty,
            "remaining_source": info.remaining_source,
            "source_entity": info.source_entity,
        }
        for info in batteries
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BatteryBrainConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BatteryBrain sensor entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            BatteryBrainSensor(
                coordinator, "batteries_normal", "mdi:battery-check", lambda d: d.normal
            ),
            BatteryBrainSensor(
                coordinator, "batteries_warning", "mdi:battery-alert", lambda d: d.warning
            ),
            BatteryBrainSensor(
                coordinator,
                "batteries_critical",
                "mdi:battery-alert-variant",
                lambda d: d.critical,
            ),
            BatteryBrainSensor(
                coordinator,
                "all_batteries",
                "mdi:battery-heart-variant",
                lambda d: list(d.batteries.values()),
            ),
        ]
    )


class BatteryBrainSensor(BatteryBrainEntity, SensorEntity):
    """Number of batteries in a group, with per-battery detail attributes."""

    # The per-battery details can be large and change with every battery
    # reading; recording them would bloat the database (and exceed HA's
    # 16 KB attribute limit with many batteries). Live values are unaffected.
    _unrecorded_attributes = frozenset({MATCH_ALL})

    def __init__(
        self,
        coordinator: BatteryBrainCoordinator,
        key: str,
        icon: str,
        select: Callable[[BatteryBrainData], list[BatteryInfo]],
    ) -> None:
        super().__init__(coordinator, "sensor", key)
        self._attr_translation_key = key
        self._attr_icon = icon
        self._select = select

    @property
    def available(self) -> bool:
        return self.coordinator.startup_complete and super().available

    @property
    def native_value(self) -> int:
        return len(self._select(self.coordinator.data))

    @property
    def extra_state_attributes(self) -> dict[str, dict[str, Any]]:
        return _battery_attrs(self._select(self.coordinator.data))
