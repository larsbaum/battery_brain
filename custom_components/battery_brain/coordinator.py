"""DataUpdateCoordinator for BatteryBrain."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_FRIENDLY_NAME,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .analysis import check_stale, classify_battery, derive_status
from .const import (
    CATEGORY_BINARY,
    CATEGORY_RECLASSIFY_INTERVAL,
    CATEGORY_UNKNOWN_DEFAULT,
    CONF_DEVELOPER_MODE,
    CONFIDENCE_DEFAULT,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    COORDINATOR_UPDATE_INTERVAL,
    DOMAIN,
    LOGGER,
    LOW_CONFIDENCE_DAYS,
    MEDIUM_CONFIDENCE_DAYS,
    MIN_HISTORY_DAYS,
    OPT_BINARY_LOW_IS_CRITICAL,
    OPT_EXCLUDE_ENTITIES,
    OPT_SCAN_BATTERY_LEVEL_ATTR,
    STATUS_CRITICAL,
    STATUS_NORMAL,
    STATUS_WARNING,
    TEST_MODE_TIME_FACTOR,
)
from .storage import BatteryHistoryStore, async_seed_from_recorder


@dataclass
class BatteryInfo:
    """Tracked state for a single battery."""

    name: str
    source_entity: str
    category: str = CATEGORY_UNKNOWN_DEFAULT
    status: str = STATUS_NORMAL
    last_value: float | str | None = None
    confidence: str = CONFIDENCE_DEFAULT
    stale: bool = False
    is_binary: bool = False
    unit: str | None = None


@dataclass
class BatteryBrainData:
    """Aggregated data returned by the coordinator."""

    batteries: dict[str, BatteryInfo] = field(default_factory=dict)

    @property
    def normal(self) -> list[BatteryInfo]:
        return [b for b in self.batteries.values() if b.status == STATUS_NORMAL]

    @property
    def warning(self) -> list[BatteryInfo]:
        return [b for b in self.batteries.values() if b.status == STATUS_WARNING]

    @property
    def critical(self) -> list[BatteryInfo]:
        return [
            b for b in self.batteries.values() if b.status == STATUS_CRITICAL
        ]


class BatteryBrainCoordinator(DataUpdateCoordinator[BatteryBrainData]):
    """Discover battery entities, classify, and compute health status."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=timedelta(seconds=COORDINATOR_UPDATE_INTERVAL),
        )
        self._tracked_entities: set[str] = set()
        self._unsub_state_listener: callback | None = None
        self.store = BatteryHistoryStore(hass)
        self._store_loaded = False
        self._last_aggregation: float = 0.0

        self._test_mode_active = False
        self._test_mode_start_real: float = 0.0
        self._test_mode_start_virtual: float = 0.0
        self._time_factor: int = TEST_MODE_TIME_FACTOR
        self._debug_logger: Any = None

    @property
    def developer_mode(self) -> bool:
        return bool(self.config_entry.data.get(CONF_DEVELOPER_MODE, False))

    @property
    def test_mode_active(self) -> bool:
        return self._test_mode_active

    def _restore_test_mode(self) -> None:
        """Restore test mode state from persistent storage after restart."""
        if not self.store.get_meta("test_mode_active", False):
            return
        saved_real = self.store.get_meta("test_mode_start_real", 0.0)
        saved_virtual = self.store.get_meta("test_mode_start_virtual", 0.0)
        if not saved_real or not saved_virtual:
            return
        real_now = dt_util.utcnow().timestamp()
        elapsed_while_off = real_now - saved_real
        self._test_mode_start_real = real_now
        self._test_mode_start_virtual = (
            saved_virtual + elapsed_while_off * self._time_factor
        )
        self._test_mode_active = True
        self.update_interval = timedelta(
            seconds=COORDINATOR_UPDATE_INTERVAL / self._time_factor
        )
        LOGGER.info(
            "Test mode restored (time factor: %dx, virtual time advanced by %.1f days while offline)",
            self._time_factor,
            elapsed_while_off * self._time_factor / 86400,
        )

    def activate_test_mode(self) -> None:
        real_now = dt_util.utcnow().timestamp()
        self._test_mode_start_real = real_now
        self._test_mode_start_virtual = real_now
        self._test_mode_active = True
        self.update_interval = timedelta(
            seconds=COORDINATOR_UPDATE_INTERVAL / self._time_factor
        )
        self.store.set_meta("test_mode_active", True)
        self.store.set_meta("test_mode_start_real", real_now)
        self.store.set_meta("test_mode_start_virtual", real_now)
        LOGGER.info("Test mode activated (time factor: %dx)", self._time_factor)
        self._log_test_mode_change(True)

    def deactivate_test_mode(self) -> None:
        self._test_mode_active = False
        self.update_interval = timedelta(seconds=COORDINATOR_UPDATE_INTERVAL)
        self.store.set_meta("test_mode_active", False)
        LOGGER.info("Test mode deactivated")
        self._log_test_mode_change(False)

    def _get_now_ts(self) -> float:
        real_now = dt_util.utcnow().timestamp()
        if not self._test_mode_active:
            return real_now
        elapsed = real_now - self._test_mode_start_real
        return self._test_mode_start_virtual + elapsed * self._time_factor

    def _persist_test_mode_checkpoint(self) -> None:
        """Save current virtual time anchor so restarts can resume."""
        real_now = dt_util.utcnow().timestamp()
        virtual_now = self._get_now_ts()
        self._test_mode_start_real = real_now
        self._test_mode_start_virtual = virtual_now
        self.store.set_meta("test_mode_start_real", real_now)
        self.store.set_meta("test_mode_start_virtual", virtual_now)

    # ------------------------------------------------------------------
    # Debug logging (developer mode only)
    # ------------------------------------------------------------------

    def _init_debug_logger(self) -> None:
        from .debug_log import DebugLogger

        path = self.hass.config.path(f"{DOMAIN}_debug.jsonl")
        self._debug_logger = DebugLogger(path)
        LOGGER.info("Debug log active: %s", path)
        self._debug_logger.log(
            {
                "type": "start",
                "real_ts": dt_util.utcnow().timestamp(),
                "real_iso": dt_util.utcnow().isoformat(),
                "developer_mode": True,
                "test_mode_active": self._test_mode_active,
                "time_factor": self._time_factor,
                "options": dict(self.config_entry.options),
                "config_data": {
                    k: v
                    for k, v in self.config_entry.data.items()
                    if k != "password"
                },
            }
        )

    def _ts_iso(self, ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    def _log_update(self, data: BatteryBrainData) -> None:
        if self._debug_logger is None:
            return

        now_real = dt_util.utcnow().timestamp()
        now_virtual = self._get_now_ts()

        batteries_snapshot: dict[str, Any] = {}
        for entity_id, info in data.batteries.items():
            raw = self.store.get_raw_points(entity_id)
            recent_vals = [p[1] for p in raw[-10:]] if raw else []
            batteries_snapshot[entity_id] = {
                "name": info.name,
                "value": info.last_value,
                "category": info.category,
                "status": info.status,
                "confidence": info.confidence,
                "stale": info.stale,
                "is_binary": info.is_binary,
                "unit": info.unit,
                "history_days": round(
                    self.store.get_history_days(
                        entity_id, now_ts=now_virtual
                    ),
                    2,
                ),
                "raw_points_count": len(raw),
                "daily_summaries_count": len(
                    self.store.get_daily_summaries(entity_id)
                ),
                "median_interval_s": self.store.get_median_interval(
                    entity_id
                ),
                "last_update_ts": self.store.get_last_update_ts(entity_id),
                "recent_values": recent_vals,
            }

        self._debug_logger.log(
            {
                "type": "update",
                "real_ts": now_real,
                "real_iso": self._ts_iso(now_real),
                "virtual_ts": now_virtual,
                "virtual_iso": self._ts_iso(now_virtual),
                "test_mode": self._test_mode_active,
                "time_factor": (
                    self._time_factor if self._test_mode_active else 1
                ),
                "update_interval_s": self.update_interval.total_seconds(),
                "sensors": {
                    "normal": len(data.normal),
                    "warning": len(data.warning),
                    "critical": len(data.critical),
                    "total": len(data.batteries),
                },
                "batteries": batteries_snapshot,
            }
        )

    def _log_state_change(
        self,
        entity_id: str,
        old_state_str: str | None,
        new_state_str: str,
        info: BatteryInfo,
    ) -> None:
        if self._debug_logger is None:
            return

        now_real = dt_util.utcnow().timestamp()
        self._debug_logger.log(
            {
                "type": "state_change",
                "real_ts": now_real,
                "real_iso": self._ts_iso(now_real),
                "virtual_ts": self._get_now_ts(),
                "entity_id": entity_id,
                "old_state": old_state_str,
                "new_state": new_state_str,
                "status": info.status,
                "category": info.category,
                "confidence": info.confidence,
                "stale": info.stale,
                "value": info.last_value,
            }
        )

    def _log_classification(
        self,
        entity_id: str,
        old_category: str | None,
        new_category: str,
    ) -> None:
        if self._debug_logger is None:
            return

        now_real = dt_util.utcnow().timestamp()
        values = self.store.get_all_values(entity_id)
        raw = self.store.get_raw_points(entity_id)
        self._debug_logger.log(
            {
                "type": "classification",
                "real_ts": now_real,
                "real_iso": self._ts_iso(now_real),
                "virtual_ts": self._get_now_ts(),
                "entity_id": entity_id,
                "old_category": old_category,
                "new_category": new_category,
                "history_days": round(
                    self.store.get_history_days(
                        entity_id, now_ts=self._get_now_ts()
                    ),
                    2,
                ),
                "raw_points_count": len(raw),
                "all_values_count": len(values),
                "all_values": values,
            }
        )

    def _log_test_mode_change(self, active: bool) -> None:
        if self._debug_logger is None:
            return

        now_real = dt_util.utcnow().timestamp()
        self._debug_logger.log(
            {
                "type": "test_mode_change",
                "real_ts": now_real,
                "real_iso": self._ts_iso(now_real),
                "virtual_ts": self._get_now_ts(),
                "active": active,
                "time_factor": self._time_factor,
            }
        )

    # ------------------------------------------------------------------
    # Core update loop
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> BatteryBrainData:
        if not self._store_loaded:
            await self.store.async_load()
            self._store_loaded = True
            if self.developer_mode:
                self._restore_test_mode()
                self._init_debug_logger()

        if self._test_mode_active:
            self._persist_test_mode_checkpoint()

        batteries = self._discover_batteries()
        await self._seed_new_batteries(batteries)
        self._record_current_values(batteries)
        self._classify_batteries(batteries)
        self._derive_all_status(batteries)
        self._apply_stale_overlay(batteries)
        self._update_confidence(batteries)
        self._maybe_aggregate()

        data = BatteryBrainData(batteries=batteries)
        self._update_state_listeners(set(batteries.keys()))

        self._log_update(data)
        if self._debug_logger is not None:
            await self._debug_logger.async_flush(self.hass)

        return data

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_batteries(self) -> dict[str, BatteryInfo]:
        exclude = set(
            self.config_entry.options.get(OPT_EXCLUDE_ENTITIES, [])
        )
        scan_attr = self.config_entry.options.get(
            OPT_SCAN_BATTERY_LEVEL_ATTR, False
        )
        batteries: dict[str, BatteryInfo] = {}

        for state in self.hass.states.async_all("sensor"):
            if state.entity_id in exclude:
                continue
            if (
                state.attributes.get(ATTR_DEVICE_CLASS)
                == SensorDeviceClass.BATTERY
            ):
                batteries[state.entity_id] = self._build_battery_info(
                    state.entity_id, state.state, state.attributes
                )

        for state in self.hass.states.async_all("binary_sensor"):
            if state.entity_id in exclude:
                continue
            if (
                state.attributes.get(ATTR_DEVICE_CLASS)
                == BinarySensorDeviceClass.BATTERY
            ):
                batteries[state.entity_id] = self._build_battery_info(
                    state.entity_id,
                    state.state,
                    state.attributes,
                    is_binary=True,
                )

        if scan_attr:
            for domain in ("sensor", "binary_sensor", "device_tracker"):
                for state in self.hass.states.async_all(domain):
                    if state.entity_id in exclude:
                        continue
                    if state.entity_id in batteries:
                        continue
                    if "battery_level" in state.attributes:
                        batteries[state.entity_id] = self._build_battery_info(
                            state.entity_id,
                            str(state.attributes["battery_level"]),
                            state.attributes,
                        )

        return batteries

    def _build_battery_info(
        self,
        entity_id: str,
        state_value: str,
        attributes: dict[str, Any],
        *,
        is_binary: bool = False,
    ) -> BatteryInfo:
        name = attributes.get(ATTR_FRIENDLY_NAME, entity_id)
        unit = attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        if state_value in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            last_value: float | str | None = None
        elif is_binary:
            last_value = state_value
        else:
            last_value = self._try_float(state_value)

        return BatteryInfo(
            name=name,
            source_entity=entity_id,
            category=CATEGORY_BINARY if is_binary else CATEGORY_UNKNOWN_DEFAULT,
            status=STATUS_NORMAL,
            last_value=last_value,
            confidence=CONFIDENCE_DEFAULT,
            stale=False,
            is_binary=is_binary,
            unit=unit,
        )

    @staticmethod
    def _try_float(value: str) -> float | str | None:
        try:
            return float(value)
        except (ValueError, TypeError):
            return value if value else None

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_batteries(
        self, batteries: dict[str, BatteryInfo]
    ) -> None:
        now = self._get_now_ts()
        reclassify_interval = CATEGORY_RECLASSIFY_INTERVAL
        if self._test_mode_active:
            reclassify_interval /= self._time_factor

        for entity_id, info in batteries.items():
            stored_cat = self.store.get_category(entity_id)
            last_classified = self.store.get_last_classified(entity_id)

            if (
                stored_cat
                and last_classified
                and (now - last_classified) < reclassify_interval
            ):
                info.category = stored_cat
                continue

            old_cat = stored_cat
            if info.is_binary:
                info.category = CATEGORY_BINARY
            elif (
                self.store.get_history_days(entity_id, now_ts=now)
                >= MIN_HISTORY_DAYS
            ):
                values = self.store.get_all_values(entity_id)
                info.category = classify_battery(
                    values, is_binary=False, unit=info.unit
                )
            else:
                info.category = CATEGORY_UNKNOWN_DEFAULT

            if info.category != old_cat:
                self._log_classification(entity_id, old_cat, info.category)

            self.store.set_category(entity_id, info.category, now_ts=now)

    # ------------------------------------------------------------------
    # Status derivation
    # ------------------------------------------------------------------

    def _derive_all_status(
        self, batteries: dict[str, BatteryInfo]
    ) -> None:
        binary_critical = self.config_entry.options.get(
            OPT_BINARY_LOW_IS_CRITICAL, False
        )
        for entity_id, info in batteries.items():
            info.status = self._derive_single_status(
                entity_id, info, binary_critical
            )

    def _derive_single_status(
        self,
        entity_id: str,
        info: BatteryInfo,
        binary_critical: bool,
    ) -> str:
        values = self.store.get_all_values(entity_id)
        raw_points = self.store.get_raw_points(entity_id)
        return derive_status(
            info.category,
            info.last_value,
            values,
            raw_points,
            is_binary=info.is_binary,
            binary_low_is_critical=binary_critical,
            now_ts=self._get_now_ts(),
        )

    # ------------------------------------------------------------------
    # Stale overlay
    # ------------------------------------------------------------------

    def _apply_stale_overlay(
        self, batteries: dict[str, BatteryInfo]
    ) -> None:
        now = self._get_now_ts()
        for entity_id, info in batteries.items():
            last_ts = self.store.get_last_update_ts(entity_id)
            median_iv = self.store.get_median_interval(entity_id)
            info.stale = check_stale(
                last_update_ts=last_ts,
                median_interval=median_iv,
                value_is_unavailable=info.last_value is None,
                now_ts=now,
            )
            if info.stale:
                info.status = STATUS_CRITICAL

    # ------------------------------------------------------------------
    # History integration
    # ------------------------------------------------------------------

    async def _seed_new_batteries(
        self, batteries: dict[str, BatteryInfo]
    ) -> None:
        for entity_id, info in batteries.items():
            if self.store.is_seeded(entity_id):
                continue
            try:
                await async_seed_from_recorder(
                    self.hass,
                    self.store,
                    entity_id,
                    is_binary=info.is_binary,
                )
            except Exception:
                LOGGER.warning(
                    "Failed to seed history for %s",
                    entity_id,
                    exc_info=True,
                )
                self.store.mark_seeded(entity_id)

    def _record_current_values(
        self, batteries: dict[str, BatteryInfo]
    ) -> None:
        now = self._get_now_ts()
        for entity_id, info in batteries.items():
            if info.last_value is None:
                continue
            if info.is_binary:
                val = 1.0 if info.last_value == STATE_ON else 0.0
            elif isinstance(info.last_value, (int, float)):
                val = float(info.last_value)
            else:
                continue
            self.store.add_point(entity_id, now, val)

    def _update_confidence(
        self, batteries: dict[str, BatteryInfo]
    ) -> None:
        now = self._get_now_ts()
        for entity_id, info in batteries.items():
            days = self.store.get_history_days(entity_id, now_ts=now)
            if days < MIN_HISTORY_DAYS:
                info.confidence = CONFIDENCE_DEFAULT
            elif days < LOW_CONFIDENCE_DAYS:
                info.confidence = CONFIDENCE_LOW
            elif days < MEDIUM_CONFIDENCE_DAYS:
                info.confidence = CONFIDENCE_MEDIUM
            else:
                info.confidence = CONFIDENCE_HIGH

    def _maybe_aggregate(self) -> None:
        now = self._get_now_ts()
        agg_interval = 86400
        if self._test_mode_active:
            agg_interval /= self._time_factor
        if now - self._last_aggregation > agg_interval:
            self.store.aggregate(now_ts=now)
            self._last_aggregation = now

    # ------------------------------------------------------------------
    # State-change listener
    # ------------------------------------------------------------------

    @callback
    def _update_state_listeners(self, current_entities: set[str]) -> None:
        if current_entities == self._tracked_entities:
            return

        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None

        if current_entities:
            self._unsub_state_listener = async_track_state_change_event(
                self.hass,
                list(current_entities),
                self._handle_battery_state_change,
            )
            self.config_entry.async_on_unload(
                lambda: (
                    self._unsub_state_listener()
                    if self._unsub_state_listener
                    else None
                )
            )

        self._tracked_entities = current_entities

    @callback
    def _handle_battery_state_change(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")
        if entity_id is None or new_state is None or self.data is None:
            return

        if entity_id not in self.data.batteries:
            return

        existing = self.data.batteries[entity_id]

        if new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            now = self._get_now_ts()
            if existing.is_binary:
                val = 1.0 if new_state.state == STATE_ON else 0.0
            else:
                try:
                    val = float(new_state.state)
                except (ValueError, TypeError):
                    val = None
            if val is not None:
                self.store.add_point(entity_id, now, val)

        updated = self._build_battery_info(
            entity_id,
            new_state.state,
            new_state.attributes,
            is_binary=existing.is_binary,
        )
        updated.category = existing.category
        updated.confidence = existing.confidence

        binary_critical = self.config_entry.options.get(
            OPT_BINARY_LOW_IS_CRITICAL, False
        )
        updated.status = self._derive_single_status(
            entity_id, updated, binary_critical
        )

        old_state_obj = event.data.get("old_state")
        old_state_str = old_state_obj.state if old_state_obj else None
        self._log_state_change(
            entity_id, old_state_str, new_state.state, updated
        )

        self.data.batteries[entity_id] = updated
        self.async_set_updated_data(self.data)
