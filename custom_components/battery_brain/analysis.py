"""Battery classification, per-category status and remaining-lifetime logic.

Pure functions without Home Assistant state; the only HA import is
``homeassistant.util.dt`` for the current time (stubbed in the tests).
History is passed in as ``[timestamp, value]`` points, oldest first.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.util import dt as dt_util

from .const import (
    BINARY_CRITICAL_DAYS,
    CHARGED_DEVICE_MIN_CHARGES,
    CATEGORY_BINARY,
    CATEGORY_LINEAR,
    CATEGORY_LOW_STABLE,
    CATEGORY_PLATEAU_CLIFF,
    CATEGORY_RECHARGEABLE,
    CATEGORY_UNKNOWN_DEFAULT,
    CATEGORY_VOLTAGE,
    DEFAULT_THRESHOLDS,
    ESTIMATE_CHARGING_GRACE_HOURS,
    ESTIMATE_HALF_LIFE_FRACTION,
    ESTIMATE_HALF_LIFE_MIN_DAYS,
    ESTIMATE_LINEAR_MIN_DAYS,
    ESTIMATE_MIN_POINTS,
    ESTIMATE_MIN_SPAN_HOURS,
    ESTIMATE_RECHARGE_FULL_WEIGHT_DROP,
    ESTIMATE_RECHARGE_HISTORY_PHASES,
    ESTIMATE_RECHARGE_MIN_PHASE_DROP,
    ESTIMATE_RECHARGE_MIN_PHASE_HOURS,
    ESTIMATE_RECENT_MIN_DAYS,
    ESTIMATE_RECENT_MIN_DECLINE,
    ESTIMATE_RECENT_MIN_DECLINE_RATIO,
    ESTIMATE_RECENT_MIN_R2,
    ESTIMATE_RECHARGE_RISE_TOL,
    ESTIMATE_REPLACEMENT_JUMP,
    ESTIMATE_UNKNOWN_MIN_DROP,
    ESTIMATE_UNKNOWN_MIN_R2,
    ESTIMATE_VOLTAGE_RISE_MIN_RATIO,
    ESTIMATE_VOLTAGE_RISE_RATIO,
    ESTIMATE_WINDOW_DAYS,
    LOW_STABLE_MAX_DECLINE,
    LOW_STABLE_MIN_R2,
    LOW_STABLE_TREND_DAYS,
    NOISE_SMOOTHING_MIN_POINTS,
    NOISE_SMOOTHING_PERCENTILE,
    NOISE_SMOOTHING_WINDOW_HOURS,
    PLATEAU_KNEE_RATIO,
    PLATEAU_CLIFF_CRITICAL_DAYS,
    PLATEAU_CLIFF_WARNING_DAYS,
    PLATEAU_KNEE_START_RATIO,
    PREDICTION_CRITICAL_DAYS,
    PREDICTION_WARNING_DAYS,
    RECHARGE_DEFAULT_CYCLE_DAYS,
    RECHARGE_EVENT_MIN_RISE,
    RECHARGE_FAST_MAX_HOURS,
    RECHARGE_FAST_MIN_EVENTS,
    RECHARGE_MIN_PEAK_RATIO,
    UNCONFIRMED_DROP_HOURS,
    UNCONFIRMED_DROP_PP,
    UNCONFIRMED_DROP_RATIO,
    VOLTAGE_RECHARGED_MIN_PHASES,
    REPLACEMENT_HOLD_HOURS,
    REPLACEMENT_IMMEDIATE_LEVEL,
    REPLACEMENT_MIN_LEVEL,
    REPLACEMENT_MERGE_DAYS,
    STALE_MIN_HOURS,
    STALE_MULTIPLIER,
    STALE_UNAVAILABLE_HOURS,
    STATUS_CRITICAL,
    STATUS_NORMAL,
    STATUS_WARNING,
    VOLTAGE_EMPTY_FALLBACK_RATIO,
    VOLTAGE_EMPTY_TABLE,
    VOLTAGE_FALLBACK_LIFETIME_DAYS,
    VOLTAGE_MIN_RANGE_ABS,
    VOLTAGE_MIN_RANGE_RATIO,
)

_DAY = 86400.0
_HOUR = 3600.0
# Smaller declines are float noise of a flat fit, not a trend (pp per day).
MIN_DECLINE_PER_DAY = 1e-6

Point = tuple[float, float]
# (time-weighted centre, mean value, covered fraction of the bucket)
Bucket = tuple[float, float, float]

# =====================================================================
#  Classification — assign one of the seven archetypes
# =====================================================================


def classify_battery(
    values: list[float],
    *,
    is_binary: bool = False,
    unit: str | None = None,
    points: list[list[float]] | None = None,
    now_ts: float | None = None,
) -> str:
    """Return the archetype category for a battery based on its history.

    Classification order matters: earlier checks take precedence. With
    *points* (the same history as [ts, value]), a low battery that is
    still draining is not mistaken for low_stable.
    """
    if is_binary:
        return CATEGORY_BINARY

    if not values or len(values) < 3:
        return CATEGORY_UNKNOWN_DEFAULT

    if _is_voltage(values, unit):
        return CATEGORY_VOLTAGE

    if _is_rechargeable(values, points):
        return CATEGORY_RECHARGEABLE

    # Only the current battery: after a replacement, months of low readings
    # of the old one would otherwise keep the new battery low_stable.
    current = _current_battery(values, points, now_ts)
    if (
        _is_low_stable(current)
        and _observed_long_enough(points, now_ts)
        and not _still_draining(points, now_ts)
    ):
        return CATEGORY_LOW_STABLE

    if _is_plateau_cliff(values):
        return CATEGORY_PLATEAU_CLIFF

    # Regular recharges (a wall tablet held between 40 and 60 %) can look
    # mostly descending; a primary battery isn't refilled every few hours.
    if _is_linear(values) and _count_charge_rises(points) < RECHARGE_FAST_MIN_EVENTS:
        return CATEGORY_LINEAR

    return CATEGORY_UNKNOWN_DEFAULT


# --- Detectors ---


def is_voltage_unit(unit: str | None) -> bool:
    return bool(unit) and unit.lower() in ("v", "mv", "volt", "millivolt")


def _is_voltage(values: list[float], unit: str | None) -> bool:
    # A known unit decides: a percentage battery stuck at 1–5 % for its
    # whole history must not be mistaken for a voltage reading.
    if unit:
        return is_voltage_unit(unit)
    max_val = max(values)
    return 0.3 < max_val <= 5.0


def _is_rechargeable(
    values: list[float], points: list[list[float]] | None = None
) -> bool:
    """Two or more gradual charge events detected via local-peak tracking.

    Key distinctions:
    - Rechargeable device: value drops ≥15 pp from its recent peak (clear discharge),
      then rises gradually over ≥5 steps, each step ≤20 pp (gradual recharge), and
      the rise actually reaches close to the device's all-time observed maximum.
    - Battery replacement: value jumps instantly by >20 pp in a single step — this
      resets the tracking and does NOT count as a charge event.
    - Low-stable / erratic: never drops 15 pp from its local peak, so the discharge
      gate is never opened and no charge events are counted.
    - Periodic environmental artifacts (e.g. a daily temperature-driven sawtooth on
      an outdoor sensor's reported battery %) can otherwise mimic a discharge/gradual
      -recharge pattern, but the recovered value never gets close to the device's
      real "full" level — the peak-ratio gate below filters these out.
    - Erratic sensors (median ≤5, >40% values near zero) are filtered out upfront.

    This algorithm works for both per-tick raw data (step size ≈0.15 pp/tick) and
    coarser aggregated data (step size ≈1–20 pp/day). Fast charges in hourly
    history (steps > 20 pp) are counted from the timestamped *points*, see
    _count_fast_charges().
    """
    if len(values) < 10:
        return False

    near_zero_ratio = sum(1 for v in values if v <= 1) / len(values)
    if _median(values) <= 5 and near_zero_ratio > 0.4:
        return False

    _MIN_DISCHARGE = 15.0   # must drop this far below local peak to enter discharge state
    _MIN_CUMULATIVE = 30.0  # cumulative rise required to count as one charge cycle
    _MAX_SINGLE_STEP = 20.0 # single step above this → replacement event, resets tracking
    _MIN_STEPS = 5          # minimum consecutive rising steps (ensures gradual, not instant)
    _DROP_RESET = -0.5      # fell back during apparent charging → reset rise tracking

    peak_floor = max(values) * RECHARGE_MIN_PEAK_RATIO

    charge_events = 0
    peak = values[0]
    trough: float | None = None
    cumulative_rise = 0.0
    step_count = 0
    # A rise that satisfied the cumulative/step gate, but not yet confirmed to have
    # reached peak_floor — the rise may still be climbing higher before it ends.
    pending = False

    def resolve_pending() -> None:
        nonlocal charge_events, pending
        if pending and peak >= peak_floor:
            charge_events += 1
        pending = False

    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]

        # --- Update local peak ---
        if values[i] > peak:
            if delta > _MAX_SINGLE_STEP:
                # Jumped up too fast → battery replacement; reset everything
                resolve_pending()
                trough = None
                cumulative_rise = 0.0
                step_count = 0
            peak = values[i]

        # --- Open discharge gate: dropped MIN_DISCHARGE below local peak ---
        if peak - values[i] >= _MIN_DISCHARGE:
            if trough is None:
                # A prior rise (if any) has now conclusively ended — the peak
                # variable above has kept tracking its true top since the
                # cumulative/step gate first fired, so it's safe to judge now.
                resolve_pending()
            if trough is None or values[i] < trough:
                trough = values[i]

        # --- Track gradual charging after a trough ---
        if trough is not None:
            if delta > _MAX_SINGLE_STEP:
                # Instant jump → replacement, not recharge
                resolve_pending()
                trough = None
                peak = values[i]
                cumulative_rise = 0.0
                step_count = 0
            elif delta > 0.5:
                cumulative_rise += delta
                step_count += 1
                if cumulative_rise >= _MIN_CUMULATIVE and step_count >= _MIN_STEPS:
                    # Cycle qualifies on shape; defer the peak-height verdict
                    # until we know how high this rise actually goes.
                    pending = True
                    trough = None
                    peak = values[i]
                    cumulative_rise = 0.0
                    step_count = 0
            elif delta < _DROP_RESET:
                # Fell back down significantly during charging → reset rise tracking
                cumulative_rise = 0.0
                step_count = 0

    resolve_pending()
    if charge_events >= 2:
        return True
    if not points or len(points) != len(values):
        return False
    fast, multi_step = _count_fast_charges(points, peak_floor)
    return (
        charge_events + multi_step >= 2
        or charge_events + fast >= RECHARGE_FAST_MIN_EVENTS
    )


def _count_fast_charges(
    points: list[list[float]], peak_floor: float
) -> tuple[int, int]:
    """Charges too fast for the gradual rule: hourly steps above 20 pp.

    A phone charging at 40–60 pp/h shows up in hourly means as e.g.
    25 → 60 → 95. Counted: after a drop of at least 15 pp below the local
    peak, a run of at least two rising steps with a step above the gradual
    limit or fewer steps than a gradual charge needs, a total rise of
    30 pp, reaching *peak_floor* within RECHARGE_FAST_MAX_HOURS. A single
    jump stays a replacement, and daily means (24 h per step) never qualify.
    Returns (charges, of which with at least 4 rising steps): a replacement
    takes at most two hourly steps, so those are certainly charges.
    """
    min_discharge, min_rise, max_gradual_step = 15.0, 30.0, 20.0
    pts = _clean(points)
    count = multi_step = 0
    peak = pts[0][1] if pts else 0.0
    i = 1
    while i < len(pts):
        value = pts[i][1]
        if value > peak:
            peak = value
            i += 1
            continue
        if peak - value < min_discharge:
            i += 1
            continue
        # In a discharge: find the trough, then the rise after it.
        while i + 1 < len(pts) and pts[i + 1][1] <= pts[i][1]:
            i += 1
        start = i
        j = i
        while j + 1 < len(pts) and pts[j + 1][1] - pts[j][1] > 0.5:
            j += 1
        steps = [pts[k + 1][1] - pts[k][1] for k in range(start, j)]
        if (
            len(steps) >= 2
            and (max(steps) > max_gradual_step or len(steps) < 5)
            and pts[j][1] - pts[start][1] >= min_rise
            and pts[j][1] >= peak_floor
            and pts[j][0] - pts[start][0] <= RECHARGE_FAST_MAX_HOURS * _HOUR
        ):
            count += 1
            if len(steps) >= 4:
                multi_step += 1
        peak = pts[j][1]
        i = j + 1
    return count, multi_step


def _is_low_stable(values: list[float]) -> bool:
    """Persistently low and stable.

    Matches if either:
    - The whole history is low + stable, OR
    - The recent tail (last ~60 samples) is low + stable. This catches
      batteries that were once high but have settled at a low value for
      a long time — e.g. a button that has been at 1 % for months.
    """
    if len(values) < 5:
        return False

    if _stable_low(values):
        return True

    # Recent tail: at least 30 samples, last min(60, len) values
    tail_len = min(60, len(values))
    if tail_len >= 30 and _stable_low(values[-tail_len:]):
        return True

    return False


def _count_charge_rises(points: list[list[float]] | None) -> int:
    """Rises of at least 10 pp within RECHARGE_FAST_MAX_HOURS (any level).

    Battery replacements are rare; several such rises mean the device is
    being charged. Without timestamps nothing is counted.
    """
    if not points:
        return 0
    pts = _clean(points)
    count = 0
    i = 1
    while i < len(pts):
        if pts[i][1] - pts[i - 1][1] <= 0.5:
            i += 1
            continue
        start = i - 1
        j = i
        while j + 1 < len(pts) and pts[j + 1][1] - pts[j][1] > 0.5:
            j += 1
        if (
            pts[j][1] - pts[start][1] >= 10.0
            and pts[j][0] - pts[start][0] <= RECHARGE_FAST_MAX_HOURS * _HOUR
        ):
            count += 1
        i = j + 1
    return count


def _still_draining(
    points: list[list[float]] | None,
    now_ts: float | None,
) -> bool:
    """A low battery that keeps declining steadily is not low_stable.

    The low_stable tail check looks at the last 60 *readings*. A slowly
    draining sensor that flickers between two values (26, 27, 26, …)
    produces many readings within days and looks "low and stable" there.
    It only counts as stuck if it also stopped declining over the last
    LOW_STABLE_TREND_DAYS — a battery sitting at 1 % for weeks has, a
    draining one at 26 % hasn't. A clear trend is required (r²), so noise
    of a battery stuck low doesn't count as draining.
    """
    if not points:
        return False
    pts = _clean(points)
    now = now_ts if now_ts is not None else pts[-1][0]
    start = now - LOW_STABLE_TREND_DAYS * _DAY
    before = [p for p in pts if p[0] < start]
    window = before[-1:] + [p for p in pts if p[0] >= start]
    trend = _fit_trend(_resample(window, now, _DAY, start_ts=start), now)
    if trend is None:
        return False
    return (
        -trend.slope * LOW_STABLE_TREND_DAYS * _DAY >= LOW_STABLE_MAX_DECLINE
        and trend.r2 >= LOW_STABLE_MIN_R2
    )


def _observed_long_enough(
    points: list[list[float]] | None, now_ts: float | None
) -> bool:
    """The current battery was observed for LOW_STABLE_TREND_DAYS.

    With only a few days of readings (a sensor without long-term
    statistics, or a battery replaced recently) a battery stuck at a low
    level can't be told from one that drains slowly. Without timestamps
    there is nothing to check.
    """
    if not points:
        return True
    pts = _clean(points)
    now = now_ts if now_ts is not None else pts[-1][0]
    start = _current_battery_start(pts, now)
    return now - start >= LOW_STABLE_TREND_DAYS * _DAY


def _stable_low(values: list[float]) -> bool:
    """Median < 30 and trimmed standard deviation < 10.

    Trims 10% from each end to resist outlier spikes (e.g. solar-powered
    sensors that briefly charge to 50%+ during sunny hours).
    """
    if _median(values) >= 30:
        return False
    sorted_v = sorted(values)
    trim = len(sorted_v) // 10
    trimmed = sorted_v[trim:-trim] if trim > 0 else sorted_v
    if not trimmed:
        return False
    mean_val = sum(trimmed) / len(trimmed)
    variance = sum((v - mean_val) ** 2 for v in trimmed) / len(trimmed)
    return variance**0.5 < 10


def _is_plateau_cliff(values: list[float]) -> bool:
    """≥ 60 % of values near the max, optionally followed by a sharp drop."""
    if len(values) < 10:
        return False

    max_val = max(values)
    if max_val < 50:
        return False

    plateau_thr = max_val * 0.95
    on_plateau = sum(1 for v in values if v >= plateau_thr)
    ratio = on_plateau / len(values)

    if ratio >= 0.80:
        return True

    if ratio >= 0.60:
        for i in range(1, len(values)):
            if values[i - 1] >= plateau_thr and values[i] < max_val * 0.70:
                return True

    return False


def _is_linear(values: list[float]) -> bool:
    """Mostly monotonic decline with an overall drop > 5 pp.

    Handles two common edge cases:
    - Battery replacements (large upward jumps) split the data into segments;
      each segment is checked independently.
    - Slow-declining integer sensors use coarser windowing to filter noise.
    """
    if len(values) < 5:
        return False

    if _check_linear_segment(values):
        return True

    segments = _split_at_replacements(values, threshold=20.0)
    if len(segments) <= 5:
        for seg in segments:
            if len(seg) >= 30 and _check_linear_segment(seg):
                return True

    return False


def _check_linear_segment(values: list[float]) -> bool:
    if len(values) < 5:
        return False
    if values[-1] - values[0] >= -5:
        return False
    if _descent_ratio(values, skip=1) > 0.65:
        return True
    skip = max(2, min(24, len(values) // 20))
    return _descent_ratio(values, skip=skip) > 0.65


def _descent_ratio(values: list[float], skip: int = 1) -> float:
    decreases = increases = 0
    for i in range(skip, len(values)):
        d = values[i] - values[i - skip]
        if d < -0.5:
            decreases += 1
        elif d > 0.5:
            increases += 1
    total = decreases + increases
    return decreases / total if total > 0 else 0.0


def _current_battery(
    values: list[float],
    points: list[list[float]] | None,
    now_ts: float | None,
) -> list[float]:
    """Values since the last replacement (same rule as detect_replacements).

    A replacement counts once it has held for REPLACEMENT_HOLD_HOURS, or
    right away if it reached REPLACEMENT_IMMEDIATE_LEVEL, so a solar spike
    (real outdoor sensor: up to 65 % for hours) never counts. Without
    timestamps, the whole history.
    """
    if not points or len(points) != len(values):
        return values
    now = now_ts if now_ts is not None else points[-1][0]
    start = _current_battery_start(points, now)
    return [v for ts, v in points if ts >= start]


def _current_battery_start(points: list[list[float]], now: float) -> float:
    """Timestamp of the last confirmed replacement, else the first point."""
    level = {ts: v for ts, v in points}
    confirmed = [
        ts
        for ts in detect_replacements(points)
        if now - ts >= REPLACEMENT_HOLD_HOURS * _HOUR
        or level.get(ts, 0.0) >= REPLACEMENT_IMMEDIATE_LEVEL
    ]
    return confirmed[-1] if confirmed else points[0][0]


def _split_at_replacements(
    values: list[float], threshold: float = 20.0
) -> list[list[float]]:
    segments: list[list[float]] = []
    start = 0
    for i in range(1, len(values)):
        if values[i] - values[i - 1] > threshold:
            segments.append(values[start:i])
            start = i
    segments.append(values[start:])
    return segments


# =====================================================================
#  Status derivation — per-category logic
# =====================================================================


def derive_status(
    category: str,
    current_value: float | str | None,
    values: list[float],
    raw_points: list[list[float]],
    *,
    is_binary: bool = False,
    binary_low_is_critical: bool = False,
    now_ts: float | None = None,
    all_points: list[list[float]] | None = None,
    unit: str | None = None,
    alert_threshold: float | None = None,
    text_low: bool = False,
) -> str:
    """Return normal / warning / critical for *current_value*.

    *values* are all known values (daily means + raw points), *raw_points*
    the recent full-resolution points and *all_points* the full [ts, value]
    history; without it, linear predictions use the raw points only.

    With *alert_threshold* (threshold alert mode) a fixed percentage
    decides instead of the archetype rules; binary and voltage batteries
    keep their own rules. *text_low* marks a text reading that is the
    device's own low signal ("low", "critical", "empty").
    """
    if category == CATEGORY_BINARY or is_binary:
        return _status_binary(
            current_value, raw_points, binary_low_is_critical, now_ts=now_ts
        )
    if alert_threshold is not None and category != CATEGORY_VOLTAGE:
        return _status_threshold(
            category,
            current_value,
            raw_points,
            alert_threshold,
            text_low=text_low,
            binary_low_is_critical=binary_low_is_critical,
            now_ts=now_ts,
        )
    if category == CATEGORY_LINEAR:
        return _status_linear(
            current_value, all_points or raw_points, now_ts=now_ts
        )
    if category == CATEGORY_PLATEAU_CLIFF:
        return _status_plateau_cliff(
            current_value, values, all_points or raw_points, now_ts=now_ts
        )
    if category == CATEGORY_LOW_STABLE:
        return _status_low_stable(current_value, values, raw_points, now_ts=now_ts)
    if category == CATEGORY_VOLTAGE:
        return _status_voltage(
            current_value, values, raw_points, now_ts=now_ts, unit=unit
        )
    if category == CATEGORY_RECHARGEABLE:
        return _status_rechargeable(current_value, raw_points, now_ts=now_ts)
    return _status_unknown_default(current_value, raw_points, now_ts=now_ts)


# --- threshold alert mode ---


def _status_threshold(
    category: str,
    value: float | str | None,
    raw_points: list[list[float]],
    threshold: float,
    *,
    text_low: bool,
    binary_low_is_critical: bool,
    now_ts: float | None = None,
) -> str:
    """WARNING at or below *threshold*, CRITICAL at or below half of it.

    No predictions. Short dips are smoothed out like for low_stable, except
    for rechargeables, whose level moves too fast for that; a rechargeable
    that was recharged within its usual cycle is only WARNING.
    """
    status = STATUS_NORMAL
    if _is_number(value):
        if category == CATEGORY_RECHARGEABLE:
            level = value
        else:
            level = _representative_recent_value(value, raw_points, now_ts=now_ts)
        if level <= threshold / 2:
            status = STATUS_CRITICAL
            if category == CATEGORY_RECHARGEABLE and _recently_recharged(
                raw_points, _now(now_ts)
            ):
                status = STATUS_WARNING
        elif level <= threshold:
            status = STATUS_WARNING

    if text_low and status != STATUS_CRITICAL:
        status = STATUS_CRITICAL if binary_low_is_critical else STATUS_WARNING
    return status


# --- binary ---


def _status_binary(
    value: float | str | None,
    raw_points: list[list[float]],
    binary_low_is_critical: bool,
    *,
    now_ts: float | None = None,
) -> str:
    if value is None:
        return STATUS_NORMAL

    is_low = str(value) == "on" or (_is_number(value) and value >= 1.0)
    if not is_low:
        return STATUS_NORMAL

    if binary_low_is_critical:
        return STATUS_CRITICAL

    if len(raw_points) >= 2:
        low_since: float | None = None
        for point in reversed(raw_points):
            if point[1] >= 1.0:
                low_since = point[0]
            else:
                break
        if (
            low_since is not None
            and _now(now_ts) - low_since > BINARY_CRITICAL_DAYS * _DAY
        ):
            return STATUS_CRITICAL

    return STATUS_WARNING


# --- linear ---


def _status_linear(
    value: float | str | None,
    points: list[list[float]],
    *,
    now_ts: float | None = None,
) -> str:
    if not _is_number(value):
        return STATUS_NORMAL

    warning_pct, critical_pct = DEFAULT_THRESHOLDS[CATEGORY_LINEAR]
    status = STATUS_NORMAL
    if value <= critical_pct:
        status = STATUS_CRITICAL
    elif value <= warning_pct:
        status = STATUS_WARNING

    remaining = _estimate_trend(points, _now(now_ts))
    if remaining is not None:
        if remaining < PREDICTION_CRITICAL_DAYS:
            status = STATUS_CRITICAL
        elif remaining < PREDICTION_WARNING_DAYS and status == STATUS_NORMAL:
            status = STATUS_WARNING

    return status


# --- plateau_cliff ---


def _status_plateau_cliff(
    value: float | str | None,
    values: list[float],
    points: list[list[float]],
    *,
    now_ts: float | None = None,
) -> str:
    """Absolute thresholds, below the knee the measured time until empty.

    Leaving the plateau alone is no reason to warn: a coin cell at 85 %
    that loses a percent every few days still lasts for months. Without
    timestamped history the position below the plateau decides instead.
    """
    if not _is_number(value):
        return STATUS_NORMAL

    warning_pct, critical_pct = DEFAULT_THRESHOLDS[CATEGORY_PLATEAU_CLIFF]
    status = STATUS_NORMAL
    if value <= critical_pct:
        return STATUS_CRITICAL
    if value <= warning_pct:
        status = STATUS_WARNING

    if len(values) < 5:
        return status
    plateau = _plateau_level(values)
    if plateau < 10 or value >= plateau * PLATEAU_KNEE_RATIO:
        return status

    if points:
        remaining = _estimate_plateau_cliff(points, value, _now(now_ts))
        if remaining is not None:
            if remaining < PLATEAU_CLIFF_CRITICAL_DAYS:
                return STATUS_CRITICAL
            if remaining < PLATEAU_CLIFF_WARNING_DAYS:
                return STATUS_WARNING
        return status

    if value >= plateau * 0.70:
        return STATUS_WARNING
    return STATUS_CRITICAL


# --- low_stable ---


def _status_low_stable(
    value: float | str | None,
    values: list[float],
    raw_points: list[list[float]] | None = None,
    *,
    now_ts: float | None = None,
) -> str:
    if not _is_number(value) or len(values) < 5:
        return STATUS_NORMAL

    representative = _representative_recent_value(
        value, raw_points or [], now_ts=now_ts
    )

    sorted_vals = sorted(values)
    idx_5 = max(0, int(len(sorted_vals) * 0.05))
    floor = sorted_vals[idx_5]

    diff = floor - representative
    if diff <= 3:
        return STATUS_NORMAL
    if diff <= 10:
        return STATUS_WARNING
    return STATUS_CRITICAL


# --- voltage ---


def _status_voltage(
    value: float | str | None,
    values: list[float],
    raw_points: list[list[float]],
    *,
    now_ts: float | None = None,
    unit: str | None = None,
) -> str:
    """Charge level between the battery's full and empty voltage.

    Relative to the observed min/max instead, a battery that was never
    replaced sits at its own minimum all the time and would be pegged at
    critical (or flap with daily temperature swings).
    """
    if not _is_number(value) or len(values) < 3:
        return STATUS_NORMAL

    tol = _voltage_rise_tol(values)
    cleaned = [v for _, v in _despike(list(enumerate(values)), tol)]
    _, full, empty = _voltage_reference(cleaned, unit)
    span = full - empty
    # Full barely above empty: the empty reference doesn't fit this device
    # (or the readings are pure noise) — no meaningful charge level.
    if span < _voltage_min_range(full, unit):
        return STATUS_NORMAL

    representative = _representative_recent_value(
        value, raw_points, now_ts=now_ts
    )
    pct = (representative - empty) / span * 100
    warning_pct, critical_pct = DEFAULT_THRESHOLDS[CATEGORY_VOLTAGE]

    if pct <= critical_pct:
        return STATUS_CRITICAL
    if pct <= warning_pct:
        return STATUS_WARNING
    return STATUS_NORMAL


# --- rechargeable ---


def _status_rechargeable(
    value: float | str | None,
    raw_points: list[list[float]],
    *,
    now_ts: float | None = None,
) -> str:
    if not _is_number(value):
        return STATUS_NORMAL

    warning_pct, critical_pct = DEFAULT_THRESHOLDS[CATEGORY_RECHARGEABLE]

    if value <= critical_pct:
        if _recently_recharged(raw_points, _now(now_ts)):
            return STATUS_WARNING
        return STATUS_CRITICAL

    if value <= warning_pct:
        return STATUS_WARNING
    return STATUS_NORMAL


def _recently_recharged(raw_points: list[list[float]], now: float) -> bool:
    """Whether the last recharge lies within 1.5 typical charge cycles."""
    points = _clean(raw_points)
    if len(points) < 2:
        return False
    phases = _discharge_phases([v for _, v in points], RECHARGE_EVENT_MIN_RISE)
    charges = [points[start][0] for start, _ in phases[1:]]
    if not charges:
        return False
    cycle_days = RECHARGE_DEFAULT_CYCLE_DAYS
    if len(charges) >= 2:
        cycle_days = _median(
            [(b - a) / _DAY for a, b in zip(charges, charges[1:])]
        )
    return now - charges[-1] <= 1.5 * cycle_days * _DAY


# --- unknown_default ---


def _status_unknown_default(
    value: float | str | None,
    raw_points: list[list[float]] | None = None,
    *,
    now_ts: float | None = None,
) -> str:
    if not _is_number(value):
        return STATUS_NORMAL

    representative = _representative_recent_value(
        value, raw_points or [], now_ts=now_ts
    )

    warning_pct, critical_pct = DEFAULT_THRESHOLDS[CATEGORY_UNKNOWN_DEFAULT]
    if representative <= critical_pct:
        return STATUS_CRITICAL
    if representative <= warning_pct:
        return STATUS_WARNING
    return STATUS_NORMAL


def _representative_recent_value(
    current_value: float,
    raw_points: list[list[float]],
    *,
    window_hours: float = NOISE_SMOOTHING_WINDOW_HOURS,
    percentile: float = NOISE_SMOOTHING_PERCENTILE,
    now_ts: float | None = None,
) -> float:
    """A noise-robust stand-in for *current_value* for threshold comparisons.

    Returns a high percentile of recent raw points instead of the single
    latest reading, so a short-lived dip (e.g. a daily temperature-driven
    sawtooth on an outdoor sensor) doesn't trigger warning/critical status
    on its own, while a genuine sustained decline still pulls this value
    down over time. Falls back to *current_value* when there isn't enough
    recent history to smooth over.
    """
    if len(raw_points) < NOISE_SMOOTHING_MIN_POINTS:
        return current_value

    cutoff = _now(now_ts) - window_hours * _HOUR
    window = [p[1] for p in raw_points if p[0] >= cutoff and p[1] is not None]

    if len(window) < NOISE_SMOOTHING_MIN_POINTS:
        return current_value

    sorted_window = sorted(window)
    idx = min(int(len(sorted_window) * percentile), len(sorted_window) - 1)
    return sorted_window[idx]


# =====================================================================
#  Remaining-lifetime estimation
# =====================================================================


def estimate_remaining(
    category: str,
    current_value: float | str | None,
    raw_points: list[list[float]],
    all_points: list[list[float]],
    *,
    now_ts: float | None = None,
    unit: str | None = None,
) -> float | None:
    """Days until empty measured from the battery's own trend, or None.

    *raw_points* are the recent full-resolution points, *all_points* the
    complete history (daily means + raw points). low_stable and binary
    readings carry no trend; for them, and whenever this returns None,
    lifetime.fallback_remaining() provides an estimate.
    """
    if not _is_number(current_value):
        return None
    now = _now(now_ts)
    history = all_points or raw_points
    if category == CATEGORY_LINEAR:
        return _estimate_trend(history, now)
    if category == CATEGORY_UNKNOWN_DEFAULT:
        return _estimate_trend(history, now, gated=True)
    if category == CATEGORY_RECHARGEABLE:
        return _estimate_rechargeable(raw_points, current_value, now)
    if category == CATEGORY_VOLTAGE:
        return _estimate_voltage(history, now, unit)
    if category == CATEGORY_PLATEAU_CLIFF:
        return _estimate_plateau_cliff(history, current_value, now)
    return None


def _estimate_trend(
    points: list[list[float]], now: float, *, gated: bool = False
) -> float | None:
    """Days until 0 % along the trend since the last battery replacement.

    With *gated* (unknown_default), only a long, clearly declining trend
    yields an estimate.
    """
    pts = _clean(points, ESTIMATE_REPLACEMENT_JUMP)
    if len(pts) < 2:
        return None
    start, _ = _discharge_phases(
        [v for _, v in pts], ESTIMATE_REPLACEMENT_JUMP
    )[-1]
    phase = pts[start:]
    trend = _phase_trend(phase, now)
    if trend is None:
        return None
    if gated:
        span = now - phase[0][0]
        if (
            span < ESTIMATE_LINEAR_MIN_DAYS * _DAY
            or trend.r2 < ESTIMATE_UNKNOWN_MIN_R2
            or -trend.slope * span < ESTIMATE_UNKNOWN_MIN_DROP
        ):
            return None
    return _days_until(trend, 0.0)


def _estimate_rechargeable(
    raw_points: list[list[float]], current_value: float, now: float
) -> float | None:
    """Days until 0 % at the drain rate of the current discharge phase.

    The rate blends the current phase's own trend with the median rate of
    past discharge phases: right after unplugging the typical rate is used,
    and the more the current phase has dropped, the more its own rate
    counts. None while charging.
    """
    pts = _clean(raw_points)
    if len(pts) < 2:
        return None
    values = [v for _, v in pts]
    phases = _discharge_phases(values, ESTIMATE_RECHARGE_RISE_TOL)
    start, _ = phases[-1]
    if (
        _ends_in_rise(values, ESTIMATE_RECHARGE_RISE_TOL)
        and now - pts[start][0] < ESTIMATE_CHARGING_GRACE_HOURS * _HOUR
    ):
        return None  # charging

    typical = _typical_discharge_rate(pts, phases)

    current = pts[start:]
    own_phase = _after_top(current)
    if len(own_phase) < 2:
        own_phase = current  # a single drop so far: keep the top reading
    trend = _phase_trend(own_phase, now)
    own = -trend.slope if trend is not None and trend.slope < 0 else None

    if own is None and typical is None:
        return None
    if typical is None:
        rate = own
    elif own is None:
        rate = typical
    else:
        dropped = current[0][1] - current[-1][1]
        weight = min(1.0, max(dropped, 0.0) / ESTIMATE_RECHARGE_FULL_WEIGHT_DROP)
        rate = weight * own + (1 - weight) * typical
    return max(current_value, 0.0) / rate / _DAY


def typical_discharge_rate(
    points: list[list[float]],
    *,
    min_phase_hours: float = ESTIMATE_RECHARGE_MIN_PHASE_HOURS,
) -> float | None:
    """Median drain rate (pp per day) of the past discharge phases, or None.

    A single glitch reading (e.g. 0 % and straight back) is no charge.
    """
    pts = _clean(points, UNCONFIRMED_DROP_PP)
    if len(pts) < 2:
        return None
    phases = _discharge_phases([v for _, v in pts], ESTIMATE_RECHARGE_RISE_TOL)
    rate = _typical_discharge_rate(pts, phases, min_phase_hours=min_phase_hours)
    return rate * _DAY if rate is not None else None


def _typical_discharge_rate(
    pts: list[Point],
    phases: list[tuple[int, int]],
    *,
    min_phase_hours: float = ESTIMATE_RECHARGE_MIN_PHASE_HOURS,
) -> float | None:
    """Median drain rate (per second) of the completed discharge phases.

    Each phase's rate is its total drop over its duration — from its first
    reading below the top (time on the charger doesn't count) to its end:
    halfway between the bottom reading and the first charging reading, as
    charging started somewhere in between. An average, not a regression: a
    tablet that idles for weeks and is then used heavily for a day drains
    at the average of both.
    """
    rates: list[float] = []
    for p_start, p_end in phases[:-1]:
        phase = _after_top(pts[p_start : p_end + 1])
        if (
            len(phase) < 2
            or phase[-1][0] - phase[0][0] < min_phase_hours * _HOUR
            or phase[0][1] - phase[-1][1] < ESTIMATE_RECHARGE_MIN_PHASE_DROP
        ):
            continue
        end = (phase[-1][0] + pts[p_end + 1][0]) / 2
        rates.append((phase[0][1] - phase[-1][1]) / (end - phase[0][0]))
    if not rates:
        return None
    return _median(rates[-ESTIMATE_RECHARGE_HISTORY_PHASES:])


def is_charged_device(raw_points: list[list[float]]) -> bool:
    """Whether the battery gets recharged regularly (≥ 2 clear rises).

    True for devices kept within a charge window by an automation or
    sitting in a dock, which aren't classified as rechargeable because
    their cycles are small.
    """
    # A single glitch reading (97 → 0 → 97) is no charge.
    values = [v for _, v in _clean(raw_points, UNCONFIRMED_DROP_PP)]
    if len(values) < 3:
        return False
    rises = len(_discharge_phases(values, RECHARGE_EVENT_MIN_RISE)) - 1
    return rises >= CHARGED_DEVICE_MIN_CHARGES


def _estimate_voltage(
    points: list[list[float]], now: float, unit: str | None
) -> float | None:
    """Days until the voltage reaches the empty level (see _voltage_reference)."""
    raw_values = [p[1] for p in points if p[1] is not None]
    if len(raw_values) < 2:
        return None
    pts = _clean(points, _voltage_rise_tol(raw_values))
    values = [v for _, v in pts]
    start, full, empty = _voltage_reference(values, unit)
    phase_values = values[start:]
    if max(phase_values) - min(phase_values) < _voltage_min_range(full, unit):
        return None  # no measurable discharge yet
    min_decline = ESTIMATE_RECENT_MIN_DECLINE_RATIO * (full - empty)
    return _days_until(
        _phase_trend(pts[start:], now, min_decline=min_decline), empty
    )


def _estimate_plateau_cliff(
    points: list[list[float]], current_value: float, now: float
) -> float | None:
    """Trend since the battery left its plateau (the knee).

    On the plateau the readings carry no trend; past lifetimes of this
    device (lifetime.py) are the only signal then.
    """
    pts = _clean(points, ESTIMATE_REPLACEMENT_JUMP)
    if not pts:
        return None
    values = [v for _, v in pts]
    plateau = _plateau_level(values)
    if plateau < 10 or current_value >= plateau * PLATEAU_KNEE_RATIO:
        return None
    start, _ = _discharge_phases(values, ESTIMATE_REPLACEMENT_JUMP)[-1]
    phase = pts[start:]
    knee = max(
        (
            i
            for i, (_, v) in enumerate(phase)
            if v >= plateau * PLATEAU_KNEE_START_RATIO
        ),
        default=0,
    )
    return _days_until(_phase_trend(phase[knee:], now), 0.0)


def detect_replacements(points: list[list[float]]) -> list[float]:
    """Timestamps at which a new battery was inserted (percentage history).

    A replacement is a rise of more than ESTIMATE_REPLACEMENT_JUMP to at
    least REPLACEMENT_MIN_LEVEL that holds for REPLACEMENT_HOLD_HOURS. A
    solar spike or a short charge burst falls back within hours; a sunny
    week can lift a solar sensor for days, but not to a new battery's level.
    """
    pts = _clean(points, ESTIMATE_REPLACEMENT_JUMP)
    if not pts:
        return []
    events: list[float] = []
    for start, _ in _discharge_phases(
        [v for _, v in pts], ESTIMATE_REPLACEMENT_JUMP
    )[1:]:
        top_ts, top = pts[start]
        if top < REPLACEMENT_MIN_LEVEL:
            continue
        hold_until = top_ts + REPLACEMENT_HOLD_HOURS * _HOUR
        held = [v for ts, v in pts[start:] if ts <= hold_until]
        if min(held) >= top - ESTIMATE_REPLACEMENT_JUMP:
            events.append(top_ts)
    return events


def detect_binary_replacements(points: list[list[float]]) -> list[float]:
    """Times a binary low-battery signal cleared for good (new battery).

    Readings are 1.0 (low) and 0.0 (normal). Both the low signal before
    and the normal state after must last REPLACEMENT_HOLD_HOURS, so a
    flapping signal doesn't count.
    """
    pts = _clean(points)
    hold = REPLACEMENT_HOLD_HOURS * _HOUR
    events: list[float] = []
    low_since: float | None = None
    for i, (ts, value) in enumerate(pts):
        if value >= 1.0:
            if low_since is None:
                low_since = ts
            continue
        if low_since is not None and ts - low_since >= hold:
            if all(v < 1.0 for t, v in pts[i:] if t <= ts + hold):
                events.append(ts)
        low_since = None
    return events


def merge_replacement_events(*sources: list[float]) -> list[float]:
    """Sorted union of replacement timestamps; near-duplicates collapsed."""
    merged: list[float] = []
    for ts in sorted(ts for source in sources for ts in source):
        if merged and ts - merged[-1] < REPLACEMENT_MERGE_DAYS * _DAY:
            continue
        merged.append(ts)
    return merged


# =====================================================================
#  Shared helpers
# =====================================================================


@dataclass(frozen=True)
class _Trend:
    """A fitted line: slope per second and the fitted value at "now"."""

    slope: float
    level: float
    r2: float


def _phase_trend(
    phase: list[Point],
    now: float,
    *,
    min_decline: float = ESTIMATE_RECENT_MIN_DECLINE,
) -> _Trend | None:
    """Trend of a discharge phase up to *now*.

    Phases shorter than ESTIMATE_LINEAR_MIN_DAYS are regressed over hourly
    buckets of the last ESTIMATE_WINDOW_DAYS. Longer ones over daily
    buckets: the shortest recent window with a clear decline of at least
    *min_decline* (see ESTIMATE_RECENT_*) if there is one — it follows an
    accelerating drain — otherwise the recency-weighted whole phase.
    """
    if len(phase) < 2:
        return None
    span = now - phase[0][0]
    if span < ESTIMATE_MIN_SPAN_HOURS * _HOUR:
        return None
    if span < ESTIMATE_LINEAR_MIN_DAYS * _DAY:
        series = _resample(
            phase, now, _HOUR, start_ts=now - ESTIMATE_WINDOW_DAYS * _DAY
        )
        if len(series) < ESTIMATE_MIN_POINTS:
            return None
        return _fit_trend(series, now)

    series = _resample(phase, now, _DAY)
    recent: _Trend | None = None
    window = span / 2
    while window >= ESTIMATE_RECENT_MIN_DAYS * _DAY:
        buckets = [b for b in series if b[0] >= now - window]
        trend = (
            _fit_trend(buckets, now)
            if len(buckets) >= ESTIMATE_MIN_POINTS
            else None
        )
        if (
            trend is not None
            and trend.r2 >= ESTIMATE_RECENT_MIN_R2
            and -trend.slope * window >= min_decline
        ):
            recent = trend
        window /= 2
    if recent is not None:
        return recent
    half_life = max(
        ESTIMATE_HALF_LIFE_MIN_DAYS * _DAY, span * ESTIMATE_HALF_LIFE_FRACTION
    )
    return _fit_trend(series, now, half_life_s=half_life)


def _resample(
    points: list[Point],
    end_ts: float,
    bucket_s: float,
    *,
    start_ts: float | None = None,
) -> list[Bucket]:
    """Time-weighted bucket means of the readings as a continuous curve.

    Readings are interpolated linearly; the last one holds until *end_ts*.
    Change-only readings and hourly imported history thus weigh the same,
    a slow integer sensor's steps become the underlying slope, and time
    since the last change counts as "no drain". Buckets end at *end_ts*,
    so the most recent one is always complete (a partial day would skew
    the trend with half a day/night temperature cycle). Returns one
    (time-weighted centre, mean value, covered fraction) per bucket.
    """
    acc: dict[int, list[float]] = {}
    for i, (ts, value) in enumerate(points):
        if i + 1 < len(points):
            next_ts, next_value = points[i + 1]
            rate = (next_value - value) / (next_ts - ts) if next_ts > ts else 0.0
        else:
            next_ts, rate = end_ts, 0.0
        seg_end = min(next_ts, end_ts)
        t = ts if start_ts is None else max(ts, start_ts)
        while t < seg_end:
            bucket = int((t - end_ts) // bucket_s)
            stop = min(end_ts + (bucket + 1) * bucket_s, seg_end)
            if stop <= t:  # float rounding at a bucket edge
                bucket += 1
                stop = min(end_ts + (bucket + 1) * bucket_s, seg_end)
            duration = stop - t
            mean = value + rate * ((t + stop) / 2 - ts)
            sums = acc.setdefault(bucket, [0.0, 0.0, 0.0])
            sums[0] += mean * duration
            sums[1] += (t + stop) / 2 * duration
            sums[2] += duration
            t = stop
    return [
        (s[1] / s[2], s[0] / s[2], s[2] / bucket_s)
        for _, s in sorted(acc.items())
    ]


def _fit_trend(
    series: list[Bucket], now: float, *, half_life_s: float | None = None
) -> _Trend | None:
    """Least-squares line through *series*, evaluated at *now*.

    Buckets are weighted by how much of them is covered and, with
    *half_life_s*, by how recent they are.
    """
    if len(series) < 2:
        return None
    weights = [
        covered * (0.5 ** ((now - t) / half_life_s) if half_life_s else 1.0)
        for t, _, covered in series
    ]
    total = sum(weights)
    mean_t = sum(w * t for w, (t, _, _) in zip(weights, series)) / total
    mean_v = sum(w * v for w, (_, v, _) in zip(weights, series)) / total
    s_tt = s_tv = s_vv = 0.0
    for w, (t, v, _) in zip(weights, series):
        dt = t - mean_t
        dv = v - mean_v
        s_tt += w * dt * dt
        s_tv += w * dt * dv
        s_vv += w * dv * dv
    if s_tt <= 0:
        return None
    slope = s_tv / s_tt
    r2 = s_tv * s_tv / (s_tt * s_vv) if s_vv > 0 else 0.0
    return _Trend(slope=slope, level=mean_v + slope * (now - mean_t), r2=r2)


def _days_until(trend: _Trend | None, floor: float) -> float | None:
    """Days until the fitted line reaches *floor*; None if not declining."""
    # Exactly flat readings can fit a slope of about -1e-30 (float noise),
    # which became "measured: 100 years" instead of the fallback.
    if trend is None or -trend.slope * _DAY < MIN_DECLINE_PER_DAY:
        return None
    headroom = trend.level - floor
    if headroom <= 0:
        return 0.0
    return headroom / -trend.slope / _DAY


def _discharge_phases(
    values: list[float], rise_tol: float
) -> list[tuple[int, int]]:
    """Split a series into discharge phases at rises larger than *rise_tol*.

    A rise is a run of consecutive non-decreasing readings, measured from
    its first to its last reading — so a recharge reported in 1 pp steps
    counts as one rise. Each phase is (start, end): it starts where a rise
    first reached its top (battery inserted / charging finished) and ends
    at the bottom of the next rise. If the series ends in a rise (e.g.
    while charging), the last phase starts at that rise's top.
    """
    if not values:
        return []
    phases: list[tuple[int, int]] = []
    start = 0
    run_low = 0
    for i in range(1, len(values)):
        if values[i] < values[i - 1]:
            if values[i - 1] - values[run_low] > rise_tol:
                phases.append((start, run_low))
                start = values.index(values[i - 1], run_low, i)
            run_low = i
    if values[-1] - values[run_low] > rise_tol:
        phases.append((start, run_low))
        start = values.index(values[-1], run_low)
    phases.append((start, len(values) - 1))
    return phases


def _ends_in_rise(values: list[float], rise_tol: float) -> bool:
    """Whether the series ends in a rise larger than *rise_tol*."""
    k = len(values) - 1
    while k > 0 and values[k - 1] <= values[k]:
        k -= 1
    return values[-1] - values[k] > rise_tol


def _after_top(phase: list[Point]) -> list[Point]:
    """The part of a phase from the first reading below its starting top.

    For rechargeables the time spent at the top (still on the charger) is
    no discharge, so the drain rate is measured from the first drop.
    """
    top = phase[0][1]
    for i, (_, value) in enumerate(phase):
        if value < top:
            return phase[i:]
    return []


def _clean(
    points: list[list[float]], spike_tol: float | None = None
) -> list[Point]:
    """Numeric points as sorted tuples, optionally without single spikes."""
    pts = sorted((float(p[0]), float(p[1])) for p in points if p[1] is not None)
    if spike_tol is not None:
        pts = _despike(pts, spike_tol)
    return pts


def is_unconfirmed_drop(
    raw_points: list[list[float]], now_ts: float, unit: str | None = None
) -> bool:
    """The latest reading is a sudden large drop nothing has confirmed yet.

    True if it is at least UNCONFIRMED_DROP_PP (voltages: the
    UNCONFIRMED_DROP_RATIO share) below the reading before, it is the only
    reading at that level and it is younger than UNCONFIRMED_DROP_HOURS. A
    second low reading or the time limit confirms it; a reading back up
    makes it a glitch, which _despike() removes from the history.
    """
    if len(raw_points) < 2:
        return False
    (_, before), (ts, value) = raw_points[-2], raw_points[-1]
    if before is None or value is None:
        return False
    drop = before - value
    limit = (
        UNCONFIRMED_DROP_RATIO * abs(before)
        if is_voltage_unit(unit)
        else UNCONFIRMED_DROP_PP
    )
    return drop >= limit and now_ts - ts < UNCONFIRMED_DROP_HOURS * _HOUR


def _despike(points: list[Point], tol: float) -> list[Point]:
    """Drop isolated readings that jump by more than *tol* and straight back.

    A glitch like 80 → 0 → 80 would otherwise look like a battery
    replacement (the 0 → 80 rise). Only single readings whose neighbours
    agree with each other are dropped.
    """
    if len(points) < 3:
        return points
    kept = [points[0]]
    for i in range(1, len(points) - 1):
        prev_v = kept[-1][1]
        value = points[i][1]
        next_v = points[i + 1][1]
        if (
            abs(value - prev_v) > tol
            and abs(value - next_v) > tol
            and abs(prev_v - next_v) <= tol / 2
        ):
            continue
        kept.append(points[i])
    kept.append(points[-1])
    return kept


def _voltage_reference(
    values: list[float], unit: str | None
) -> tuple[int, float, float]:
    """(phase start, full, empty) voltage of the current battery.

    *full* is the highest reading since the last replacement or recharge;
    *empty* the lowest reading of the previous battery, or — as long as no
    replacement has been observed — the typical cut-off voltage for this
    battery type (VOLTAGE_EMPTY_TABLE).
    """
    phases = _discharge_phases(values, _voltage_rise_tol(values))
    start, _ = phases[-1]
    full = max(values[start:])
    typical = _typical_empty_voltage(full, unit)
    # Batteries are replaced every few months; a source that is recharged
    # all the time (a car battery by its alternator, a node charged by
    # hand) doesn't end its phases empty. Taken as "empty", a car's resting
    # 12.5 V made 12.7 V critical.
    if 1 < len(phases) < VOLTAGE_RECHARGED_MIN_PHASES:
        prev_start, prev_end = phases[-2]
        previous_empty = min(values[prev_start : prev_end + 1])
        if previous_empty < full:
            return start, full, previous_empty
    return start, full, typical


def _voltage_rise_tol(values: list[float]) -> float:
    vmax = max(values)
    return max(
        ESTIMATE_VOLTAGE_RISE_RATIO * (vmax - min(values)),
        ESTIMATE_VOLTAGE_RISE_MIN_RATIO * vmax,
    )


def _voltage_min_range(full: float, unit: str | None) -> float:
    """Smallest voltage difference that is more than noise/quantization."""
    return max(
        VOLTAGE_MIN_RANGE_ABS / _volts_per_unit(unit),
        VOLTAGE_MIN_RANGE_RATIO * full,
    )


def _typical_empty_voltage(full: float, unit: str | None) -> float:
    scale = _volts_per_unit(unit)
    full_volts = full * scale
    for max_full, empty, _ in VOLTAGE_EMPTY_TABLE:
        if full_volts <= max_full:
            return empty / scale
    return full * VOLTAGE_EMPTY_FALLBACK_RATIO


def voltage_charge(
    values: list[float], level: float, unit: str | None
) -> tuple[float, float]:
    """(remaining charge 0..1, typical lifetime in days) of a voltage battery.

    The charge is the position of *level* between the battery's full and
    empty voltage (see _voltage_reference); the lifetime comes from
    VOLTAGE_EMPTY_TABLE by full voltage.
    """
    tol = _voltage_rise_tol(values)
    cleaned = [v for _, v in _despike(list(enumerate(values)), tol)]
    _, full, empty = _voltage_reference(cleaned, unit)
    span = full - empty
    fraction = min(max((level - empty) / span, 0.0), 1.0) if span > 0 else 1.0
    full_volts = full * _volts_per_unit(unit)
    for max_full, _, lifetime in VOLTAGE_EMPTY_TABLE:
        if full_volts <= max_full:
            return fraction, lifetime
    return fraction, VOLTAGE_FALLBACK_LIFETIME_DAYS


def _volts_per_unit(unit: str | None) -> float:
    return 0.001 if unit and unit.lower() in ("mv", "millivolt") else 1.0


def _plateau_level(values: list[float]) -> float:
    """Mean of the top quarter of the values."""
    sorted_desc = sorted(values, reverse=True)
    top_n = max(1, len(sorted_desc) // 4)
    return sum(sorted_desc[:top_n]) / top_n


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _now(now_ts: float | None) -> float:
    return now_ts if now_ts is not None else dt_util.utcnow().timestamp()


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


# =====================================================================
#  Stale detection
# =====================================================================


def check_stale(
    last_update_ts: float | None,
    median_interval: float | None,
    value_is_unavailable: bool,
    now_ts: float | None = None,
) -> bool:
    """Determine whether a battery should be considered stale.

    A battery is stale when:
    - state unavailable/unknown for longer than STALE_UNAVAILABLE_HOURS, OR
    - time since *last_update_ts* exceeds max(3 × median interval, 24 h).

    The coordinator passes the last time the entity was seen with a valid
    value (refreshed every update cycle), so in practice a battery becomes
    stale once its entity has been unavailable/unknown for over an hour.
    """
    if last_update_ts is None:
        return False

    elapsed = _now(now_ts) - last_update_ts

    if value_is_unavailable and elapsed > STALE_UNAVAILABLE_HOURS * _HOUR:
        return True

    if median_interval is not None:
        threshold = max(
            STALE_MULTIPLIER * median_interval,
            STALE_MIN_HOURS * _HOUR,
        )
    else:
        threshold = STALE_MIN_HOURS * _HOUR

    return elapsed > threshold
