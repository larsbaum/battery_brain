"""Config flow for BatteryBrain."""

from __future__ import annotations

from typing import Any

# Home Assistant ≥ 2026.10 validates with probatio and aliases voluptuous
# to it for custom integrations; older versions ship voluptuous itself.
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.loader import async_get_integrations

from .const import (
    ALERT_MODE_SMART,
    ALERT_MODE_THRESHOLD,
    CONF_DEVELOPER_MODE,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
    OPT_ALERT_MODE,
    OPT_BINARY_LOW_IS_CRITICAL,
    OPT_EXCLUDE_ENTITIES,
    OPT_EXCLUDE_INTEGRATIONS,
    OPT_INCLUDE_VOLTAGE_SENSORS,
    OPT_SCAN_BATTERY_LEVEL_ATTR,
    OPT_WARNING_THRESHOLD,
    WARNING_THRESHOLD_MAX,
    WARNING_THRESHOLD_MIN,
)

# Options and their defaults. Options are stored flat (as before 1.0);
# the sections only group them in the form.
DEFAULT_OPTIONS: dict[str, Any] = {
    OPT_SCAN_BATTERY_LEVEL_ATTR: False,
    OPT_INCLUDE_VOLTAGE_SENSORS: True,
    OPT_EXCLUDE_INTEGRATIONS: [],
    OPT_EXCLUDE_ENTITIES: [],
    OPT_ALERT_MODE: ALERT_MODE_SMART,
    OPT_WARNING_THRESHOLD: DEFAULT_WARNING_THRESHOLD,
    OPT_BINARY_LOW_IS_CRITICAL: False,
    CONF_DEVELOPER_MODE: False,
}

SECTION_DISCOVERY = "discovery"
SECTION_EXCLUSIONS = "exclusions"
SECTION_ALERTS = "alerts"
SECTION_ADVANCED = "advanced"
SECTIONS: dict[str, tuple[str, ...]] = {
    SECTION_DISCOVERY: (OPT_SCAN_BATTERY_LEVEL_ATTR, OPT_INCLUDE_VOLTAGE_SENSORS),
    SECTION_EXCLUSIONS: (OPT_EXCLUDE_INTEGRATIONS, OPT_EXCLUDE_ENTITIES),
    SECTION_ALERTS: (
        OPT_ALERT_MODE,
        OPT_WARNING_THRESHOLD,
        OPT_BINARY_LOW_IS_CRITICAL,
    ),
    SECTION_ADVANCED: (CONF_DEVELOPER_MODE,),
}


class BatteryBrainConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for BatteryBrain."""

    VERSION = 2
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup; everything is discovered automatically."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="BatteryBrain", data={}, options=dict(DEFAULT_OPTIONS)
            )
        return self.async_show_form(step_id="user")

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
        """Manage the options, grouped into sections."""
        if user_input is not None:
            options = dict(self.config_entry.options)
            for name, keys in SECTIONS.items():
                if name not in user_input:
                    continue
                values = user_input[name]
                for key in keys:
                    # A cleared multi-select or switched-off boolean may be
                    # omitted from the input; other fields keep their default.
                    default = DEFAULT_OPTIONS[key]
                    if isinstance(default, list):
                        default = []
                    elif isinstance(default, bool):
                        default = False
                    options[key] = values.get(key, default)
            return self.async_create_entry(data=options)

        current = {**DEFAULT_OPTIONS, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(SECTION_DISCOVERY): section(
                    vol.Schema(
                        {
                            vol.Optional(
                                OPT_SCAN_BATTERY_LEVEL_ATTR
                            ): selector.BooleanSelector(),
                            vol.Optional(
                                OPT_INCLUDE_VOLTAGE_SENSORS
                            ): selector.BooleanSelector(),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_EXCLUSIONS): section(
                    vol.Schema(
                        {
                            vol.Optional(OPT_EXCLUDE_INTEGRATIONS): _multi_select(
                                await self._integration_options(current)
                            ),
                            vol.Optional(OPT_EXCLUDE_ENTITIES): _multi_select(
                                self._entity_options(current)
                            ),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_ALERTS): section(
                    vol.Schema(
                        {
                            vol.Optional(OPT_ALERT_MODE): selector.SelectSelector(
                                selector.SelectSelectorConfig(
                                    options=[ALERT_MODE_SMART, ALERT_MODE_THRESHOLD],
                                    mode=selector.SelectSelectorMode.LIST,
                                    translation_key=OPT_ALERT_MODE,
                                )
                            ),
                            vol.Optional(
                                OPT_WARNING_THRESHOLD
                            ): selector.NumberSelector(
                                selector.NumberSelectorConfig(
                                    min=WARNING_THRESHOLD_MIN,
                                    max=WARNING_THRESHOLD_MAX,
                                    step=1,
                                    unit_of_measurement="%",
                                    mode=selector.NumberSelectorMode.SLIDER,
                                )
                            ),
                            vol.Optional(
                                OPT_BINARY_LOW_IS_CRITICAL
                            ): selector.BooleanSelector(),
                        }
                    ),
                    {"collapsed": False},
                ),
                vol.Required(SECTION_ADVANCED): section(
                    vol.Schema(
                        {
                            vol.Optional(
                                CONF_DEVELOPER_MODE
                            ): selector.BooleanSelector(),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )
        suggested = {
            name: {key: current[key] for key in keys}
            for name, keys in SECTIONS.items()
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
        )

    def _monitored(self) -> set[str]:
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None or coordinator.data is None:
            return set()
        return set(coordinator.data.batteries)

    def _entity_options(
        self, current: dict[str, Any]
    ) -> list[selector.SelectOptionDict]:
        """Monitored batteries plus already excluded entities."""
        options = []
        for entity_id in self._monitored() | set(current[OPT_EXCLUDE_ENTITIES]):
            state = self.hass.states.get(entity_id)
            name = state.attributes.get("friendly_name") if state else None
            options.append(
                selector.SelectOptionDict(
                    value=entity_id,
                    label=f"{name} ({entity_id})" if name else entity_id,
                )
            )
        return sorted(options, key=lambda o: o["label"].casefold())

    async def _integration_options(
        self, current: dict[str, Any]
    ) -> list[selector.SelectOptionDict]:
        """Integrations that provide batteries, plus already excluded ones."""
        ent_reg = er.async_get(self.hass)
        domains = set(current[OPT_EXCLUDE_INTEGRATIONS])
        for entity_id in self._monitored() | set(current[OPT_EXCLUDE_ENTITIES]):
            if entry := ent_reg.async_get(entity_id):
                domains.add(entry.platform)
        integrations = await async_get_integrations(self.hass, domains)
        options = []
        for domain in domains:
            integration = integrations.get(domain)
            name = getattr(integration, "name", None) or domain.replace(
                "_", " "
            ).title()
            options.append(selector.SelectOptionDict(value=domain, label=name))
        return sorted(options, key=lambda o: o["label"].casefold())


def _multi_select(
    options: list[selector.SelectOptionDict],
) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )
