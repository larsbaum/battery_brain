"""Constants for the BatteryBrain integration."""

from __future__ import annotations

import logging

DOMAIN = "battery_brain"
LOGGER = logging.getLogger(__package__)

# --- Update intervals (seconds) ---
COORDINATOR_UPDATE_INTERVAL = 300  # 5 minutes
CATEGORY_RECLASSIFY_INTERVAL = 3600  # 1 hour
# The production log gets a full snapshot of all batteries this often.
PRODUCTION_SNAPSHOT_INTERVAL = 3600  # 1 hour

# --- Discovery ---
# Voltage-class sensors count as batteries within this range (volts);
# filters out mains voltage. Once tracked, a sensor stays tracked even if
# its value leaves the range (e.g. a dead battery reporting 0 V).
VOLTAGE_DISCOVERY_MIN = 0.3
VOLTAGE_DISCOVERY_MAX = 20.0
ATTR_BATTERY_LEVEL = "battery_level"

# --- Classification ---
# A change from one archetype to another only takes effect after it was
# the result of this many consecutive classifications (one per hour), so
# a borderline battery doesn't flap. The first classification, leaving
# unknown_default and manual reclassification apply immediately.
CATEGORY_CONFIRMATIONS = 3

# low_stable only applies if the battery has stopped declining: one that
# dropped at least LOW_STABLE_MAX_DECLINE pp over the last
# LOW_STABLE_TREND_DAYS (a clear trend, r² ≥ LOW_STABLE_MIN_R2, not noise)
# is still draining, however low and steady it looks. The current battery
# must also have been observed for LOW_STABLE_TREND_DAYS: a few days of
# readings can't tell a stuck battery from a slowly draining one.
LOW_STABLE_TREND_DAYS = 30
LOW_STABLE_MAX_DECLINE = 1.5
LOW_STABLE_MIN_R2 = 0.3

# The lowest voltage of the previous battery is its device's "empty" — unless
# the history has this many discharge phases: then it is a recharged source
# (car battery, hand-charged Li-ion node) and the typical cut-off applies.
VOLTAGE_RECHARGED_MIN_PHASES = 4

# A single reading that drops at least UNCONFIRMED_DROP_PP below the one
# before (UNCONFIRMED_DROP_RATIO for voltages) is a likely glitch (Z-Wave
# devices sometimes report 0 %): it doesn't change status or remaining time
# until another reading confirms it or UNCONFIRMED_DROP_HOURS have passed.
UNCONFIRMED_DROP_PP = 30.0
UNCONFIRMED_DROP_RATIO = 0.3
UNCONFIRMED_DROP_HOURS = 2.0

# Fast charging in hourly (imported) history: a phone charges 40–60 pp per
# hour, so every hourly step is larger than a gradual charge allows. A rise
# in at least two steps within RECHARGE_FAST_MAX_HOURS counts as a charge
# too; a single replacement can look like that, so it takes at least
# RECHARGE_FAST_MIN_EVENTS charges (gradual + fast) to be rechargeable.
RECHARGE_FAST_MAX_HOURS = 12.0
RECHARGE_FAST_MIN_EVENTS = 3

# --- History thresholds (days) ---
MIN_HISTORY_DAYS = 7
LOW_CONFIDENCE_DAYS = 14
MEDIUM_CONFIDENCE_DAYS = 30

# --- Stale detection ---
# A restored entity (left in the registry, nothing provides it) is ignored
# once it has been restored for this long (integrations may load late).
ORPHAN_GRACE_MINUTES = 15
STALE_MULTIPLIER = 3
STALE_MIN_HOURS = 24
STALE_UNAVAILABLE_HOURS = 1

# --- Status values ---
STATUS_NORMAL = "normal"
STATUS_WARNING = "warning"
STATUS_CRITICAL = "critical"

# --- Categories (archetypes) ---
CATEGORY_LINEAR = "linear"
CATEGORY_PLATEAU_CLIFF = "plateau_cliff"
CATEGORY_LOW_STABLE = "low_stable"
CATEGORY_VOLTAGE = "voltage"
CATEGORY_BINARY = "binary"
CATEGORY_RECHARGEABLE = "rechargeable"
CATEGORY_UNKNOWN_DEFAULT = "unknown_default"

# --- Confidence levels ---
CONFIDENCE_DEFAULT = "default"
CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

