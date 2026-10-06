"""Constants for the BatteryBrain integration."""

from __future__ import annotations

import logging

DOMAIN = "battery_brain"
LOGGER = logging.getLogger(__package__)

# --- Update intervals (seconds) ---
COORDINATOR_UPDATE_INTERVAL = 300  # 5 minutes
CATEGORY_RECLASSIFY_INTERVAL = 3600  # 1 hour

# --- History thresholds (days) ---
MIN_HISTORY_DAYS = 7
LOW_CONFIDENCE_DAYS = 14
MEDIUM_CONFIDENCE_DAYS = 30

# --- Stale detection ---
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

# --- Remaining-lifetime estimation ---
# Trend regression only looks at this many trailing days of raw points.
ESTIMATE_WINDOW_DAYS = 14
# A single upward step larger than this (pp) is a battery replacement.
ESTIMATE_REPLACEMENT_JUMP = 20.0
# Rechargeables: an upward step larger than this (pp) ends the current
# discharge phase (charging); smaller rises are treated as noise.
ESTIMATE_RECHARGE_RISE_TOL = 2.0
# Voltage: an upward step larger than this fraction of the observed
# voltage range ends the current discharge phase (replacement/recharge).
ESTIMATE_VOLTAGE_RISE_RATIO = 0.2
# Linear: minimum days of history since the last replacement before the
# long-term (daily-mean) regression is used instead of the 14-day window.
ESTIMATE_LINEAR_MIN_DAYS = 7
# Minimum size of the discharge phase used for a regression.
ESTIMATE_MIN_POINTS = 3
ESTIMATE_MIN_SPAN_HOURS = 1.0

# --- Binary sensor thresholds (days) ---
BINARY_CRITICAL_DAYS = 3

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

# --- Developer / test mode ---
CONF_DEVELOPER_MODE = "developer_mode"
TEST_MODE_TIME_FACTOR = 200
