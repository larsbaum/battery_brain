# BatteryBrain

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/larsbaum/battery_brain.svg)](https://github.com/larsbaum/battery_brain/releases)

Intelligent battery health analysis for Home Assistant.

BatteryBrain automatically discovers all battery entities in your Home Assistant instance, learns their behavior patterns from historical data, and derives a health status (**normal** / **warning** / **critical**) for each battery — with zero configuration required.

## Features

- **Zero-config auto-discovery** of all battery entities (`device_class: battery`)
- **Behavioral classification** into archetypes (linear, plateau-cliff, low-stable, voltage, binary, rechargeable)
- **Per-battery health status** with confidence level and staleness detection
- **Remaining lifetime estimation** for linear-drain batteries
- **Summary sensors** for dashboards and automations
- **Own history storage** with intelligent aggregation (30 days raw, up to 1 year aggregated)

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/larsbaum/battery_brain` with category **Integration**
4. Click **Install**
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration → BatteryBrain**

### Manual

1. Copy `custom_components/battery_brain/` to your `config/custom_components/` directory
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration → BatteryBrain**

## Sensors

| Entity | State | Attributes |
|---|---|---|
| `sensor.batteries_normal` | Count of normal batteries | `batteries`: list of names |
| `sensor.batteries_warning` | Count of warning batteries | `batteries`: list of names |
| `sensor.batteries_critical` | Count of critical batteries | `batteries`: list of names |
| `sensor.all_batteries` | Total monitored batteries | Per-battery dict with category, status, last_value, confidence, stale, source_entity |

## Options

Access via **Settings → Devices & Services → BatteryBrain → Configure**:

- **Scan for battery_level attributes** — also monitor entities with a `battery_level` attribute
- **Treat binary low-battery as critical** — escalate binary sensors from warning to critical
- **Excluded entities** — select entities to exclude from monitoring

## Battery Categories (Archetypes)

| Category | Description |
|---|---|
| `linear` | Steady, roughly monotonic drain |
| `plateau_cliff` | Stays high, then drops sharply (typical for coin cells) |
| `low_stable` | Reports persistently low values but keeps working |
| `voltage` | Reports voltage instead of percentage |
| `binary` | Binary sensor (low / normal) |
| `rechargeable` | Regular charge/discharge cycles |
| `unknown_default` | Default until enough history is available |

## How It Works

1. **Discovery** — scans for all entities with `device_class: battery`
2. **History seeding** — on first run, imports historical data from the HA recorder
3. **Classification** — after 7+ days of data, classifies each battery into an archetype
4. **Status derivation** — applies category-specific thresholds and pattern analysis
5. **Staleness detection** — flags batteries that stop reporting

## License

MIT
