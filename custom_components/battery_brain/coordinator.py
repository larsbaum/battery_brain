"""DataUpdateCoordinator for BatteryBrain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_FRIENDLY_NAME,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .analysis import (
    check_stale,
    classify_battery,
    derive_status,
    detect_binary_replacements,
    detect_replacements,
    estimate_remaining,
    is_unconfirmed_drop,
    is_voltage_unit,
)
from .const import (
    ALERT_MODE_SMART,
    ALERT_MODE_THRESHOLD,
    ATTR_BATTERY_LEVEL,
    CATEGORY_BINARY,
    CATEGORY_CONFIRMATIONS,
    CATEGORY_LINEAR,
    CATEGORY_LOW_STABLE,
    CATEGORY_PLATEAU_CLIFF,
    CATEGORY_RECLASSIFY_INTERVAL,
    CATEGORY_UNKNOWN_DEFAULT,
    CATEGORY_VOLTAGE,
    CONF_DEVELOPER_MODE,
    CONFIDENCE_DEFAULT,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    COORDINATOR_UPDATE_INTERVAL,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
    ESTIMATE_MAX_DAYS,
    LOGGER,
    LOW_CONFIDENCE_DAYS,
    MEDIUM_CONFIDENCE_DAYS,
    MIN_HISTORY_DAYS,
    OPT_ALERT_MODE,
    OPT_BINARY_LOW_IS_CRITICAL,
    OPT_EXCLUDE_ENTITIES,
    OPT_EXCLUDE_INTEGRATIONS,
    OPT_INCLUDE_VOLTAGE_SENSORS,
    OPT_SCAN_BATTERY_LEVEL_ATTR,
    OPT_WARNING_THRESHOLD,
    ORPHAN_GRACE_MINUTES,
    SIMILAR_RATE_MIN_DAYS,
    SIMILAR_RATE_MIN_DROP,
    PRODUCTION_SNAPSHOT_INTERVAL,
    REMAINING_MEASURED,
    REMAINING_STALE,
    STATUS_CRITICAL,
    STATUS_NORMAL,
    STATUS_WARNING,
    TEST_MODE_TIME_FACTOR,
    TEXT_BATTERY_LEVELS,
    TEXT_LOW_LEVELS,
    VOLTAGE_DISCOVERY_MAX,
    VOLTAGE_DISCOVERY_MIN,
)
from .event_log import DEBUG_LOG_FILE, PRODUCTION_LOG_DIR, DebugLog, ProductionLog
from .lifetime import Household, fallback_remaining
from .storage import (
    SOURCE_ATTRIBUTE,
    SOURCE_STATE,
    BatteryHistoryStore,
    async_seed_from_recorder,
)

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, State


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
    remaining_days: float | None = None
    estimated_empty: str | None = None
    # measured / history / similar / typical / stale (see const.REMAINING_*)
    remaining_source: str | None = None
    # Attribute the value is read from (None: the entity's state).
    source_attr: str | None = None
    # "manufacturer|model" of the device, to learn from identical devices.
    device_model: str | None = None


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
        self.store = BatteryHistoryStore(hass)
        self._store_loaded = False
        self._tracked_entities: set[str] = set()
        self._unsub_state_listener: CALLBACK_TYPE | None = None
        config_entry.async_on_unload(self._async_unsubscribe_state_listener)
        self._last_aggregation = 0.0
        self._last_snapshot_log = 0.0
        self._reclassify_reason: str | None = None
        self._startup_complete = False

        self._test_mode_active = False
        self._test_mode_start_real = 0.0
        self._test_mode_start_virtual = 0.0
        self._time_factor: int = TEST_MODE_TIME_FACTOR

        self._household = Household()
        self._production_log: ProductionLog | None = None
        self._debug_log: DebugLog | None = None

    @property
    def developer_mode(self) -> bool:
        return bool(self.config_entry.options.get(CONF_DEVELOPER_MODE, False))

    @property
    def test_mode_active(self) -> bool:
        return self._test_mode_active

    @property
    def startup_complete(self) -> bool:
        return self._startup_complete

    def mark_startup_complete(self) -> None:
        self._startup_complete = True
        if self.data is not None:
            self.async_update_listeners()

    async def async_force_reclassify(self) -> None:
        """Reset classification timestamps and trigger an immediate update."""
        self.store.reset_all_last_classified()
        self._reclassify_reason = "manual"
        LOGGER.info("Forced reclassification triggered")
        await self.async_refresh()

    async def async_persist(self) -> None:
        """Write history and logs to disk now (before unload/reload)."""
        if self._store_loaded:
            await self.store.async_save_immediate()
        await self._async_flush_logs()

    # ------------------------------------------------------------------
    # Test mode (developer mode only): virtual time runs 200× faster.
    # It always starts off; virtual timestamps end up in the stored
    # history, so it must only be used with simulated batteries.
    # ------------------------------------------------------------------

    def activate_test_mode(self) -> None:
        real_now = dt_util.utcnow().timestamp()
        self._test_mode_start_real = real_now
        self._test_mode_start_virtual = real_now
        self._test_mode_active = True
        self.update_interval = timedelta(
            seconds=COORDINATOR_UPDATE_INTERVAL / self._time_factor
        )
        LOGGER.info("Test mode activated (time factor: %dx)", self._time_factor)
        self._log_event(
            "test_mode_change",
            production=False,
            active=True,
            time_factor=self._time_factor,
        )

    def deactivate_test_mode(self) -> None:
        self._test_mode_active = False
        self.update_interval = timedelta(seconds=COORDINATOR_UPDATE_INTERVAL)
        LOGGER.info("Test mode deactivated")
        self._log_event(
            "test_mode_change",
            production=False,
            active=False,
            time_factor=self._time_factor,
        )

    def _get_now_ts(self) -> float:
        real_now = dt_util.utcnow().timestamp()
        if not self._test_mode_active:
            return real_now
        elapsed = real_now - self._test_mode_start_real
        return self._test_mode_start_virtual + elapsed * self._time_factor

    def _scaled(self, seconds: float) -> float:
        """An interval in (possibly virtual) store time."""
        if self._test_mode_active:
            return seconds / self._time_factor
        return seconds

    # ------------------------------------------------------------------
    # Core update loop
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> BatteryBrainData:
        if not self._store_loaded:
            await self.store.async_load()
            self._store_loaded = True
            self._init_logs()

        # Write the logs of the last cycle and of live events now: no await
        # may come between reading the states and returning the result,
        # otherwise live values processed meanwhile would be overwritten
        # with the older ones read here.
        await self._async_flush_logs()

        now = self._get_now_ts()
        previous = self.data.batteries if self.data is not None else {}
        manual = self._reclassify_reason == "manual"
        self._reclassify_reason = None

        batteries = self._discover_batteries()
        seeded = await self._seed_new_batteries(batteries)
        if seeded:
            # The import awaited the recorder: read the states again.
            batteries = self._discover_batteries()
            # Imported history older than HISTORY_RAW_DAYS becomes daily means
            # right away: the first classification must see the same data as
            # every later one (hourly points for a year classified
            # differently, so archetypes changed hours after installing).
            self.store.aggregate(now_ts=now)
            self._last_aggregation = now
        self._household = self._build_household(batteries, previous)

        for entity_id, info in batteries.items():
            self.store.ensure_source(
                entity_id,
                SOURCE_ATTRIBUTE if info.source_attr else SOURCE_STATE,
                now_ts=now,
            )
            self._ingest(entity_id, info, now)
            self._classify(entity_id, info, now, manual, previous.get(entity_id))
            self._sync_replacements(entity_id, info, now)
            self._evaluate(entity_id, info, previous.get(entity_id))
            info.confidence = self._confidence(entity_id, now)

        if now - self._last_aggregation > self._scaled(86400):
            self.store.aggregate(now_ts=now)
            self._last_aggregation = now

        data = BatteryBrainData(batteries=batteries)
        self._update_state_listener(set(batteries))
        self._log_update(data)  # written at the start of the next cycle
        return data

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_batteries(self) -> dict[str, BatteryInfo]:
        options = self.config_entry.options
        exclude = set(options.get(OPT_EXCLUDE_ENTITIES, []))
        exclude_integrations = set(options.get(OPT_EXCLUDE_INTEGRATIONS, []))
        include_voltage = options.get(OPT_INCLUDE_VOLTAGE_SENSORS, True)
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)

        def add(state: State, **kwargs: Any) -> None:
            """Add the battery unless excluded; note its device model."""
            entry = ent_reg.async_get(state.entity_id)
            if state.entity_id in exclude or (
                entry is not None and entry.platform in exclude_integrations
            ):
                return
            if self._is_orphan(state, entry):
                return
            info = self._build_battery_info(state, **kwargs)
            device = (
                dev_reg.async_get(entry.device_id)
                if entry is not None and entry.device_id
                else None
            )
            if device is not None and device.model:
                info.device_model = f"{device.manufacturer or ''}|{device.model}"
            batteries[state.entity_id] = info

        batteries: dict[str, BatteryInfo] = {}
        for state in self.hass.states.async_all(("sensor", "binary_sensor")):
            device_class = state.attributes.get(ATTR_DEVICE_CLASS)
            if state.domain == "binary_sensor":
                if device_class == BinarySensorDeviceClass.BATTERY:
                    add(state, is_binary=True)
            elif device_class == SensorDeviceClass.BATTERY or (
                device_class == SensorDeviceClass.VOLTAGE
                and include_voltage
                and self._is_battery_voltage(state)
            ):
                add(state)

        if options.get(OPT_SCAN_BATTERY_LEVEL_ATTR, False):
            for state in self.hass.states.async_all(
                ("sensor", "binary_sensor", "device_tracker")
            ):
                if (
                    state.entity_id not in batteries
                    and ATTR_BATTERY_LEVEL in state.attributes
                ):
                    add(state, source_attr=ATTR_BATTERY_LEVEL)

        return batteries

    def _is_orphan(self, state: State, entry: Any) -> bool:
        """An entity nothing provides any more (left behind in the registry).

        HA restores registry entities as ``unavailable`` with
        ``restored: true`` until their integration provides them. If that
        still holds ORPHAN_GRACE_MINUTES later and the entity has no config
        entry (YAML, no longer defined), its config entry is gone, or the
        config entry is loaded but doesn't provide it (device removed), it
        is an orphan and would stay "unreachable" (critical) forever.
        Entities of a config entry that failed to load stay monitored:
        their batteries really are unreachable.
        """
        if state.attributes.get("restored") is not True:
            return False
        updated = getattr(state, "last_updated", None)
        if updated is None or (
            dt_util.utcnow() - updated
        ).total_seconds() < ORPHAN_GRACE_MINUTES * 60:
            return False
        config_entry_id = getattr(entry, "config_entry_id", None)
        if config_entry_id is None:
            return True
        config_entry = self.hass.config_entries.async_get_entry(config_entry_id)
        return config_entry is None or config_entry.state is ConfigEntryState.LOADED

    def _is_battery_voltage(self, state: State) -> bool:
        """Voltage sensor in battery range (or already tracked)."""
        if self.store.has_battery(state.entity_id):
            return True
        try:
            volts = float(state.state)
        except (ValueError, TypeError):
            return False
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit and unit.lower() == "mv":
            volts /= 1000
        return VOLTAGE_DISCOVERY_MIN < volts <= VOLTAGE_DISCOVERY_MAX

    @staticmethod
    def _build_battery_info(
        state: State,
        *,
        is_binary: bool = False,
        source_attr: str | None = None,
    ) -> BatteryInfo:
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            last_value: float | str | None = None
        elif is_binary:
            last_value = state.state
        elif source_attr is not None:
            last_value = _try_float(state.attributes.get(source_attr))
        else:
            last_value = _try_float(state.state)

        return BatteryInfo(
            name=state.attributes.get(ATTR_FRIENDLY_NAME, state.entity_id),
            source_entity=state.entity_id,
            category=CATEGORY_BINARY if is_binary else CATEGORY_UNKNOWN_DEFAULT,
            last_value=last_value,
            is_binary=is_binary,
            # battery_level attributes are percentages; the host entity's
            # unit (e.g. °C) has nothing to do with them.
            unit="%" if source_attr else state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
            source_attr=source_attr,
        )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def _seed_new_batteries(self, batteries: dict[str, BatteryInfo]) -> bool:
        """Import recorder history for batteries seen for the first time.

        Attribute-based batteries are not imported: the recorder history
        of their entity is the host entity's state, not the battery level.
        Returns True if history was imported.
        """
        new = [
            info
            for entity_id, info in batteries.items()
            if not self.store.is_seeded(entity_id)
        ]
        for info in new:
            if info.source_attr is not None:
                self.store.mark_seeded(info.source_entity)
        to_seed = [i.source_entity for i in new if i.source_attr is None]
        if not to_seed:
            return False
        try:
            await async_seed_from_recorder(
                self.hass,
                self.store,
                to_seed,
                {i.source_entity for i in new if i.is_binary},
            )
        except Exception:  # noqa: BLE001 - never block the update cycle
            LOGGER.warning("Failed to seed battery history", exc_info=True)
            for entity_id in to_seed:
                self.store.mark_seeded(entity_id)
        return True

    def _ingest(self, entity_id: str, info: BatteryInfo, now: float) -> None:
        """Mark the battery alive; record its value (only when it changed)."""
        if info.last_value is None:
            return
        self.store.set_last_seen(entity_id, now)
        value = _battery_level(info)
        if value is None:
            return
        raw = self.store.get_raw_points(entity_id)
        if not raw or raw[-1][1] != value:
            self.store.add_point(entity_id, now, value)

    def _confidence(self, entity_id: str, now: float) -> str:
        days = self.store.get_history_days(entity_id, now_ts=now)
        if days < MIN_HISTORY_DAYS:
            return CONFIDENCE_DEFAULT
        if days < LOW_CONFIDENCE_DAYS:
            return CONFIDENCE_LOW
        if days < MEDIUM_CONFIDENCE_DAYS:
            return CONFIDENCE_MEDIUM
        return CONFIDENCE_HIGH

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(
        self,
        entity_id: str,
        info: BatteryInfo,
        now: float,
        manual: bool,
        previous: BatteryInfo | None,
    ) -> None:
        stored = self.store.get_category(entity_id)
        last_classified = self.store.get_last_classified(entity_id)
        if (
            stored
            and last_classified
            and now - last_classified < self._scaled(CATEGORY_RECLASSIFY_INTERVAL)
        ):
            info.category = stored
            return

        all_points = self.store.get_all_points(entity_id)
        if info.is_binary:
            result = CATEGORY_BINARY
        elif is_voltage_unit(info.unit):
            # The unit is conclusive; no need to wait for MIN_HISTORY_DAYS
            # (percentage thresholds would rate 2.9 V as critical).
            result = CATEGORY_VOLTAGE
        elif self.store.get_history_days(entity_id, now_ts=now) >= MIN_HISTORY_DAYS:
            result = classify_battery(
                [p[1] for p in all_points],
                unit=info.unit,
                points=all_points,
                now_ts=now,
            )
        else:
            result = CATEGORY_UNKNOWN_DEFAULT

        if stored is None:
            reason = "first"
        elif manual:
            reason = "manual"
        else:
            reason = "interval"
        info.category = self._confirmed_category(
            entity_id, stored, result, immediate=reason != "interval"
        )

        # Production log: hourly re-checks only when something happens (the
        # archetype changed or another one waits for confirmation); the
        # hourly "update" snapshot has every battery's category anyway.
        # With hundreds of batteries the unchanged ones made up a third of
        # the log. The debug log keeps all of them.
        self._log_event(
            "classification",
            production=reason != "interval"
            or info.category != stored
            or result != info.category,
            entity_id=entity_id,
            old_category=stored,
            new_category=info.category,
            category_changed=info.category != stored,
            candidate=result,
            reason=reason,
            old_status=previous.status if previous else None,
            current_value=info.last_value,
            history_days=round(self.store.get_history_days(entity_id, now_ts=now), 2),
            raw_points_count=len(self.store.get_raw_points(entity_id)),
            debug_extra={
                "all_values_count": len(all_points),
                "all_values": [p[1] for p in all_points],
            },
        )
        self.store.set_category(entity_id, info.category, now_ts=now)

    def _sync_replacements(
        self, entity_id: str, info: BatteryInfo, now: float
    ) -> None:
        """Store the battery replacements seen in the history (every cycle)."""
        all_points = self.store.get_all_points(entity_id)
        if info.is_binary:
            detected: list[float] | None = detect_binary_replacements(all_points)
        elif info.category in (
            CATEGORY_LINEAR,
            CATEGORY_PLATEAU_CLIFF,
            CATEGORY_LOW_STABLE,
        ):
            detected = detect_replacements(all_points)
        else:
            detected = None  # rises are charging, not new batteries
        self.store.sync_replacements(
            entity_id, detected, all_points[0][0] if all_points else now
        )

    def _confirmed_category(
        self, entity_id: str, stored: str | None, result: str, *, immediate: bool
    ) -> str:
        """Apply the classification hysteresis (CATEGORY_CONFIRMATIONS)."""
        if immediate or stored in (None, CATEGORY_UNKNOWN_DEFAULT) or result == stored:
            self.store.set_pending_category(entity_id, None)
            return result
        pending, count = self.store.get_pending_category(entity_id)
        count = count + 1 if pending == result else 1
        if count >= CATEGORY_CONFIRMATIONS:
            self.store.set_pending_category(entity_id, None)
            return result
        self.store.set_pending_category(entity_id, result, count)
        return stored

    # ------------------------------------------------------------------
    # Status, stale overlay and remaining lifetime (one battery)
    # ------------------------------------------------------------------

    def _evaluate(
        self, entity_id: str, info: BatteryInfo, previous: BatteryInfo | None
    ) -> None:
        now = self._get_now_ts()
        all_points = self.store.get_all_points(entity_id)
        raw_points = self.store.get_raw_points(entity_id)

        level = _battery_level(info)
        rated = (
            # Text levels ("low", …) are rated by their percent equivalent.
            level if isinstance(info.last_value, str) and not info.is_binary
            else info.last_value
        )
        if (
            not info.is_binary
            and isinstance(level, (int, float))
            and raw_points
            and raw_points[-1][1] == level
            and is_unconfirmed_drop(raw_points, now, info.unit)
        ):
            # A sudden drop (e.g. a single 0 % from a Z-Wave device) only
            # counts once confirmed; until then rate the reading before.
            glitch_ts = raw_points[-1][0]
            raw_points = raw_points[:-1]
            all_points = [p for p in all_points if p[0] != glitch_ts]
            level = rated = raw_points[-1][1]
        options = self.config_entry.options
        info.status = derive_status(
            info.category,
            rated,
            [p[1] for p in all_points],
            raw_points,
            is_binary=info.is_binary,
            binary_low_is_critical=options.get(OPT_BINARY_LOW_IS_CRITICAL, False),
            now_ts=now,
            all_points=all_points,
            unit=info.unit,
            alert_threshold=_alert_threshold(options),
            text_low=_is_text_low(info),
        )

        info.stale = check_stale(
            last_update_ts=self.store.get_last_seen_ts(entity_id)
            or self.store.get_last_update_ts(entity_id),
            median_interval=self.store.get_median_interval(entity_id),
            value_is_unavailable=info.last_value is None,
            now_ts=now,
        )
        if info.stale:
            info.status = STATUS_CRITICAL
        if info.stale != (previous.stale if previous else False):
            self._log_event(
                "stale_change",
                entity_id=entity_id,
                stale=info.stale,
                status=info.status,
                category=info.category,
                value=info.last_value,
            )

        # Remaining lifetime: always estimated. Unavailable/stale batteries
        # use their last known reading.
        if level is None and raw_points:
            level = raw_points[-1][1]
        remaining: float | None = None
        source = REMAINING_MEASURED
        if level is not None and not info.is_binary:
            remaining = estimate_remaining(
                info.category,
                level,
                raw_points,
                all_points,
                now_ts=now,
                unit=info.unit,
            )
        if remaining is None:
            remaining, source = fallback_remaining(
                entity_id=entity_id,
                category=info.category,
                level=level,
                unit=info.unit,
                raw_points=raw_points,
                all_points=all_points,
                replacements=self.store.get_replacements(entity_id),
                first_seen=self.store.get_first_seen(entity_id) or now,
                now=now,
                model=info.device_model,
                household=self._household,
            )
        if info.stale:
            source = REMAINING_STALE
        remaining = min(max(remaining, 0.0), ESTIMATE_MAX_DAYS)
        info.remaining_days = round(remaining, 1)
        info.remaining_source = source
        # remaining is in (possibly virtual) store time; convert to real time.
        empty_at = dt_util.utcnow() + timedelta(
            seconds=self._scaled(remaining * 86400)
        )
        info.estimated_empty = dt_util.as_local(empty_at).date().isoformat()

    def _build_household(
        self,
        batteries: dict[str, BatteryInfo],
        previous: dict[str, BatteryInfo],
    ) -> Household:
        """Lifetimes and drain rates of all batteries, to learn from similar ones.

        Lifetimes come from stored replacements, drain rates from the last
        cycle's measured linear estimates (never from fallback estimates).
        """
        household = Household()
        for entity_id, info in batteries.items():
            household.add_replacements(
                entity_id,
                info.device_model,
                self.store.get_category(entity_id) or info.category,
                self.store.get_replacements(entity_id),
            )
        for entity_id, info in previous.items():
            if (
                info.remaining_source == REMAINING_MEASURED
                and info.category == CATEGORY_LINEAR
                and isinstance(info.last_value, (int, float))
                and info.remaining_days
            ):
                rate = self._average_drain_rate(entity_id) or (
                    info.last_value / info.remaining_days
                )
                household.rates.append((entity_id, info.device_model, rate))
        return household

    def _average_drain_rate(self, entity_id: str) -> float | None:
        """pp per day since the current battery was inserted, if measurable.

        A full battery of the same model is estimated from this, not from
        the current slope: a peer whose drop speeds up towards the end
        (common for coin cells) would make a fresh battery look empty in
        weeks (IKEA remote: 48 days instead of ~600).
        """
        points = self.store.get_all_points(entity_id)
        replacements = self.store.get_replacements(entity_id)
        start = replacements[-1] if replacements else None
        current = [p for p in points if start is None or p[0] >= start]
        if len(current) < 2:
            return None
        days = (current[-1][0] - current[0][0]) / 86400
        drop = current[0][1] - current[-1][1]
        if days < SIMILAR_RATE_MIN_DAYS or drop < SIMILAR_RATE_MIN_DROP:
            return None
        return drop / days

    # ------------------------------------------------------------------
    # State-change listener
    # ------------------------------------------------------------------

    @callback
    def _update_state_listener(self, entity_ids: set[str]) -> None:
        if entity_ids == self._tracked_entities:
            return
        self._async_unsubscribe_state_listener()
        if entity_ids:
            self._unsub_state_listener = async_track_state_change_event(
                self.hass, list(entity_ids), self._handle_battery_state_change
            )
        self._tracked_entities = entity_ids

    @callback
    def _async_unsubscribe_state_listener(self) -> None:
        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None

    @callback
    def _handle_battery_state_change(
        self, event: Event[EventStateChangedData]
    ) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        if new_state is None or self.data is None:
            return
        previous = self.data.batteries.get(entity_id)
        if previous is None:
            return

        info = self._build_battery_info(
            new_state,
            is_binary=previous.is_binary,
            source_attr=previous.source_attr,
        )
        if info.last_value == previous.last_value and info.name == previous.name:
            return  # attribute-only update, nothing new for the battery

        info.category = previous.category
        info.confidence = previous.confidence
        info.device_model = previous.device_model
        self._ingest(entity_id, info, self._get_now_ts())
        self._evaluate(entity_id, info, previous)
        self._log_event(
            "state_change",
            entity_id=entity_id,
            old_state=_state_str(previous.last_value),
            new_state=_state_str(info.last_value),
            status=info.status,
            category=info.category,
            confidence=info.confidence,
            stale=info.stale,
            value=info.last_value,
            remaining_days=info.remaining_days,
            remaining_source=info.remaining_source,
        )

        self.data.batteries[entity_id] = info
        # Not async_set_updated_data(): that would also restart the update
        # interval, and frequent battery events would starve the periodic
        # cycle (discovery, reclassification, stale detection, aggregation).
        self.async_update_listeners()

    # ------------------------------------------------------------------
    # Event logs
    # ------------------------------------------------------------------

    def _init_logs(self) -> None:
        log_dir = self.hass.config.path(PRODUCTION_LOG_DIR)
        self._production_log = ProductionLog(log_dir)
        LOGGER.info("Production log directory: %s", log_dir)
        if self.developer_mode:
            path = self.hass.config.path(DEBUG_LOG_FILE)
            self._debug_log = DebugLog(path)
            LOGGER.info("Debug log active: %s", path)
        self._log_event(
            "start",
            options=dict(self.config_entry.options),
            debug_extra={
                "developer_mode": True,
                "test_mode_active": self._test_mode_active,
                "time_factor": self._time_factor,
                "config_data": dict(self.config_entry.data),
            },
        )

    def _log_event(
        self,
        event_type: str,
        *,
        production: bool = True,
        debug_extra: dict[str, Any] | None = None,
        **fields: Any,
    ) -> None:
        """Write an event to the production log and (verbose) debug log."""
        now = dt_util.utcnow().timestamp()
        if production and self._production_log is not None:
            self._production_log.log(
                {"type": event_type, "ts": now, "iso": _iso(now), **fields}
            )
        if self._debug_log is not None:
            self._debug_log.log(
                {
                    "type": event_type,
                    "real_ts": now,
                    "real_iso": _iso(now),
                    "virtual_ts": self._get_now_ts(),
                    **fields,
                    **(debug_extra or {}),
                }
            )

    def _log_update(self, data: BatteryBrainData) -> None:
        """Snapshot of all batteries: hourly in production, every cycle in debug."""
        real_now = dt_util.utcnow().timestamp()
        production = real_now - self._last_snapshot_log >= PRODUCTION_SNAPSHOT_INTERVAL
        if not production and self._debug_log is None:
            return
        if production:
            self._last_snapshot_log = real_now

        now = self._get_now_ts()
        snapshot: dict[str, dict[str, Any]] = {}
        debug_snapshot: dict[str, dict[str, Any]] = {}
        for entity_id, info in data.batteries.items():
            raw = self.store.get_raw_points(entity_id)
            snapshot[entity_id] = {
                "name": info.name,
                "value": info.last_value,
                "category": info.category,
                "status": info.status,
                "confidence": info.confidence,
                "stale": info.stale,
                "remaining_days": info.remaining_days,
                "remaining_source": info.remaining_source,
                "is_binary": info.is_binary,
                "unit": info.unit,
                "history_days": round(
                    self.store.get_history_days(entity_id, now_ts=now), 2
                ),
                "raw_points_count": len(raw),
                "daily_summaries_count": len(
                    self.store.get_daily_summaries(entity_id)
                ),
            }
            if self._debug_log is not None:
                debug_snapshot[entity_id] = {
                    **snapshot[entity_id],
                    "median_interval_s": self.store.get_median_interval(entity_id),
                    "last_update_ts": self.store.get_last_update_ts(entity_id),
                    "recent_values": [p[1] for p in raw[-10:]],
                }

        self._log_event(
            "update",
            production=production,
            update_interval_s=self.update_interval.total_seconds(),
            sensors={
                "normal": len(data.normal),
                "warning": len(data.warning),
                "critical": len(data.critical),
                "total": len(data.batteries),
            },
            batteries=snapshot,
            debug_extra={
                "virtual_iso": _iso(now),
                "test_mode": self._test_mode_active,
                "time_factor": self._time_factor if self._test_mode_active else 1,
                "batteries": debug_snapshot,
            },
        )

    async def _async_flush_logs(self) -> None:
        for log in (self._production_log, self._debug_log):
            if log is not None:
                await log.async_flush(self.hass)


def _battery_level(info: BatteryInfo) -> float | None:
    """The reading as a number: percent, volts, or 1.0/0.0 (binary low/normal).

    Text levels ("low", "high", …) map to percent (TEXT_BATTERY_LEVELS).
    """
    value = info.last_value
    if value is None:
        return None
    if info.is_binary:
        return 1.0 if value == STATE_ON else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return TEXT_BATTERY_LEVELS.get(str(value).strip().lower())


def _alert_threshold(options: Mapping[str, Any]) -> float | None:
    """The warning threshold in the threshold alert mode, else None."""
    if options.get(OPT_ALERT_MODE, ALERT_MODE_SMART) != ALERT_MODE_THRESHOLD:
        return None
    return float(options.get(OPT_WARNING_THRESHOLD, DEFAULT_WARNING_THRESHOLD))


def _is_text_low(info: BatteryInfo) -> bool:
    """Whether the reading is a text low signal ("low", "critical", "empty")."""
    value = info.last_value
    return (
        isinstance(value, str)
        and not info.is_binary
        and value.strip().lower() in TEXT_LOW_LEVELS
    )


def _try_float(value: Any) -> float | str | None:
    """A number if possible, otherwise the raw value (e.g. "low") or None."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return str(value) or None


def _state_str(value: float | str | None) -> str | None:
    return None if value is None else str(value)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
