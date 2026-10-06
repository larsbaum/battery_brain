"""Battery classification into archetypes and per-category status derivation."""

from __future__ import annotations

from homeassistant.util import dt as dt_util

from .const import (
    BINARY_CRITICAL_DAYS,
    CATEGORY_BINARY,
    CATEGORY_LINEAR,
    CATEGORY_LOW_STABLE,
    CATEGORY_PLATEAU_CLIFF,
    CATEGORY_RECHARGEABLE,
    CATEGORY_UNKNOWN_DEFAULT,
    CATEGORY_VOLTAGE,
    DEFAULT_THRESHOLDS,
    ESTIMATE_LINEAR_MIN_DAYS,
    ESTIMATE_MIN_POINTS,
    ESTIMATE_MIN_SPAN_HOURS,
    ESTIMATE_RECHARGE_RISE_TOL,
    ESTIMATE_REPLACEMENT_JUMP,
    ESTIMATE_VOLTAGE_RISE_RATIO,
    ESTIMATE_WINDOW_DAYS,
    NOISE_SMOOTHING_MIN_POINTS,
    NOISE_SMOOTHING_PERCENTILE,
    NOISE_SMOOTHING_WINDOW_HOURS,
    PREDICTION_CRITICAL_DAYS,
    PREDICTION_WARNING_DAYS,
    RECHARGE_MIN_PEAK_RATIO,
    STALE_MIN_HOURS,
    STALE_MULTIPLIER,
    STALE_UNAVAILABLE_HOURS,
    STATUS_CRITICAL,
    STATUS_NORMAL,
    STATUS_WARNING,
    VOLTAGE_MIN_RANGE_ABS,
    VOLTAGE_MIN_RANGE_RATIO,
)

# =====================================================================
#  Classification — assign one of the seven archetypes
# =====================================================================


def classify_battery(
    values: list[float],
    *,
    is_binary: bool = False,
    unit: str | None = None,
) -> str:
    """Return the archetype category for a battery based on its history.

    Classification order matters: earlier checks take precedence.
    """
    if is_binary:
        return CATEGORY_BINARY

    if not values or len(values) < 3:
        return CATEGORY_UNKNOWN_DEFAULT

    if _is_voltage(values, unit):
        return CATEGORY_VOLTAGE

    if _is_rechargeable(values):
        return CATEGORY_RECHARGEABLE

    if _is_low_stable(values):
        return CATEGORY_LOW_STABLE

    if _is_plateau_cliff(values):
        return CATEGORY_PLATEAU_CLIFF

    if _is_linear(values):
        return CATEGORY_LINEAR

    return CATEGORY_UNKNOWN_DEFAULT


# --- Detectors ---


def _is_voltage(values: list[float], unit: str | None) -> bool:
    if unit and unit.lower() in ("v", "mv", "volt", "millivolt"):
        return True
    max_val = max(values)
    return 0.3 < max_val <= 5.0


def _is_rechargeable(values: list[float]) -> bool:
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
    coarser aggregated data (step size ≈1–20 pp/day).
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
    return charge_events >= 2


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
) -> str:
    """Return normal / warning / critical for *current_value*.

    *all_points* is the full [ts, value] history (daily means + raw points);
    without it, linear predictions fall back to the recent raw points only.
    """
    if category == CATEGORY_BINARY:
        return _status_binary(
            current_value, raw_points, binary_low_is_critical, now_ts=now_ts
        )
    if category == CATEGORY_LINEAR:
        return _status_linear(
            current_value, raw_points, all_points, now_ts=now_ts
        )
    if category == CATEGORY_PLATEAU_CLIFF:
        return _status_plateau_cliff(current_value, values)
    if category == CATEGORY_LOW_STABLE:
        return _status_low_stable(current_value, values, raw_points, now_ts=now_ts)
    if category == CATEGORY_VOLTAGE:
        return _status_voltage(current_value, values)
    if category == CATEGORY_RECHARGEABLE:
        return _status_rechargeable(current_value, raw_points, now_ts=now_ts)
    return _status_unknown_default(
        current_value, is_binary, binary_low_is_critical, raw_points, now_ts=now_ts
    )


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

    is_low = str(value) == "on" or (
        isinstance(value, (int, float)) and value >= 1.0
    )
    if not is_low:
        return STATUS_NORMAL

    if binary_low_is_critical:
        return STATUS_CRITICAL

    if len(raw_points) >= 2:
        now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
        low_since: float | None = None
        for point in reversed(raw_points):
            if point[1] >= 1.0:
                low_since = point[0]
            else:
                break
        if low_since is not None and (
            now - low_since
        ) > BINARY_CRITICAL_DAYS * 86400:
            return STATUS_CRITICAL

    return STATUS_WARNING


