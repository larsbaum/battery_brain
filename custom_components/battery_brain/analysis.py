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
    PREDICTION_CRITICAL_DAYS,
    PREDICTION_WARNING_DAYS,
    STALE_MIN_HOURS,
    STALE_MULTIPLIER,
    STALE_UNAVAILABLE_HOURS,
    STATUS_CRITICAL,
    STATUS_NORMAL,
    STATUS_WARNING,
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
      then rises gradually over ≥6 steps, each step ≤15 pp (gradual recharge).
    - Battery replacement: value jumps instantly by >15 pp in a single step — this
      resets the tracking and does NOT count as a charge event.
    - Low-stable / erratic: never drops 15 pp from its local peak, so the discharge
      gate is never opened and no charge events are counted.

    This algorithm works for both per-tick raw data (step size ≈0.15 pp/tick) and
    coarser aggregated data (step size ≈1–15 pp/day).
    """
    if len(values) < 10:
        return False

    _MIN_DISCHARGE = 15.0   # must drop this far below local peak to enter discharge state
    _MIN_CUMULATIVE = 30.0  # cumulative rise required to count as one charge cycle
    _MAX_SINGLE_STEP = 15.0 # single step above this → replacement event, resets tracking
    _MIN_STEPS = 6          # minimum consecutive rising steps (ensures gradual, not instant)

    charge_events = 0
    peak = values[0]
    trough: float | None = None
    cumulative_rise = 0.0
    step_count = 0

    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]

        # --- Update local peak ---
        if values[i] > peak:
            if delta > _MAX_SINGLE_STEP:
                # Jumped up too fast → battery replacement; reset everything
                trough = None
                cumulative_rise = 0.0
                step_count = 0
            peak = values[i]

        # --- Open discharge gate: dropped MIN_DISCHARGE below local peak ---
        if peak - values[i] >= _MIN_DISCHARGE:
            if trough is None or values[i] < trough:
                trough = values[i]

        # --- Track gradual charging after a trough ---
        if trough is not None:
            if delta > _MAX_SINGLE_STEP:
                # Instant jump → replacement, not recharge
                trough = None
                peak = values[i]
                cumulative_rise = 0.0
                step_count = 0
            elif delta > 0.5:
                cumulative_rise += delta
                step_count += 1
                if cumulative_rise >= _MIN_CUMULATIVE and step_count >= _MIN_STEPS:
                    charge_events += 1
                    trough = None
                    peak = values[i]
                    cumulative_rise = 0.0
                    step_count = 0
            elif delta < -0.5:
                # Fell back down during apparent charging → reset rise tracking
                cumulative_rise = 0.0
                step_count = 0

    return charge_events >= 2


def _is_low_stable(values: list[float]) -> bool:
    """Median below 30 % with low variance."""
    if len(values) < 5:
        return False

    if _median(values) >= 30:
        return False

    mean_val = sum(values) / len(values)
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
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
    """Mostly monotonic decline with an overall drop > 5 pp."""
    if len(values) < 5:
        return False

    decreases = increases = 0
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        if d < -0.5:
            decreases += 1
        elif d > 0.5:
            increases += 1

    total = decreases + increases
    if total == 0:
        return False

    return (decreases / total) > 0.65 and (values[-1] - values[0]) < -5


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
) -> str:
    """Return normal / warning / critical for *current_value*."""
    if category == CATEGORY_BINARY:
        return _status_binary(
            current_value, raw_points, binary_low_is_critical, now_ts=now_ts
        )
    if category == CATEGORY_LINEAR:
        return _status_linear(current_value, raw_points, now_ts=now_ts)
    if category == CATEGORY_PLATEAU_CLIFF:
        return _status_plateau_cliff(current_value, values)
    if category == CATEGORY_LOW_STABLE:
        return _status_low_stable(current_value, values)
    if category == CATEGORY_VOLTAGE:
        return _status_voltage(current_value, values)
    if category == CATEGORY_RECHARGEABLE:
        return _status_rechargeable(current_value, raw_points, now_ts=now_ts)
    return _status_unknown_default(
        current_value, is_binary, binary_low_is_critical
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

    remaining = estimate_remaining_days(raw_points, now_ts=now_ts)
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
    if ratio >= 0.95:
        return STATUS_NORMAL
    if ratio >= 0.70:
        return STATUS_WARNING
    return STATUS_CRITICAL


# --- low_stable ---


def _status_low_stable(
    value: float | str | None,
    values: list[float],
) -> str:
    if not isinstance(value, (int, float)) or len(values) < 5:
        return STATUS_NORMAL

    sorted_vals = sorted(values)
    idx_5 = max(0, int(len(sorted_vals) * 0.05))
    floor = sorted_vals[idx_5]

    diff = floor - value
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

    if v_range < 0.01:
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
) -> str:
    if is_binary:
        if str(value) == "on":
            return STATUS_CRITICAL if binary_low_is_critical else STATUS_WARNING
        return STATUS_NORMAL

    if not isinstance(value, (int, float)):
        return STATUS_NORMAL

    warning_pct, critical_pct = DEFAULT_THRESHOLDS[CATEGORY_UNKNOWN_DEFAULT]
    if value <= critical_pct:
        return STATUS_CRITICAL
    if value <= warning_pct:
        return STATUS_WARNING
    return STATUS_NORMAL


# =====================================================================
#  Shared helpers
# =====================================================================


def estimate_remaining_days(
    raw_points: list[list[float]], *, now_ts: float | None = None
) -> float | None:
    """Linear-regression estimate of days until value reaches zero."""
    if len(raw_points) < 3:
        return None

    now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
    cutoff = now - 14 * 86400
    recent = [
        (p[0], p[1])
        for p in raw_points
        if p[0] >= cutoff and p[1] is not None
    ]
    if len(recent) < 3:
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
    current_est = slope * now + intercept

    if current_est <= 0:
        return 0.0

    return (-current_est / slope) / 86400


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
