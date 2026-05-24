"""Tests for battery classification and per-category status derivation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import FROZEN_NOW, FakeDtUtil

from custom_components.battery_brain.analysis import (
    check_stale,
    classify_battery,
    derive_status,
    estimate_remaining_days,
)
from custom_components.battery_brain.const import (
    CATEGORY_BINARY,
    CATEGORY_LINEAR,
    CATEGORY_LOW_STABLE,
    CATEGORY_PLATEAU_CLIFF,
    CATEGORY_RECHARGEABLE,
    CATEGORY_UNKNOWN_DEFAULT,
    CATEGORY_VOLTAGE,
    STALE_MIN_HOURS,
    STALE_UNAVAILABLE_HOURS,
    STATUS_CRITICAL,
    STATUS_NORMAL,
    STATUS_WARNING,
)

NOW_TS = FROZEN_NOW.timestamp()


# =====================================================================
#  Classification
# =====================================================================


class TestClassifyBinary:
    def test_binary_flag(self):
        assert classify_battery([], is_binary=True) == CATEGORY_BINARY

    def test_binary_ignores_values(self):
        assert (
            classify_battery([100, 90, 80], is_binary=True) == CATEGORY_BINARY
        )


class TestClassifyVoltage:
    def test_by_unit_v(self):
        assert classify_battery([3.1, 3.0, 2.9], unit="V") == CATEGORY_VOLTAGE

    def test_by_unit_mv(self):
        assert (
            classify_battery([3300, 3200, 3100], unit="mV") == CATEGORY_VOLTAGE
        )

    def test_by_low_values(self):
        assert (
            classify_battery([3.3, 3.2, 3.1, 3.0, 2.9]) == CATEGORY_VOLTAGE
        )

    def test_percentage_not_misclassified(self):
        vals = list(range(100, 30, -5))
        assert classify_battery(vals) != CATEGORY_VOLTAGE


class TestClassifyRechargeable:
    def test_two_charge_cycles(self):
        # Gradual discharge (-5pp/step) then gradual recharge (+5pp/step), twice
        vals = (
            list(range(100, 20, -5))
            + list(range(20, 100, 5))
            + list(range(100, 20, -5))
            + list(range(20, 100, 5))
        )
        assert classify_battery(vals) == CATEGORY_RECHARGEABLE

    def test_single_cycle_not_rechargeable(self):
        vals = list(range(100, 20, -5)) + list(range(20, 100, 5))
        assert classify_battery(vals) != CATEGORY_RECHARGEABLE

    def test_too_few_values(self):
        assert classify_battery([100, 50, 100]) != CATEGORY_RECHARGEABLE

    def test_instant_jumps_not_rechargeable(self):
        # Battery replaced twice (instant +90 pp jump) — must NOT be classified as rechargeable
        vals = list(range(100, 0, -1)) + [92] + list(range(92, 0, -1)) + [95]
        assert classify_battery(vals) != CATEGORY_RECHARGEABLE

    def test_per_tick_discharge_two_cycles(self):
        # Simulate real 200x test-mode: discharge 0.16pp/tick, charge 5.2pp/tick
        # Two full cycles should be detected as rechargeable
        import math
        discharge_step = 0.156  # 15%/day at 200x, per tick
        charge_step = 5.208     # 500%/day at 200x, per tick
        vals = [100.0]
        charging_target = None
        for _ in range(1300):
            if charging_target is not None:
                v = round(min(vals[-1] + charge_step, charging_target), 1)
                vals.append(v)
                if v >= charging_target:
                    charging_target = None
            else:
                v = round(max(vals[-1] - discharge_step, 0.0), 1)
                vals.append(v)
                if v <= 10.0:
                    charging_target = 97.0
        assert classify_battery(vals) == CATEGORY_RECHARGEABLE

    def test_erratic_not_rechargeable(self):
        # Random values between 30-80% — should NOT be classified as rechargeable
        import random
        random.seed(42)
        vals = [round(random.uniform(30, 80), 1) for _ in range(1300)]
        assert classify_battery(vals) != CATEGORY_RECHARGEABLE

    def test_erratic_near_zero_not_rechargeable(self):
        # Sensor mostly at 0% with random spikes — erratic, not rechargeable
        vals = [0.0] * 200 + [0, 1.7, 4.5, 11.9, 22.1, 28.1, 34.0, 30.5, 25.5]
        vals += [0.0] * 300
        vals += [10.9, 25.4, 31.3, 26.3, 30.1, 35.9, 41.5, 47.6, 55.3, 20, 0]
        vals += [0.0] * 200
        assert classify_battery(vals) != CATEGORY_RECHARGEABLE

    def test_fast_cycling_rechargeable(self):
        # Wall panel with rapid charge/discharge cycles (steps ~10-18pp)
        vals = []
        for _ in range(50):
            # Discharge: 80 -> 30 in 5 steps
            for v in [80, 65, 50, 40, 30]:
                vals.append(float(v))
            # Charge: 30 -> 80 in 5 steps
            for v in [42, 55, 62, 72, 80]:
                vals.append(float(v))
        assert classify_battery(vals) == CATEGORY_RECHARGEABLE

    def test_low_stable_not_rechargeable(self):
        # Values oscillating near 5% — should NOT be classified as rechargeable
        # (never drops 15pp from local peak so discharge gate never opens)
        import random
        random.seed(7)
        walk = 0.0
        vals = []
        for _ in range(500):
            walk += random.gauss(0, 0.1) * 0.3
            walk = max(-2, min(2, walk))
            vals.append(round(max(0.0, 5.0 + walk + random.gauss(0, 0.3)), 1))
        assert classify_battery(vals) != CATEGORY_RECHARGEABLE


class TestClassifyLowStable:
    def test_persistently_low(self):
        vals = [5, 6, 5, 4, 5, 6, 5, 4, 5, 5]
        assert classify_battery(vals) == CATEGORY_LOW_STABLE

    def test_high_values_not_low_stable(self):
        vals = [80, 79, 80, 81, 80, 79, 80, 80]
        assert classify_battery(vals) != CATEGORY_LOW_STABLE

    def test_low_but_high_variance(self):
        vals = [5, 25, 5, 28, 3, 20, 5, 25]
        assert classify_battery(vals) != CATEGORY_LOW_STABLE

    def test_stuck_at_low_after_decline(self):
        # Battery dropped from 100 % over time and has been stuck at 1 %
        # for many readings — should now be low_stable, not unknown.
        # 20 declining (full history fails the variance check) +
        # 60 stable at 1 % (the tail tail passes).
        vals = list(range(100, 0, -5)) + [1.0] * 60
        assert classify_battery(vals) == CATEGORY_LOW_STABLE

    def test_recent_decline_not_yet_stable(self):
        # Just dropped — recent values not yet stable enough
        vals = [80, 70, 60, 50, 40, 30, 20, 10, 5, 2]
        assert classify_battery(vals) != CATEGORY_LOW_STABLE


class TestClassifyPlateauCliff:
    def test_classic_plateau_then_cliff(self):
        vals = [100] * 50 + [95, 80, 30, 10]
        assert classify_battery(vals) == CATEGORY_PLATEAU_CLIFF

    def test_pure_plateau_no_cliff_yet(self):
        vals = [100, 100, 99, 100, 100, 99, 100, 100, 100, 100]
        assert classify_battery(vals) == CATEGORY_PLATEAU_CLIFF

    def test_low_plateau_excluded(self):
        vals = [30] * 20
        assert classify_battery(vals) != CATEGORY_PLATEAU_CLIFF


class TestClassifyLinear:
    def test_steady_decline(self):
        vals = list(range(100, 20, -2))
        assert classify_battery(vals) == CATEGORY_LINEAR

    def test_noisy_decline(self):
        import random

        random.seed(42)
        vals = [100 - i * 2 + random.uniform(-1, 1) for i in range(40)]
        assert classify_battery(vals) == CATEGORY_LINEAR

    def test_flat_not_linear(self):
        vals = [80, 80, 80, 80, 80, 80, 80]
        assert classify_battery(vals) != CATEGORY_LINEAR

    def test_slow_integer_decline_with_replacement(self):
        # Sensor that drops 1% at a time over thousands of readings,
        # then gets a battery replacement (large jump up).
        vals = []
        # Phase 1: slow decline from 23 to 6 with integer noise
        for i in range(700):
            base = 23 - (17 * i / 700)
            vals.append(round(base))
        # Battery replacement jump
        vals.append(55.0)
        # Phase 2: slowly declining from 55
        for i in range(150):
            vals.append(round(55 - (4 * i / 150)))
        assert classify_battery(vals) == CATEGORY_LINEAR

    def test_slow_decline_no_replacement(self):
        # Very slow decline with mostly flat readings (integer sensor)
        vals = []
        for i in range(500):
            base = 80 - (40 * i / 500)
            vals.append(round(base))
        assert classify_battery(vals) == CATEGORY_LINEAR


    def test_sawtooth_charge_cycles_not_linear(self):
        # Rechargeable with large charge steps (>20pp) must not be caught
        # by segmentation — many segments = cycling, not replacements.
        vals = []
        for _ in range(80):
            for v in [80, 65, 50, 35, 55, 75, 90]:
                vals.append(float(v))
        assert classify_battery(vals) != CATEGORY_LINEAR


class TestClassifyUnknownDefault:
    def test_insufficient_data(self):
        assert classify_battery([50, 45]) == CATEGORY_UNKNOWN_DEFAULT

    def test_empty(self):
        assert classify_battery([]) == CATEGORY_UNKNOWN_DEFAULT


# =====================================================================
#  Status derivation — unknown_default
# =====================================================================


class TestStatusUnknownDefault:
    def test_normal(self):
        assert (
            derive_status(CATEGORY_UNKNOWN_DEFAULT, 50.0, [], [])
            == STATUS_NORMAL
        )

    def test_warning(self):
        assert (
            derive_status(CATEGORY_UNKNOWN_DEFAULT, 18.0, [], [])
            == STATUS_WARNING
        )

    def test_critical(self):
        assert (
            derive_status(CATEGORY_UNKNOWN_DEFAULT, 8.0, [], [])
            == STATUS_CRITICAL
        )

    def test_boundary_20(self):
        assert (
            derive_status(CATEGORY_UNKNOWN_DEFAULT, 20.0, [], [])
            == STATUS_WARNING
        )

    def test_boundary_10(self):
        assert (
            derive_status(CATEGORY_UNKNOWN_DEFAULT, 10.0, [], [])
            == STATUS_CRITICAL
        )

    def test_none_value(self):
        assert (
            derive_status(CATEGORY_UNKNOWN_DEFAULT, None, [], [])
            == STATUS_NORMAL
        )

    def test_binary_on_warning(self):
        assert (
            derive_status(
                CATEGORY_UNKNOWN_DEFAULT,
                "on",
                [],
                [],
                is_binary=True,
            )
            == STATUS_WARNING
        )

    def test_binary_on_critical_option(self):
        assert (
            derive_status(
                CATEGORY_UNKNOWN_DEFAULT,
                "on",
                [],
                [],
                is_binary=True,
                binary_low_is_critical=True,
            )
            == STATUS_CRITICAL
        )


# =====================================================================
#  Status derivation — linear
# =====================================================================


class TestStatusLinear:
    def test_normal(self):
        assert (
            derive_status(CATEGORY_LINEAR, 50.0, [50], []) == STATUS_NORMAL
        )

    def test_warning_threshold(self):
        assert (
            derive_status(CATEGORY_LINEAR, 18.0, [18], []) == STATUS_WARNING
        )

    def test_critical_threshold(self):
        assert (
            derive_status(CATEGORY_LINEAR, 8.0, [8], []) == STATUS_CRITICAL
        )

    def test_prediction_escalates_to_warning(self):
        raw = [
            [NOW_TS - 10 * 86400, 20.0],
            [NOW_TS - 7 * 86400, 15.0],
            [NOW_TS - 4 * 86400, 10.0],
            [NOW_TS - 1 * 86400, 5.0],
        ]
        result = derive_status(CATEGORY_LINEAR, 25.0, [25], raw)
        assert result in (STATUS_WARNING, STATUS_CRITICAL)


# =====================================================================
#  Status derivation — plateau_cliff
# =====================================================================


class TestStatusPlateauCliff:
    def test_on_plateau(self):
        vals = [100] * 30
        assert (
            derive_status(CATEGORY_PLATEAU_CLIFF, 99.0, vals, [])
            == STATUS_NORMAL
        )

    def test_slight_drop_warning(self):
        vals = [100] * 30
        assert (
            derive_status(CATEGORY_PLATEAU_CLIFF, 85.0, vals, [])
            == STATUS_WARNING
        )

    def test_cliff_fall_critical(self):
        vals = [100] * 30
        assert (
            derive_status(CATEGORY_PLATEAU_CLIFF, 40.0, vals, [])
            == STATUS_CRITICAL
        )

    def test_rapid_recent_drop_critical(self):
        vals = [100] * 20 + [100, 95, 90, 85, 80, 75, 70, 65, 50, 30]
        assert (
            derive_status(CATEGORY_PLATEAU_CLIFF, 30.0, vals, [])
            == STATUS_CRITICAL
        )


# =====================================================================
#  Status derivation — low_stable
# =====================================================================


class TestStatusLowStable:
    def test_near_floor_normal(self):
        vals = [5, 6, 5, 4, 5, 6, 5, 4, 5, 5]
        assert (
            derive_status(CATEGORY_LOW_STABLE, 5.0, vals, []) == STATUS_NORMAL
        )

    def test_below_floor_warning(self):
        vals = [10, 11, 10, 9, 10, 11, 10, 9, 10, 10]
        assert (
            derive_status(CATEGORY_LOW_STABLE, 2.0, vals, []) == STATUS_WARNING
        )

    def test_far_below_floor_critical(self):
        vals = [20, 21, 20, 19, 20, 21, 20, 19, 20, 20]
        assert (
            derive_status(CATEGORY_LOW_STABLE, 1.0, vals, []) == STATUS_CRITICAL
        )

    def test_never_critical_just_because_low(self):
        vals = [3, 3, 3, 3, 3, 3, 3]
        assert (
            derive_status(CATEGORY_LOW_STABLE, 3.0, vals, []) == STATUS_NORMAL
        )


# =====================================================================
#  Status derivation — voltage
# =====================================================================


class TestStatusVoltage:
    def test_full_voltage_normal(self):
        vals = [4.2, 4.0, 3.8, 3.5, 3.0]
        assert (
            derive_status(CATEGORY_VOLTAGE, 4.0, vals, []) == STATUS_NORMAL
        )

    def test_low_voltage_warning(self):
        vals = [4.2, 4.0, 3.8, 3.5, 3.0]
        # range = 1.2, warning threshold = 25% → value at 3.0 + 0.25*1.2 = 3.30
        assert (
            derive_status(CATEGORY_VOLTAGE, 3.2, vals, []) == STATUS_WARNING
        )

    def test_critical_voltage(self):
        vals = [4.2, 4.0, 3.8, 3.5, 3.0]
        # critical threshold = 10% → value at 3.0 + 0.10*1.2 = 3.12
        assert (
            derive_status(CATEGORY_VOLTAGE, 3.05, vals, []) == STATUS_CRITICAL
        )


# =====================================================================
#  Status derivation — binary
# =====================================================================


class TestStatusBinary:
    def test_off_normal(self):
        assert (
            derive_status(CATEGORY_BINARY, "off", [], []) == STATUS_NORMAL
        )

    def test_on_warning(self):
        assert (
            derive_status(CATEGORY_BINARY, "on", [], []) == STATUS_WARNING
        )

    def test_on_critical_option(self):
        assert (
            derive_status(
                CATEGORY_BINARY,
                "on",
                [],
                [],
                binary_low_is_critical=True,
            )
            == STATUS_CRITICAL
        )

    def test_on_prolonged_critical(self):
        four_days_ago = NOW_TS - 4 * 86400
        raw = [
            [four_days_ago, 1.0],
            [four_days_ago + 3600, 1.0],
            [NOW_TS - 3600, 1.0],
        ]
        assert (
            derive_status(CATEGORY_BINARY, "on", [], raw) == STATUS_CRITICAL
        )


# =====================================================================
#  Status derivation — rechargeable
# =====================================================================


class TestStatusRechargeable:
    def test_high_charge_normal(self):
        assert (
            derive_status(CATEGORY_RECHARGEABLE, 80.0, [], []) == STATUS_NORMAL
        )

    def test_warning_threshold(self):
        assert (
            derive_status(CATEGORY_RECHARGEABLE, 12.0, [], []) == STATUS_WARNING
        )

    def test_critical_no_recent_charge(self):
        old_ts = NOW_TS - 30 * 86400
        raw = [[old_ts, 80.0], [old_ts + 86400, 60.0], [NOW_TS, 3.0]]
        assert (
            derive_status(CATEGORY_RECHARGEABLE, 3.0, [], raw) == STATUS_CRITICAL
        )

    def test_critical_downgraded_if_recent_charge(self):
        raw = [
            [NOW_TS - 3 * 86400, 10.0],
            [NOW_TS - 2 * 86400, 90.0],
            [NOW_TS - 86400, 50.0],
            [NOW_TS, 3.0],
        ]
        assert (
            derive_status(CATEGORY_RECHARGEABLE, 3.0, [], raw) == STATUS_WARNING
        )


# =====================================================================
#  Remaining-days estimation
# =====================================================================


class TestEstimateRemainingDays:
    def test_declining_linear(self):
        raw = [
            [NOW_TS - 10 * 86400, 50.0],
            [NOW_TS - 7 * 86400, 47.0],
            [NOW_TS - 4 * 86400, 44.0],
            [NOW_TS - 1 * 86400, 41.0],
        ]
        days = estimate_remaining_days(raw)
        assert days is not None
        assert 30 < days < 50

    def test_flat_returns_none(self):
        raw = [
            [NOW_TS - 5 * 86400, 80.0],
            [NOW_TS - 3 * 86400, 80.0],
            [NOW_TS - 1 * 86400, 80.0],
        ]
        assert estimate_remaining_days(raw) is None

    def test_rising_returns_none(self):
        raw = [
            [NOW_TS - 5 * 86400, 50.0],
            [NOW_TS - 3 * 86400, 60.0],
            [NOW_TS - 1 * 86400, 70.0],
        ]
        assert estimate_remaining_days(raw) is None

    def test_too_few_points(self):
        raw = [[NOW_TS - 86400, 50.0], [NOW_TS, 45.0]]
        assert estimate_remaining_days(raw) is None


# =====================================================================
#  Stale detection
# =====================================================================


class TestCheckStale:
    def test_no_data_not_stale(self):
        assert check_stale(None, None, False, now_ts=NOW_TS) is False

    def test_recent_update_not_stale(self):
        assert (
            check_stale(NOW_TS - 3600, 3600.0, False, now_ts=NOW_TS) is False
        )

    def test_stale_by_interval(self):
        median = 36000.0  # 10h median interval
        threshold = 3 * median  # 30h (> 24h minimum)
        last = NOW_TS - (threshold + 1)
        assert check_stale(last, median, False, now_ts=NOW_TS) is True

    def test_stale_minimum_24h(self):
        median = 60.0  # very frequent updates
        # 3 * 60 = 180s, but min is 24h
        last = NOW_TS - (STALE_MIN_HOURS * 3600 + 1)
        assert check_stale(last, median, False, now_ts=NOW_TS) is True

    def test_not_stale_under_24h_even_with_small_interval(self):
        median = 60.0
        last = NOW_TS - 12 * 3600  # 12h ago
        assert check_stale(last, median, False, now_ts=NOW_TS) is False

    def test_unavailable_stale_after_threshold(self):
        last = NOW_TS - (STALE_UNAVAILABLE_HOURS * 3600 + 1)
        assert check_stale(last, None, True, now_ts=NOW_TS) is True

    def test_unavailable_not_stale_under_threshold(self):
        last = NOW_TS - (STALE_UNAVAILABLE_HOURS * 3600 - 60)
        assert check_stale(last, None, True, now_ts=NOW_TS) is False

    def test_stale_without_median_uses_24h(self):
        last = NOW_TS - (STALE_MIN_HOURS * 3600 + 1)
        assert check_stale(last, None, False, now_ts=NOW_TS) is True

    def test_not_stale_without_median_under_24h(self):
        last = NOW_TS - 12 * 3600
        assert check_stale(last, None, False, now_ts=NOW_TS) is False
