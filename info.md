## BatteryBrain

Intelligent battery health analysis for Home Assistant.

BatteryBrain automatically discovers all battery entities, learns their behavior patterns from historical data, and derives a health status (normal / warning / critical) for each battery.

### Features

- **Zero-config auto-discovery** of all battery entities (sensor and binary_sensor with `device_class: battery`)
- **Behavioral classification** into archetypes: linear, plateau-cliff, low-stable, voltage, binary, rechargeable
- **Per-battery health status** with confidence level and staleness detection
- **Summary sensors** for quick dashboards and automations
- **Own history storage** independent of the recorder, with intelligent aggregation

### Sensors

| Sensor | Description |
|---|---|
| `sensor.batteries_normal` | Count of batteries in normal state |
| `sensor.batteries_warning` | Count of batteries in warning state |
| `sensor.batteries_critical` | Count of batteries in critical state |
| `sensor.all_batteries` | Total count with per-battery detail attributes |