# --- Default thresholds per category ---
# {category: (warning_threshold, critical_threshold)}
# For percentage-based categories, thresholds are in percent (0-100).
DEFAULT_THRESHOLDS: dict[str, tuple[float, float]] = {
    CATEGORY_LINEAR: (20.0, 10.0),
    CATEGORY_PLATEAU_CLIFF: (20.0, 10.0),
    CATEGORY_LOW_STABLE: (20.0, 10.0),
    CATEGORY_VOLTAGE: (25.0, 10.0),
    CATEGORY_RECHARGEABLE: (15.0, 5.0),
    CATEGORY_UNKNOWN_DEFAULT: (20.0, 10.0),
}

# --- Prediction thresholds (days) ---
PREDICTION_WARNING_DAYS = 7
PREDICTION_CRITICAL_DAYS = 2
# plateau_cliff: the drain accelerates towards the end, so a trend
# over-estimates the time left; both horizons are longer than linear.
# Leaving the plateau alone is no reason to warn.
PLATEAU_CLIFF_WARNING_DAYS = 21
PLATEAU_CLIFF_CRITICAL_DAYS = 5

# --- Remaining-lifetime estimation ---
# Readings are interpolated linearly (the last one holds until "now") and
# resampled into time-weighted buckets before any regression, so
# change-only and hourly history weigh the same and idle periods count
# as "no drain".
#
# Short phases (< ESTIMATE_LINEAR_MIN_DAYS) are regressed over hourly
# buckets of at most this many trailing days.
ESTIMATE_WINDOW_DAYS = 14
# A rise larger than this (pp, cumulative over consecutive rising
# readings) is a battery replacement.
ESTIMATE_REPLACEMENT_JUMP = 20.0
# Rechargeables: a rise larger than this (pp) ends the current discharge
# phase (charging); smaller rises are treated as noise.
ESTIMATE_RECHARGE_RISE_TOL = 2.0
# Voltage: a rise larger than this fraction of the observed voltage
# range, and at least ESTIMATE_VOLTAGE_RISE_MIN_RATIO of the maximum
# voltage, ends the current discharge phase (replacement/recharge). The
# second bound keeps daily temperature swings from splitting phases.
ESTIMATE_VOLTAGE_RISE_RATIO = 0.2
ESTIMATE_VOLTAGE_RISE_MIN_RATIO = 0.08
# Minimum days since the last replacement before the long-term
# (daily-bucket) regression is used instead of the hourly window.
ESTIMATE_LINEAR_MIN_DAYS = 7
# Long-term regressions weight recent days more, with a half-life of
# max(ESTIMATE_HALF_LIFE_MIN_DAYS, phase length × ESTIMATE_HALF_LIFE_FRACTION),
# so an accelerating drain near the end of a battery's life is followed
# without letting a few noisy days dominate.
ESTIMATE_HALF_LIFE_MIN_DAYS = 30
ESTIMATE_HALF_LIFE_FRACTION = 1 / 3
# Most batteries drain faster towards the end (alkaline, coin cells). The
# slope is therefore also measured over ever shorter recent windows
# (phase/2, phase/4, … down to ESTIMATE_RECENT_MIN_DAYS); the shortest
# window that still saw a clear decline (≥ ESTIMATE_RECENT_MIN_DECLINE pp,
# or ESTIMATE_RECENT_MIN_DECLINE_RATIO of the full-to-empty voltage span,
# with R² ≥ ESTIMATE_RECENT_MIN_R2) wins over the long-term trend, so a
# few quantization steps never decide on their own.
ESTIMATE_RECENT_MIN_DAYS = 3
ESTIMATE_RECENT_MIN_DECLINE = 10.0
ESTIMATE_RECENT_MIN_DECLINE_RATIO = 0.10
ESTIMATE_RECENT_MIN_R2 = 0.5
# Minimum resampled buckets and time span of a phase used for a regression.
ESTIMATE_MIN_POINTS = 3
ESTIMATE_MIN_SPAN_HOURS = 1.0
# Rechargeables: no estimate while charging, i.e. while the last rise
# happened less than this long ago.
ESTIMATE_CHARGING_GRACE_HOURS = 2.0
# Rechargeables: past discharge phases count towards the typical drain
# rate only if they lasted and dropped at least this much.
ESTIMATE_RECHARGE_MIN_PHASE_HOURS = 2.0
ESTIMATE_RECHARGE_MIN_PHASE_DROP = 5.0
# Rechargeables: the current phase's own rate fully replaces the typical
# rate once it has dropped this many pp (linear blend below that).
ESTIMATE_RECHARGE_FULL_WEIGHT_DROP = 20.0
# Rechargeables: number of most recent past phases used for the median.
ESTIMATE_RECHARGE_HISTORY_PHASES = 10
# unknown_default: only clearly declining trends get an estimate.
ESTIMATE_UNKNOWN_MIN_DROP = 5.0
ESTIMATE_UNKNOWN_MIN_R2 = 0.6
# plateau_cliff: below this fraction of the plateau the battery has left
# its plateau (the knee) and the post-knee trend is used; the knee
# starts at the last reading at or above PLATEAU_KNEE_START_RATIO.
PLATEAU_KNEE_RATIO = 0.90
PLATEAU_KNEE_START_RATIO = 0.95
# Two replacement events closer than this are the same event.
REPLACEMENT_MERGE_DAYS = 2
# A rise only counts as a replacement if the new level holds this long
# (filters solar spikes and short charge bursts) and reaches at least
# REPLACEMENT_MIN_LEVEL percent (a new battery reports a high level; a
# sunny week lifting a solar sensor doesn't get there).
REPLACEMENT_HOLD_HOURS = 24
REPLACEMENT_MIN_LEVEL = 50.0
# For classification, a rise to at least this level marks a new battery
# right away (solar spikes on real outdoor sensors stay below ~65 %).
REPLACEMENT_IMMEDIATE_LEVEL = 90.0

