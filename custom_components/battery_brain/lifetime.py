"""Remaining lifetime when a battery's own trend can't tell.

analysis.estimate_remaining() measures the trend of the current battery
("measured"). When that gives nothing — a coin cell on its plateau, a
button stuck at 1 %, a binary sensor, a device that is kept charged —
fallback_remaining() still estimates, and says where the number comes from:

- history: this device's own past — lifetimes between battery
  replacements, discharge rates between charges, how long its low-battery
  signal lasted before
- similar: other batteries of the same device model (lifetimes and drain
  rates), or of the same category (lifetimes only)
- typical: fixed typical lifetimes (const.TYPICAL_LIFETIME_DAYS)

The age of the current battery is the time since its last replacement, or
— if none was ever seen — since BatteryBrain first saw it (a lower bound).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .analysis import is_charged_device, typical_discharge_rate, voltage_charge
from .const import (
    CATEGORY_BINARY,
    CATEGORY_LINEAR,
    CATEGORY_RECHARGEABLE,
    CATEGORY_UNKNOWN_DEFAULT,
    CATEGORY_VOLTAGE,
    CHARGED_DEVICE_MIN_PHASE_HOURS,
    LIFETIME_MIN_REMAINING_FRACTION,
    REMAINING_HISTORY,
    REMAINING_SIMILAR,
    REMAINING_TYPICAL,
    SIMILAR_MIN_CATEGORY_SAMPLES,
    TYPICAL_LIFETIME_DAYS,
    TYPICAL_LOW_SIGNAL_DAYS,
    TYPICAL_RECHARGE_FULL_DAYS,
)

_DAY = 86400.0


@dataclass
class Household:
    """Lifetimes and drain rates seen across all batteries (for "similar").

    Only measured or device-history values go in, never estimates made
    from typical values, so nothing feeds on itself.
    """

    # (entity_id, device model, category, lifetime in days)
    lifetimes: list[tuple[str, str | None, str, float]] = field(
        default_factory=list
    )
    # (entity_id, device model, drain in pp per day)
    rates: list[tuple[str, str | None, float]] = field(default_factory=list)

    def add_replacements(
        self,
        entity_id: str,
        model: str | None,
        category: str,
        replacements: list[float],
    ) -> None:
        for days in lifetimes_between(replacements):
            self.lifetimes.append((entity_id, model, category, days))

    def lifetimes_like(
        self, entity_id: str, model: str | None, category: str
    ) -> list[float]:
        """Lifetimes of other batteries of the same model, else category."""
        if model:
            same_model = [
                d for e, m, _, d in self.lifetimes if e != entity_id and m == model
            ]
            if same_model:
                return same_model
        same_category = [
            (e, d) for e, _, c, d in self.lifetimes if e != entity_id and c == category
        ]
        if len({e for e, _ in same_category}) >= SIMILAR_MIN_CATEGORY_SAMPLES:
            return [d for _, d in same_category]
        return []

    def rates_like(self, entity_id: str, model: str | None) -> list[float]:
        """Drain rates of other batteries of the same device model."""
        if not model:
            return []
        return [r for e, m, r in self.rates if e != entity_id and m == model]


def lifetimes_between(replacements: list[float]) -> list[float]:
    """Days between consecutive battery replacements."""
    return [(b - a) / _DAY for a, b in zip(replacements, replacements[1:])]


def fallback_remaining(
    *,
    entity_id: str,
    category: str,
    level: float | None,
    unit: str | None,
    raw_points: list[list[float]],
    all_points: list[list[float]],
    replacements: list[float],
    first_seen: float,
    now: float,
    model: str | None,
    household: Household,
) -> tuple[float, str]:
    """(days until empty, source) for a battery without a measured trend.

    *level* is the current (or last known) reading: percent, volts, or
    1.0/0.0 for a binary low signal; None if there never was one.
    """
    if category == CATEGORY_RECHARGEABLE or (
        category == CATEGORY_UNKNOWN_DEFAULT and is_charged_device(raw_points)
    ):
        return _runtime_without_charging(raw_points, level)
    if category == CATEGORY_BINARY and level is not None and level >= 1.0:
        return _until_low_signal_ends(all_points, now)

    battery_since = replacements[-1] if replacements else first_seen
    age = max((now - battery_since) / _DAY, 0.0)

    own = lifetimes_between(replacements)
    if own:
        return _left_of(_median(own), age), REMAINING_HISTORY

    if category in (CATEGORY_LINEAR, CATEGORY_UNKNOWN_DEFAULT) and level:
        rates = household.rates_like(entity_id, model)
        if rates:
            return level / _median(rates), REMAINING_SIMILAR

    similar = household.lifetimes_like(entity_id, model, category)
    if similar:
        return _left_of(_median(similar), age), REMAINING_SIMILAR

    lifetime = TYPICAL_LIFETIME_DAYS.get(
        category, TYPICAL_LIFETIME_DAYS[CATEGORY_UNKNOWN_DEFAULT]
    )
    charge: float | None = None
    if category == CATEGORY_VOLTAGE and level is not None and all_points:
        charge, lifetime = voltage_charge([p[1] for p in all_points], level, unit)
    elif (
        category in (CATEGORY_LINEAR, CATEGORY_UNKNOWN_DEFAULT)
        and level is not None
    ):
        charge = min(max(level / 100, 0.0), 1.0)
    if not replacements and charge is not None:
        # Age unknown: the charge level says more than the observed time.
        remaining = max(lifetime * charge, lifetime * LIFETIME_MIN_REMAINING_FRACTION)
        return remaining, REMAINING_TYPICAL
    return _left_of(lifetime, age), REMAINING_TYPICAL


def _runtime_without_charging(
    raw_points: list[list[float]], level: float | None
) -> tuple[float, str]:
    """How long the current charge lasts at the device's usual drain."""
    charge = level if level is not None else 100.0
    rate = typical_discharge_rate(
        raw_points, min_phase_hours=CHARGED_DEVICE_MIN_PHASE_HOURS
    )
    if rate:
        return max(charge, 0.0) / rate, REMAINING_HISTORY
    return TYPICAL_RECHARGE_FULL_DAYS * max(charge, 0.0) / 100, REMAINING_TYPICAL


def _until_low_signal_ends(
    points: list[list[float]], now: float
) -> tuple[float, str]:
    """Binary sensor reporting low: its usual lead time minus time spent low.

    The lead time of a past battery is the time from its low signal to its
    replacement (the signal clearing for good).
    """
    runs = _low_runs(points)
    leads = [(end - start) / _DAY for start, end in runs if end is not None]
    lead, source = (
        (_median(leads), REMAINING_HISTORY)
        if leads
        else (TYPICAL_LOW_SIGNAL_DAYS, REMAINING_TYPICAL)
    )
    low_since = runs[-1][0] if runs and runs[-1][1] is None else now
    return _left_of(lead, (now - low_since) / _DAY), source


def _low_runs(points: list[list[float]]) -> list[tuple[float, float | None]]:
    """(start, end) of each period with a low signal; end None if ongoing."""
    runs: list[tuple[float, float | None]] = []
    start: float | None = None
    for ts, value in points:
        if value is None:
            continue
        if value >= 1.0 and start is None:
            start = ts
        elif value < 1.0 and start is not None:
            runs.append((start, ts))
            start = None
    if start is not None:
        runs.append((start, None))
    return runs


def _left_of(lifetime: float, age: float) -> float:
    """Lifetime minus age, but never less than a fraction of the lifetime."""
    return max(lifetime - age, lifetime * LIFETIME_MIN_REMAINING_FRACTION)


def _median(values: list[float]) -> float:
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
