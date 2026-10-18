"""Switch platform for BatteryBrain (developer mode: test mode)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BatteryBrainConfigEntry
from .const import CONF_DEVELOPER_MODE, DOMAIN, TEST_MODE_TIME_FACTOR
from .coordinator import BatteryBrainCoordinator
from .entity import BatteryBrainEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BatteryBrainConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BatteryBrain switch entities."""
    if not entry.options.get(CONF_DEVELOPER_MODE, False):
        # Developer mode off: remove the entity left from a previous run.
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "switch", DOMAIN, f"{DOMAIN}_test_mode"
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
        return
    async_add_entities([TestModeSwitch(entry.runtime_data)])


class TestModeSwitch(BatteryBrainEntity, SwitchEntity):
    """Switch to activate test mode with accelerated time."""

    _attr_translation_key = "test_mode"
    _attr_icon = "mdi:fast-forward"

    def __init__(self, coordinator: BatteryBrainCoordinator) -> None:
        super().__init__(coordinator, "switch", "test_mode")

    @property
    def is_on(self) -> bool:
        return self.coordinator.test_mode_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"time_factor": TEST_MODE_TIME_FACTOR}

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.coordinator.activate_test_mode()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.deactivate_test_mode()
        self.async_write_ha_state()