# --- Voltage: typical "empty" voltage and lifetime by full voltage ---
# The empty voltage is the reference until a battery replacement has been
# observed (then the level the previous battery ended at is used); the
# lifetime is the last-resort estimate (see TYPICAL_LIFETIME_DAYS).
# (max full voltage, empty voltage, typical lifetime in days), volts,
# first match wins.
VOLTAGE_EMPTY_TABLE: tuple[tuple[float, float, float], ...] = (
    (1.8, 1.0, 365),  # single cell: alkaline, NiMH, 1.5 V lithium
    (3.5, 2.3, 730),  # 2× AA/AAA, CR2032/CR2450/CR123A
    (5.2, 3.3, 365),  # Li-ion/LiPo 1S, 3× AA
    (7.0, 4.4, 365),  # 4× AA
    (10.0, 6.6, 365),  # 9 V block, Li-ion 2S
    (15.0, 11.8, 365),  # 12 V lead-acid / LiFePO4
)
# Above the table: empty at this fraction of the full voltage.
VOLTAGE_EMPTY_FALLBACK_RATIO = 0.78
VOLTAGE_FALLBACK_LIFETIME_DAYS = 365

# --- Remaining lifetime without a measurable trend (lifetime.py) ---
# Every battery gets an estimate; remaining_source tells where it is from:
# measured (own trend), history (own past batteries / discharge phases),
# similar (other batteries of the same device model or category),
# typical (the fixed values below) or stale (entity unavailable; the last
# known value was used). Only measured estimates ever affect the status.
REMAINING_MEASURED = "measured"
REMAINING_HISTORY = "history"
REMAINING_SIMILAR = "similar"
REMAINING_TYPICAL = "typical"
REMAINING_STALE = "stale"
# Typical battery lifetime per archetype (days). Voltage: VOLTAGE_EMPTY_TABLE.
TYPICAL_LIFETIME_DAYS: dict[str, float] = {
    CATEGORY_LINEAR: 540,
    CATEGORY_PLATEAU_CLIFF: 730,
    CATEGORY_LOW_STABLE: 730,
    CATEGORY_BINARY: 730,
    CATEGORY_UNKNOWN_DEFAULT: 365,
}
# Binary sensors: typical time from the low signal until the battery dies.
TYPICAL_LOW_SIGNAL_DAYS = 30
# Rechargeables without any discharge history: days a full charge lasts.
TYPICAL_RECHARGE_FULL_DAYS = 2.0
# A battery older than its expected lifetime still gets at least this
# fraction of it (it obviously works), never 0.
LIFETIME_MIN_REMAINING_FRACTION = 0.1
# Category-wide household lifetimes need at least this many other batteries.
SIMILAR_MIN_CATEGORY_SAMPLES = 2
# Drain rate of a battery for "similar": average since the battery was
# inserted, only after this long and this much of a drop.
SIMILAR_RATE_MIN_DAYS = 14
SIMILAR_RATE_MIN_DROP = 5.0
# Estimates are capped so estimated_empty is always a valid date.
ESTIMATE_MAX_DAYS = 36500