# --- linear ---


def _status_linear(
    value: float | str | None,
    raw_points: list[list[float]],
    all_points: list[list[float]] | None = None,
    *,
    now_ts: float | None = None,
) -> str:
    if not isinstance(value, (int, float)):
        return STATUS_NORMAL

    warning_pct, critical_pct = DEFAULT_THRESHOLDS[CATEGORY_LINEAR]
    status = STATUS_NORMAL
    if value <= critical_pct:
        status = STATUS_CRITICAL
    elif value <= warning_pct:
        status = STATUS_WARNING

    remaining = _estimate_linear(raw_points, all_points, now_ts=now_ts)
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
) -> str:
    if not isinstance(value, (int, float)) or len(values) < 5:
        return STATUS_NORMAL

    sorted_desc = sorted(values, reverse=True)
    top_n = max(1, len(sorted_desc) // 4)
    plateau = sum(sorted_desc[:top_n]) / top_n

    if plateau < 10:
        return STATUS_NORMAL

    recent = values[-min(10, len(values)) :]
    if len(recent) >= 2:
        recent_drop = max(recent) - min(recent)
        if recent_drop > plateau * 0.30:
            return STATUS_CRITICAL

    ratio = value / plateau if plateau > 0 else 1.0
    if ratio >= 0.90:
        return STATUS_NORMAL
    if ratio >= 0.70:
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
    if not isinstance(value, (int, float)) or len(values) < 5:
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
) -> str:
    if not isinstance(value, (int, float)) or len(values) < 3:
        return STATUS_NORMAL

    vmin = min(values)
    vmax = max(values)
    v_range = vmax - vmin

    # A range this small (relative to the voltage scale) is sensor noise or
    # quantization, not a real discharge curve — e.g. a coin-cell sensor that
    # only ever reports two values 12 mV apart. Treating it as a real signal
    # would peg the status at whichever extreme the current value happens to
    # sit at, often permanently.
    min_range = max(VOLTAGE_MIN_RANGE_ABS, VOLTAGE_MIN_RANGE_RATIO * vmax)
    if v_range < min_range:
        return STATUS_NORMAL

    pct = ((value - vmin) / v_range) * 100
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
    if not isinstance(value, (int, float)):
        return STATUS_NORMAL

    warning_pct, critical_pct = DEFAULT_THRESHOLDS[CATEGORY_RECHARGEABLE]

    if value <= critical_pct:
        cycle = _estimate_charge_cycle_days(raw_points)
        if _recent_recharge_detected(
            raw_points, lookback_days=cycle * 1.5, now_ts=now_ts
        ):
            return STATUS_WARNING
        return STATUS_CRITICAL

    if value <= warning_pct:
        return STATUS_WARNING
    return STATUS_NORMAL


# --- unknown_default ---


def _status_unknown_default(
    value: float | str | None,
    is_binary: bool,
    binary_low_is_critical: bool,
    raw_points: list[list[float]] | None = None,
    *,
    now_ts: float | None = None,
) -> str:
    if is_binary:
        if str(value) == "on":
            return STATUS_CRITICAL if binary_low_is_critical else STATUS_WARNING
        return STATUS_NORMAL

    if not isinstance(value, (int, float)):
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


