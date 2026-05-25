# BatteryBrain

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/larsbaum/battery_brain.svg)](https://github.com/larsbaum/battery_brain/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.6%2B-blue.svg)](https://www.home-assistant.io/)
[![Beta](https://img.shields.io/badge/Status-Beta-yellow.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Intelligent battery health monitoring for Home Assistant** — automatically discovers all your batteries, learns their behavior, and tells you which ones actually need attention.

> Stop guessing based on percentages. BatteryBrain classifies each battery by how it *behaves* and applies smart thresholds — so a coin cell sitting at 1% for months doesn't trigger a false alarm, but a steadily draining sensor gets flagged before it dies.

---

<!-- TODO: Screenshot of the BatteryBrain dashboard showing all four sensors -->
<!-- Place a screenshot here: docs/images/dashboard_overview.png -->
![Dashboard Overview](docs/images/dashboard_overview.png)

---

## Key Features

- **Zero-config auto-discovery** — finds all battery entities automatically, including voltage-based and binary sensors
- **Behavioral classification** — categorizes batteries into 7 archetypes based on their actual drain patterns, not just a percentage
- **Smart health status** — each battery gets a **Normal** / **Warning** / **Critical** status using category-specific thresholds
- **Stale detection** — flags batteries that stop reporting
- **Remaining lifetime estimation** — for linear-drain batteries
- **History seeding** — imports up to 1 year of existing data from the HA recorder on first setup, so classification starts immediately
- **Summary sensors** — ready-made sensors for dashboards and automations

---

## Installation

### HACS (recommended)

1. Open **HACS** in your Home Assistant instance
2. Click the three-dot menu (top right) **> Custom repositories**
3. Add this URL with category **Integration**:
   ```
   https://github.com/larsbaum/battery_brain
   ```
4. Search for **BatteryBrain** and click **Install**
5. **Restart** Home Assistant
6. Go to **Settings > Devices & Services > Add Integration** and search for **BatteryBrain**

### Manual Installation

1. Download the [latest release](https://github.com/larsbaum/battery_brain/releases)
2. Copy the `custom_components/battery_brain/` folder into your Home Assistant `config/custom_components/` directory
3. **Restart** Home Assistant
4. Go to **Settings > Devices & Services > Add Integration** and search for **BatteryBrain**

---

## Setup

After adding the integration, BatteryBrain starts working immediately:

1. It **discovers** all battery entities in your system
2. It **imports historical data** from the HA recorder (up to 1 year)
3. After **7 days of data**, it classifies each battery into an archetype
4. It **derives a health status** for each battery based on its category

> **Note:** If you have existing recorder history, most batteries will be classified right away. New batteries need about 7 days of data before classification.

---

## Sensors

BatteryBrain creates four summary sensors:

| Entity | State | Attributes |
|---|---|---|
| `sensor.battery_brain_all_batteries` | Total number of monitored batteries | Per-battery details (category, status, value, confidence, stale) |
| `sensor.battery_brain_batteries_normal` | Count of healthy batteries | List of battery names and details |
| `sensor.battery_brain_batteries_warning` | Count of batteries needing attention | List of battery names and details |
| `sensor.battery_brain_batteries_critical` | Count of batteries needing replacement | List of battery names and details |

Each sensor carries **detailed attributes** for every battery in its group, including:
- `category` — the detected archetype (e.g. `linear`, `rechargeable`)
- `status` — current health status
- `last_value` — last reported battery level
- `confidence` — classification confidence (`default` / `low` / `medium` / `high`)
- `stale` — whether the battery has stopped reporting
- `source_entity` — the original entity ID

Use these attributes to build detailed dashboards or trigger automations.

<!-- TODO: Screenshot of sensor attributes in the HA Developer Tools -->
<!-- Place a screenshot here: docs/images/sensor_attributes.png -->
![Sensor Attributes](docs/images/sensor_attributes.png)

---

## Configuration Options

Access via **Settings > Devices & Services > BatteryBrain > Configure**:

| Option | Default | Description |
|---|---|---|
| Scan for `battery_level` attributes | Off | Also monitor entities that report battery level as an attribute instead of a dedicated sensor |
| Treat binary low-battery as critical | Off | Escalate binary battery sensors directly to critical instead of warning |
| Exclude entities | — | Select specific entities to exclude from monitoring |
| Developer Mode | Off | Enables debug logging and developer tools (see below) |

---

## Battery Archetypes

BatteryBrain classifies each battery into one of 7 archetypes based on its behavior pattern. Each archetype uses different thresholds for health status — because a rechargeable at 15% means something very different than a linear-drain sensor at 15%.

| Archetype | Typical Devices | How It's Detected |
|---|---|---|
| **Linear** | Zigbee door/window sensors, motion sensors | Steady, roughly monotonic drain over time |
| **Plateau-Cliff** | Coin cell devices (CR2032) | Stays near 100% for a long time, then drops sharply |
| **Rechargeable** | Wall panels, phones, tablets | Regular charge/discharge cycles detected |
| **Low-Stable** | Sensors reporting 1% for months | Persistently low values with minimal variation |
| **Voltage** | Sensors reporting in V/mV instead of % | Detected by unit or value range (0.3 V – 20 V) |
| **Binary** | Simple low/normal battery indicators | Binary sensor with `device_class: battery` |
| **Unknown** | New batteries, insufficient data | Fallback until 7+ days of data are available |

<!-- TODO: Diagram or illustration showing the 7 archetypes with example drain curves -->
<!-- Place an image here: docs/images/archetypes.png -->
![Battery Archetypes](docs/images/archetypes.png)

---

## Dashboard Example

You can use the summary sensors to build a battery overview card. Here's a simple example using the [auto-entities](https://github.com/thomasloven/lovelace-auto-entities) card:

```yaml
type: entities
title: Battery Health
entities:
  - entity: sensor.battery_brain_batteries_critical
    name: Critical
    icon: mdi:battery-alert
  - entity: sensor.battery_brain_batteries_warning
    name: Warning
    icon: mdi:battery-low
  - entity: sensor.battery_brain_batteries_normal
    name: Normal
    icon: mdi:battery
  - entity: sensor.battery_brain_all_batteries
    name: Total Monitored
    icon: mdi:battery-heart
```

For a detailed per-battery view, you can use a Markdown card that reads the attributes from `sensor.battery_brain_all_batteries`.

---

## Troubleshooting

### Common Issues

<details>
<summary><strong>Some batteries are not discovered</strong></summary>

BatteryBrain discovers batteries in three ways:
- Sensors with `device_class: battery`
- Sensors with `device_class: voltage` in the 0.3 V – 20 V range
- Binary sensors with `device_class: battery`

If a battery is missing:
1. Check that the entity has the correct `device_class` set
2. Enable **"Scan for battery_level attributes"** in the integration options — some integrations report battery level as an attribute rather than a dedicated sensor
3. Make sure the entity is not in the **excluded entities** list
4. Wait for the next scan cycle (every 5 minutes)

</details>

<details>
<summary><strong>A battery is classified incorrectly</strong></summary>

Classification improves over time as more data becomes available. Confidence levels:
- **default** — less than 7 days of data, using fallback thresholds
- **low** — 7–14 days
- **medium** — 14–30 days
- **high** — 30+ days of data

If a battery is still misclassified after 30+ days, please [report it as an issue](https://github.com/larsbaum/battery_brain/issues) (see *Reporting Issues* below).

</details>

<details>
<summary><strong>A battery shows as "critical" but is still working fine</strong></summary>

This can happen when:
- The battery reports very low percentages but is still functional (common with some Zigbee devices). BatteryBrain should eventually classify this as `low_stable` and stop alerting.
- The battery has stopped sending updates and is marked as `stale`. Check if the device is still online.

If the issue persists, please [report it](https://github.com/larsbaum/battery_brain/issues).

</details>

<details>
<summary><strong>No batteries found after installation</strong></summary>

BatteryBrain runs a second discovery pass after Home Assistant is fully started, because some integrations (Mobile App, Zigbee2MQTT, etc.) load after BatteryBrain. If batteries are still missing after a few minutes, try restarting Home Assistant once more.

</details>

---

### Reporting Issues

If you encounter a problem, please [open an issue on GitHub](https://github.com/larsbaum/battery_brain/issues). To help us diagnose the problem, include:

1. **What battery is affected** — the entity ID (e.g. `sensor.kitchen_motion_battery`) and what kind of device it is
2. **What you expected** vs. **what happened** (e.g. "classified as `rechargeable` but it's a CR2032 coin cell")
3. **The log file** — BatteryBrain writes a daily log file at:
   ```
   config/battery_brain/logs/YYYY-MM-DD_batterybrain_logging.jsonl
   ```
   Attach the log file from the day the issue occurred (or the last few days). The log contains classification events and state changes that are essential for debugging.
4. **A screenshot** of the battery's history graph from Home Assistant (the entity's History tab) — this helps us understand the drain pattern

> **Privacy:** The log files only contain battery entity IDs, values, and classification data. No personal information is logged.

---

### Developer Mode

For advanced debugging, you can enable **Developer Mode** in the integration options. This provides:

- **Debug log file** at `config/battery_brain_debug.jsonl` — verbose logging with full classification details
- **Test Mode switch** — for development only, accelerates time by 200x (destroys real sensor data — do not use in production!)
- **Reclassify button** — forces immediate reclassification of all batteries

---

## How It Works (Technical Details)

<details>
<summary><strong>Discovery</strong></summary>

Every 5 minutes, BatteryBrain scans all entities for:
1. `sensor` entities with `device_class: battery`
2. `sensor` entities with `device_class: voltage` and values between 0.3 V – 20 V (filters out mains voltage sensors)
3. `binary_sensor` entities with `device_class: battery`
4. Optionally: any entity with a `battery_level` attribute

</details>

<details>
<summary><strong>History & Storage</strong></summary>

- On first discovery, imports up to **365 days** of history from the HA recorder (Long-Term Statistics first, raw states as fallback)
- Stores the last **30 days** of raw data points (hourly resolution)
- Aggregates older data into **daily summaries** (up to 365 days)
- All data is stored locally in `.storage/battery_brain` — independent of the HA recorder

</details>

<details>
<summary><strong>Classification</strong></summary>

Batteries are classified after 7+ days of data. The classification algorithm checks archetypes in this order (first match wins):

1. **Binary** — is it a binary sensor?
2. **Voltage** — does it report in volts?
3. **Rechargeable** — are there gradual charge/discharge cycles?
4. **Low-Stable** — is it stuck at a low value with minimal variation?
5. **Plateau-Cliff** — does it stay near max and then drop sharply?
6. **Linear** — is it steadily declining?
7. **Unknown** — fallback

Reclassification runs automatically every hour.

</details>

<details>
<summary><strong>Status Derivation</strong></summary>

Each archetype has its own thresholds:

| Archetype | Warning | Critical |
|---|---|---|
| Linear | &le; 20% | &le; 10% |
| Plateau-Cliff | &lt; 95% of plateau | &lt; 70% of plateau |
| Rechargeable | &le; 15% | &le; 5% |
| Low-Stable | Deviation from stable floor | Large deviation from floor |
| Voltage | &le; 25% of range | &le; 10% of range |
| Binary | Low signal | Low for 3+ days |
| Unknown | &le; 20% | &le; 10% |

</details>

---

## Requirements

- **Home Assistant** 2024.6 or newer
- **HACS** (for easy installation — manual install also works)
- The **Recorder** integration must be enabled (it is by default)

---

## License

[MIT](LICENSE)

---

<p align="center">
  <sub>Made with battery-powered determination.</sub>
</p>
