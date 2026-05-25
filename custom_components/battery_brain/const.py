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

# --- Binary sensor thresholds (days) ---
BINARY_CRITICAL_DAYS = 3

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