# =====================================================================
#  Shared helpers
# =====================================================================


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

    now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
    cutoff = now - window_hours * 3600
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
) -> float | None:
    """Estimated days until the battery is empty, or None if not estimable.

    *raw_points* are the recent full-resolution points, *all_points* the
    complete chronological history (daily means + raw points) as [ts, value].
    Only archetypes with a meaningful notion of "time until empty" get an
    estimate: linear, rechargeable, voltage and plateau_cliff.
    """
    if not isinstance(current_value, (int, float)):
        return None
    if category == CATEGORY_LINEAR:
        return _estimate_linear(raw_points, all_points, now_ts=now_ts)
    if category == CATEGORY_RECHARGEABLE:
        return _estimate_rechargeable(raw_points, now_ts=now_ts)
    if category == CATEGORY_VOLTAGE:
        return _estimate_voltage(all_points, now_ts=now_ts)
    if category == CATEGORY_PLATEAU_CLIFF:
        return _estimate_plateau_cliff(all_points, now_ts=now_ts)
    return None


def _estimate_linear(
    raw_points: list[list[float]],
    all_points: list[list[float]] | None = None,
    *,
    now_ts: float | None = None,
) -> float | None:
    """Trend over the whole life of the current battery, until 0%.

    Slow linear drains change by only a few integer percent per month, so a
    short window yields a noise-dominated slope. Instead, regress over daily
    means since the last battery replacement (one point per day, so the
    hourly raw points of the last 30 days don't outweigh older history).
    Freshly replaced batteries without enough days fall back to the recent
    raw points.
    """
    if all_points:
        daily = _daily_means(all_points)
        segment = daily[_trailing_segment_start(daily, ESTIMATE_REPLACEMENT_JUMP):]
        if len(segment) >= ESTIMATE_LINEAR_MIN_DAYS:
            return estimate_remaining_days(
                segment, now_ts=now_ts, window_days=None
            )
    return estimate_remaining_days(
        raw_points, now_ts=now_ts, segment_rise=ESTIMATE_REPLACEMENT_JUMP
    )