# Devices kept charged (dock, charge-window automation): ≥ this many rises
# of RECHARGE_EVENT_MIN_RISE in the raw history; their discharge phases may
# be as short as CHARGED_DEVICE_MIN_PHASE_HOURS (a robot's cleaning run).
CHARGED_DEVICE_MIN_CHARGES = 2
CHARGED_DEVICE_MIN_PHASE_HOURS = 0.5

# Battery levels reported as text (some integrations), mapped to percent.
TEXT_BATTERY_LEVELS: dict[str, float] = {
    "empty": 0.0,
    "critical": 5.0,
    "low": 15.0,
    "medium": 50.0,
    "high": 90.0,
    "full": 100.0,
}
# Text levels that are the device's own low signal. In the threshold alert
# mode they count like a binary low signal, whatever the threshold.
TEXT_LOW_LEVELS = frozenset({"low", "critical", "empty"})

# --- Binary sensor thresholds (days) ---
BINARY_CRITICAL_DAYS = 3

# --- Rechargeable status ---
# A rise of at least this many pp counts as a recharge; a battery at the
# critical level that was recharged within 1.5 × its typical charge cycle
# is only WARNING (it is part of a normal cycle).
RECHARGE_EVENT_MIN_RISE = 10.0
RECHARGE_DEFAULT_CYCLE_DAYS = 7.0

# --- Voltage status: minimum meaningful observed range ---
# A range smaller than this is treated as sensor noise/quantization rather
# than a real discharge curve, and yields STATUS_NORMAL instead of a
# (potentially permanent) false STATUS_CRITICAL.
VOLTAGE_MIN_RANGE_ABS = 0.01  # volts
VOLTAGE_MIN_RANGE_RATIO = 0.03  # fraction of the observed max voltage

# --- Rechargeable detection: minimum peak height to count a charge cycle ---
# A rise only counts as a genuine recharge if it reaches at least this
# fraction of the all-time observed maximum, filtering out periodic
# environmental artifacts (e.g. daily temperature swings) that never
# approach the device's real "full" level.
RECHARGE_MIN_PEAK_RATIO = 0.75

# --- Status noise smoothing (low_stable / unknown_default) ---
# Instead of comparing the single latest raw value against thresholds,
# use a representative recent value (a high percentile over a trailing
# window) so short-lived environmental noise doesn't trigger false
# warning/critical status. Falls back to the raw current value when
# there isn't enough recent history to smooth over.
NOISE_SMOOTHING_WINDOW_HOURS = 36
NOISE_SMOOTHING_PERCENTILE = 0.75
NOISE_SMOOTHING_MIN_POINTS = 5

# --- Storage ---
STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

# --- History retention ---
HISTORY_RAW_DAYS = 30
HISTORY_MAX_DAYS = 365

# --- Options flow keys ---
OPT_SCAN_BATTERY_LEVEL_ATTR = "scan_battery_level_attr"
OPT_EXCLUDE_ENTITIES = "exclude_entities"
OPT_EXCLUDE_INTEGRATIONS = "exclude_integrations"
OPT_BINARY_LOW_IS_CRITICAL = "binary_low_is_critical"
OPT_INCLUDE_VOLTAGE_SENSORS = "include_voltage_sensors"
OPT_ALERT_MODE = "alert_mode"
OPT_WARNING_THRESHOLD = "warning_threshold"

# --- Alert mode ---
# smart: per-archetype rules including predictions (default).
# threshold: opt-in, a fixed percentage decides (WARNING at or below it,
# CRITICAL at or below half of it). Predictions are still computed and
# shown, they just don't change the status. Voltage and binary batteries
# and stale detection behave the same in both modes.
ALERT_MODE_SMART = "smart"
ALERT_MODE_THRESHOLD = "threshold"
DEFAULT_WARNING_THRESHOLD = 10
WARNING_THRESHOLD_MIN = 5
WARNING_THRESHOLD_MAX = 50

# --- Developer / test mode ---
CONF_DEVELOPER_MODE = "developer_mode"
TEST_MODE_TIME_FACTOR = 200
