"""Lightweight HA stubs so the integration can be imported without Home Assistant."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# ---- Frozen clock for deterministic tests ----------------------------

FROZEN_NOW = datetime(2025, 5, 22, 12, 0, 0, tzinfo=timezone.utc)


class FakeDtUtil:
    """Minimal stand-in for homeassistant.util.dt."""

    _now: datetime = FROZEN_NOW

    @classmethod
    def utcnow(cls) -> datetime:
        return cls._now

    @classmethod
    def set_now(cls, dt: datetime) -> None:
        cls._now = dt

    @classmethod
    def reset(cls) -> None:
        cls._now = FROZEN_NOW


# ---- Stub base classes -----------------------------------------------


class StubDataUpdateCoordinator:
    config_entry: Any = None
    data: Any = None

    def __class_getitem__(cls, item: Any) -> type:
        return cls

    def __init__(self, *a: Any, **kw: Any) -> None:
        self.data = None


class StubCoordinatorEntity:
    def __class_getitem__(cls, item: Any) -> type:
        return cls

    def __init__(self, *a: Any, **kw: Any) -> None:
        pass


class StubSensorEntity:
    pass


class StubConfigFlow:
    VERSION = 1

    def __init_subclass__(cls, *, domain: str | None = None, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        if domain is not None:
            cls.domain = domain


class StubOptionsFlowWithReload:
    pass


class StubConfigEntry:
    def __class_getitem__(cls, item: Any) -> type:
        return cls


class StubStore:
    def __class_getitem__(cls, item: Any) -> type:
        return cls

    def __init__(self, *a: Any, **kw: Any) -> None:
        pass


def _noop_decorator(func: Any) -> Any:
    return func


# ---- Build and register stub modules --------------------------------


def _mod(name: str, **attrs: Any) -> ModuleType:
    m = ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _install_stubs() -> None:
    if "homeassistant" in sys.modules:
        return

    ha_util_dt = FakeDtUtil
    ha_util = _mod("homeassistant.util", dt=ha_util_dt)
    ha = _mod("homeassistant", util=ha_util)

    class _SensorDC:
        BATTERY = "battery"

    class _BinaryDC:
        BATTERY = "battery"

    class _Platform:
        SENSOR = "sensor"
        SWITCH = "switch"

    mods: dict[str, Any] = {
        "homeassistant": ha,
        "homeassistant.util": ha_util,
        "homeassistant.util.dt": ha_util_dt,
        "homeassistant.const": _mod(
            "homeassistant.const",
            Platform=_Platform,
            ATTR_DEVICE_CLASS="device_class",
            ATTR_FRIENDLY_NAME="friendly_name",
            ATTR_UNIT_OF_MEASUREMENT="unit_of_measurement",
            STATE_ON="on",
            STATE_UNAVAILABLE="unavailable",
            STATE_UNKNOWN="unknown",
        ),
        "homeassistant.core": _mod(
            "homeassistant.core",
            HomeAssistant=type("HomeAssistant", (), {}),
            Event=type("Event", (), {}),
            callback=_noop_decorator,
        ),
        "homeassistant.config_entries": _mod(
            "homeassistant.config_entries",
            ConfigEntry=StubConfigEntry,
            ConfigFlow=StubConfigFlow,
            ConfigFlowResult=type("ConfigFlowResult", (), {}),
            OptionsFlowWithReload=StubOptionsFlowWithReload,
        ),
        "homeassistant.helpers": _mod("homeassistant.helpers"),
        "homeassistant.helpers.storage": _mod(
            "homeassistant.helpers.storage", Store=StubStore
        ),
        "homeassistant.helpers.event": _mod(
            "homeassistant.helpers.event",
            async_track_state_change_event=lambda *a, **k: (lambda: None),
        ),
        "homeassistant.helpers.update_coordinator": _mod(
            "homeassistant.helpers.update_coordinator",
            DataUpdateCoordinator=StubDataUpdateCoordinator,
            CoordinatorEntity=StubCoordinatorEntity,
        ),
        "homeassistant.helpers.entity_platform": _mod(
            "homeassistant.helpers.entity_platform",
            AddConfigEntryEntitiesCallback=type("_CB", (), {}),
        ),
        "homeassistant.helpers.entity_registry": _mod(
            "homeassistant.helpers.entity_registry"
        ),
        "homeassistant.helpers.selector": _mod(
            "homeassistant.helpers.selector"
        ),
        "homeassistant.components": _mod("homeassistant.components"),
        "homeassistant.components.sensor": _mod(
            "homeassistant.components.sensor",
            SensorEntity=StubSensorEntity,
            SensorDeviceClass=_SensorDC,
        ),
        "homeassistant.components.binary_sensor": _mod(
            "homeassistant.components.binary_sensor",
            BinarySensorDeviceClass=_BinaryDC,
        ),
        "homeassistant.components.recorder": _mod(
            "homeassistant.components.recorder"
        ),
        "homeassistant.components.recorder.statistics": _mod(
            "homeassistant.components.recorder.statistics"
        ),
        "homeassistant.components.recorder.history": _mod(
            "homeassistant.components.recorder.history"
        ),
        "homeassistant.exceptions": _mod("homeassistant.exceptions"),
    }
    sys.modules.update(mods)


_install_stubs()

# Make tests/ importable (so test modules can `from conftest import ...`)
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Make custom_components importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---- Fixtures --------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_clock() -> None:
    """Reset the fake clock before each test."""
    FakeDtUtil.reset()