def _daily_means(points: list[list[float]]) -> list[list[float]]:
    """Collapse [ts, value] points into one [mean ts, mean value] per UTC day."""
    buckets: dict[int, list[list[float]]] = {}
    for p in points:
        if p[1] is not None:
            buckets.setdefault(int(p[0] // 86400), []).append(p)
    return [
        [
            sum(p[0] for p in day) / len(day),
            sum(p[1] for p in day) / len(day),
        ]
        for _, day in sorted(buckets.items())
    ]


def _estimate_rechargeable(
    raw_points: list[list[float]], *, now_ts: float | None = None
) -> float | None:
    # Regress over the current discharge phase only (since the last charge).
    # While charging, the trailing phase is too short and this yields None.
    return estimate_remaining_days(
        raw_points, now_ts=now_ts, segment_rise=ESTIMATE_RECHARGE_RISE_TOL
    )


def _estimate_voltage(
    all_points: list[list[float]], *, now_ts: float | None = None
) -> float | None:
    """Days until the voltage reaches the level the previous battery died at.

    The "empty" voltage is the minimum observed *before* the current
    discharge phase. Without a previous phase (first battery ever seen),
    there is no known empty level, and the current value would trivially
    be the minimum — so no estimate.
    """
    points = [p for p in all_points if p[1] is not None]
    if len(points) < ESTIMATE_MIN_POINTS:
        return None

    vals = [p[1] for p in points]
    vmax = max(vals)
    v_range = vmax - min(vals)
    if v_range < max(VOLTAGE_MIN_RANGE_ABS, VOLTAGE_MIN_RANGE_RATIO * vmax):
        return None

    rise_tol = ESTIMATE_VOLTAGE_RISE_RATIO * v_range
    start = _trailing_segment_start(points, rise_tol)
    if start == 0:
        return None
    floor = min(p[1] for p in points[:start])

    return estimate_remaining_days(
        points, now_ts=now_ts, floor=floor, segment_rise=rise_tol
    )


def _estimate_plateau_cliff(
    all_points: list[list[float]], *, now_ts: float | None = None
) -> float | None:
    """Expected lifetime from past replacement intervals minus current age.

    Plateau batteries give no usable trend before they fall off the cliff,
    so the only signal is how long previous batteries in this device lasted.
    Needs at least two observed replacements (= one complete lifetime).
    """
    points = [p for p in all_points if p[1] is not None]
    replacements = [
        points[i][0]
        for i in range(1, len(points))
        if points[i][1] - points[i - 1][1] > ESTIMATE_REPLACEMENT_JUMP
    ]
    if len(replacements) < 2:
        return None

    lifetimes = [
        (replacements[i] - replacements[i - 1]) / 86400
        for i in range(1, len(replacements))
    ]
    now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
    age = (now - replacements[-1]) / 86400
    return max(_median(lifetimes) - age, 0.0)


def _trailing_segment_start(
    points: list[tuple[float, float]] | list[list[float]], rise_tol: float
) -> int:
    """Index where the trailing discharge phase starts.

    Walks backwards from the end and stops at the last upward step larger
    than *rise_tol* (a recharge or replacement).
    """
    for i in range(len(points) - 1, 0, -1):
        if points[i][1] - points[i - 1][1] > rise_tol:
            return i
    return 0


def estimate_remaining_days(
    raw_points: list[list[float]],
    *,
    now_ts: float | None = None,
    floor: float = 0.0,
    segment_rise: float | None = None,
    window_days: float | None = ESTIMATE_WINDOW_DAYS,
) -> float | None:
    """Linear-regression estimate of days until value reaches *floor*.

    Uses the last *window_days* of points (all points if None). With
    *segment_rise*, only
    the trailing discharge phase (after the last upward step larger than
    *segment_rise*) is used, and it must span at least
    ESTIMATE_MIN_SPAN_HOURS.
    """
    if len(raw_points) < 3:
        return None

    now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
    cutoff = now - window_days * 86400 if window_days is not None else 0.0
    recent = [
        (p[0], p[1])
        for p in raw_points
        if p[0] >= cutoff and p[1] is not None
    ]
    if segment_rise is not None:
        recent = recent[_trailing_segment_start(recent, segment_rise):]
        if (
            len(recent) >= 2
            and recent[-1][0] - recent[0][0] < ESTIMATE_MIN_SPAN_HOURS * 3600
        ):
            return None
    if len(recent) < ESTIMATE_MIN_POINTS:
        return None

    n = len(recent)
    sx = sum(t for t, _ in recent)
    sy = sum(v for _, v in recent)
    sxy = sum(t * v for t, v in recent)
    sxx = sum(t * t for t, _ in recent)

    denom = n * sxx - sx * sx
    if abs(denom) < 1e-10:
        return None

    slope = (n * sxy - sx * sy) / denom
    if slope >= 0:
        return None

    intercept = (sy - slope * sx) / n
    headroom = slope * now + intercept - floor

    if headroom <= 0:
        return 0.0

    return (-headroom / slope) / 86400


def _estimate_charge_cycle_days(raw_points: list[list[float]]) -> float:
    """Median interval between detected charge events (days)."""
    if len(raw_points) < 4:
        return 7.0

    charge_times: list[float] = []
    for i in range(1, len(raw_points)):
        prev, cur = raw_points[i - 1][1], raw_points[i][1]
        if prev is not None and cur is not None and cur - prev > 10:
            charge_times.append(raw_points[i][0])

    if len(charge_times) < 2:
        return 7.0

    intervals = [
        (charge_times[i] - charge_times[i - 1]) / 86400
        for i in range(1, len(charge_times))
    ]
    return _median(intervals)


def _recent_recharge_detected(
    raw_points: list[list[float]],
    *,
    lookback_days: float = 7.0,
    now_ts: float | None = None,
) -> bool:
    if len(raw_points) < 2:
        return False

    now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
    cutoff = now - lookback_days * 86400
    recent = [p for p in raw_points if p[0] >= cutoff]

    for i in range(1, len(recent)):
        prev, cur = recent[i - 1][1], recent[i][1]
        if prev is not None and cur is not None and cur - prev > 10:
            return True
    return False


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
    - time since last data point exceeds max(3 × median reporting interval, 24 h).
    """
    if last_update_ts is None:
        return False

    if now_ts is None:
        now_ts = dt_util.utcnow().timestamp()

    elapsed = now_ts - last_update_ts

    if value_is_unavailable and elapsed > STALE_UNAVAILABLE_HOURS * 3600:
        return True

    if median_interval is not None:
        threshold = max(
            STALE_MULTIPLIER * median_interval,
            STALE_MIN_HOURS * 3600,
        )
    else:
        threshold = STALE_MIN_HOURS * 3600

    return elapsed > threshold
