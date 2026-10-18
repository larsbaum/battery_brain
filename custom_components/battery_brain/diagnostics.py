"""Diagnostics support for BatteryBrain.

Settings → Devices & services → BatteryBrain → ⋮ → Download diagnostics.
Contains the options, the current evaluation of every battery and the
stored history — everything needed to reproduce a classification or a
remaining-lifetime estimate. Battery data only; nothing to redact. The
history's point lists are compact JSON strings (see compact_history()).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from . import BatteryBrainConfigEntry
from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BatteryBrainConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    integration = await async_get_integration(hass, DOMAIN)
    batteries = coordinator.data.batteries if coordinator.data else {}
    return {
        "version": str(integration.version),
        "options": dict(entry.options),
        "startup_complete": coordinator.startup_complete,
        "test_mode_active": coordinator.test_mode_active,
        "batteries": {
            entity_id: asdict(info) for entity_id, info in batteries.items()
        },
        # See compact_history(): keeps the file small enough to attach to an
        # issue (26 MB for 324 batteries as plain JSON, ~7 MB like this).
        "history_format": HISTORY_FORMAT,
        "history": compact_history(coordinator.store.as_dict()),
    }


# Version of the "history" layout in the diagnostics file.
HISTORY_FORMAT = 2


def compact_history(history: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per battery, the point lists as one compact JSON string each.

    HA writes diagnostics indented, one number per line; a year of history
    for hundreds of batteries made the file larger than GitHub accepts as
    an attachment. ``raw_points`` becomes ``[[ts, value], …]`` (whole
    seconds), ``daily_summaries`` ``[[date, min, mean, max, count], …]``.
    expand_history() turns it back into the store layout.
    """
    compact: dict[str, dict[str, Any]] = {}
    for entity_id, data in history.items():
        entry = dict(data)
        entry["raw_points"] = json.dumps(
            [[round(ts), value] for ts, value in data.get("raw_points", [])],
            separators=(",", ":"),
        )
        entry["daily_summaries"] = json.dumps(
            [
                [s["date"], s["min"], s["mean"], s["max"], s["count"]]
                for s in data.get("daily_summaries", [])
            ],
            separators=(",", ":"),
        )
        compact[entity_id] = entry
    return compact


def expand_history(history: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The store layout from compact_history() (older files pass through)."""
    expanded: dict[str, dict[str, Any]] = {}
    for entity_id, data in history.items():
        entry = dict(data)
        if isinstance(entry.get("raw_points"), str):
            entry["raw_points"] = json.loads(entry["raw_points"])
        if isinstance(entry.get("daily_summaries"), str):
            entry["daily_summaries"] = [
                {"date": d, "min": lo, "mean": mean, "max": hi, "count": n}
                for d, lo, mean, hi, n in json.loads(entry["daily_summaries"])
            ]
        expanded[entity_id] = entry
    return expanded
