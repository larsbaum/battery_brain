"""Button platform for BatteryBrain (developer mode: force reclassification)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BatteryBrainConfigEntry
from .const import CONF_DEVELOPER_MODE, DOMAIN
from .coordinator import BatteryBrainCoordinator
from .entity import BatteryBrainEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BatteryBrainConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up BatteryBrain button entities."""
    if not entry.options.get(CONF_DEVELOPER_MODE, False):
        # Developer mode off: remove the entity left from a previous run.
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "button", DOMAIN, f"{DOMAIN}_reclassify"
        )
        if entity_id is not None:
            registry.async_remove(entity_id)
        return
    async_add_entities([ReclassifyButton(entry.runtime_data)])


class ReclassifyButton(BatteryBrainEntity, ButtonEntity):
    """Button to force reclassification of all batteries."""

    _attr_translation_key = "reclassify"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: BatteryBrainCoordinator) -> None:
        super().__init__(coordinator, "button", "reclassify")

    async def async_press(self) -> None:
        await self.coordinator.async_force_reclassify()
