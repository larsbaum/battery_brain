"""Config flow for BatteryBrain."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    CONF_DEVELOPER_MODE,
    DOMAIN,
    OPT_BINARY_LOW_IS_CRITICAL,
    OPT_EXCLUDE_ENTITIES,
    OPT_EXCLUDE_INTEGRATIONS,
    OPT_SCAN_BATTERY_LEVEL_ATTR,
)


class BatteryBrainConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for BatteryBrain."""

    VERSION = 2
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="BatteryBrain",
                data={},
                options={
                    CONF_DEVELOPER_MODE: user_input.get(
                        CONF_DEVELOPER_MODE, False
                    ),
                    OPT_SCAN_BATTERY_LEVEL_ATTR: user_input.get(
                        OPT_SCAN_BATTERY_LEVEL_ATTR, False
                    ),
                    OPT_BINARY_LOW_IS_CRITICAL: user_input.get(
                        OPT_BINARY_LOW_IS_CRITICAL, False
                    ),
                },
            )

        schema = vol.Schema(
            {
                vol.Optional(
                    OPT_SCAN_BATTERY_LEVEL_ATTR, default=False
                ): selector.BooleanSelector(),
                vol.Optional(
                    OPT_BINARY_LOW_IS_CRITICAL, default=False
                ): selector.BooleanSelector(),
                vol.Optional(CONF_DEVELOPER_MODE, default=False): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> BatteryBrainOptionsFlow:
        """Get the options flow handler."""
        return BatteryBrainOptionsFlow()


class BatteryBrainOptionsFlow(OptionsFlowWithReload):
    """Handle BatteryBrain options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        coordinator = self.config_entry.runtime_data
        monitored: set[str] = set()
        if coordinator and coordinator.data:
            monitored = set(coordinator.data.batteries.keys())

        currently_excluded = set(
            self.config_entry.options.get(OPT_EXCLUDE_ENTITIES, [])
        )
        all_relevant = sorted(monitored | currently_excluded)

        entity_options = []
        for eid in all_relevant:
            state = self.hass.states.get(eid)
            label = (
                state.attributes.get("friendly_name", eid)
                if state
                else eid
            )
            entity_options.append(
                selector.SelectOptionDict(value=eid, label=label)
            )

        ent_reg = er.async_get(self.hass)
        battery_platforms: set[str] = set()
        for eid in monitored | currently_excluded:
            reg_entry = ent_reg.async_get(eid)
            if reg_entry:
                battery_platforms.add(reg_entry.platform)
        battery_platforms.update(
            self.config_entry.options.get(OPT_EXCLUDE_INTEGRATIONS, [])
        )

        integration_options = [
            selector.SelectOptionDict(
                value=platform,
                label=platform.replace("_", " ").title(),
            )
            for platform in sorted(battery_platforms)
        ]

        options_schema = vol.Schema(
            {
                vol.Optional(
                    OPT_EXCLUDE_INTEGRATIONS,
                    default=self.config_entry.options.get(
                        OPT_EXCLUDE_INTEGRATIONS, []
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=integration_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    OPT_SCAN_BATTERY_LEVEL_ATTR,
                    default=self.config_entry.options.get(
                        OPT_SCAN_BATTERY_LEVEL_ATTR, False
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    OPT_BINARY_LOW_IS_CRITICAL,
                    default=self.config_entry.options.get(
                        OPT_BINARY_LOW_IS_CRITICAL, False
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    OPT_EXCLUDE_ENTITIES,
                    default=self.config_entry.options.get(
                        OPT_EXCLUDE_ENTITIES, []
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=entity_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_DEVELOPER_MODE,
                    default=self.config_entry.options.get(
                        CONF_DEVELOPER_MODE, False
                    ),
                ): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                options_schema, self.config_entry.options
            ),
        )
