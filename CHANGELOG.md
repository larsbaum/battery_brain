# Changelog

Alle nennenswerten Änderungen an BatteryBrain werden in dieser Datei
festgehalten.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und das Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

Die Versionsnummer hier muss immer mit `custom_components/battery_brain/manifest.json`
und dem zugehörigen Git-Tag übereinstimmen (siehe SPEC.md §11).

## [Unreleased]

### Changed
- Aufräumarbeiten: `manifest.json`-Version an den aktuellen Release-Stand
  angeglichen, `CHANGELOG.md` eingeführt, SPEC.md um einen verbindlichen
  Pflege-/Release-Prozess ergänzt. Keine funktionalen Änderungen.

## [0.1.4] - 2026-07-09

### Changed
- `plateau_cliff`: NORMAL-Schwelle von 0.90 beibehalten (aus 0.1.3), zusätzliche
  Status-Rausch-Glättung ergänzt.

### Fixed
- **Voltage-Sensoren mit winzigem Wertebereich** (z.B. 12 mV Quantisierungs-
  rauschen) wurden dauerhaft als CRITICAL gemeldet. Der Range-Guard skaliert
  jetzt relativ zur Spannung (`max(VOLTAGE_MIN_RANGE_ABS=0.01 V,
  VOLTAGE_MIN_RANGE_RATIO=3 % · vmax)`) → NORMAL bei fehlendem Signal.
- **Rechargeable-Fehlklassifikation** bei periodischen Umgebungsartefakten
  (z.B. tägliche Temperaturschwankungen von Außensensoren). Neues
  Peak-Ratio-Gate (`RECHARGE_MIN_PEAK_RATIO=0.75`) mit verzögerter Bestätigung:
  ein Ladezyklus zählt nur, wenn der Wiederanstieg nah an das historische
  Maximum kommt.
- **Status-Flattern** zwischen NORMAL/WARNING/CRITICAL bei Sensoren mit
  legitimem, aber kurzfristigem Rauschen. Neuer Helper
  `_representative_recent_value()` (75. Perzentil über ein 36 h-Fenster,
  `NOISE_SMOOTHING_*`) statt reinem Momentanwert-Vergleich für
  `low_stable`/`unknown_default`.

## [0.1.3] - 2026-06-28

### Fixed
- **`plateau_cliff` löste Warnung bei 92 %** (gesunder Wert) aus. NORMAL-Schwelle
  von 0.95 auf 0.90 gesenkt — 5 % Toleranz war zu empfindlich für natürliche
  Alterung und Messrauschen.

## [0.1.2] - 2026-05-28

### Fixed
- **Stale-Recovery** (True→False) wurde nie geloggt. Das `stale`-Flag wird jetzt
  vom bestehenden Objekt übertragen, sodass `_apply_stale_overlay` Übergänge
  zurück in den aktiven Zustand korrekt erkennt und als `stale_change`-Event
  protokolliert.
- **Summary-Sensoren zeigten 0** während des HA-Starts. Neues
  `startup_complete`-Flag im Coordinator: die Sensoren melden sich als
  `unavailable`, bis der Post-Start-Refresh abgeschlossen ist, statt
  irreführende 0-Werte zu publizieren.

## [0.1.1] - 2026-05-25

### Added
- **Ganze Integrationen ausschließen** (`OPT_EXCLUDE_INTEGRATIONS`): neues Feld
  im Options-Flow. Der Coordinator löst Integrations-Excludes über die
  Entity-Registry auf und mergt sie ins bestehende Exclude-Set — schließt
  damit alle Entities einer Integration aus (battery, voltage, attribut-basiert).

## [0.1.0] - 2026-05-25

### Added
- Erste Beta-Version. Home-Assistant-Custom-Integration (HACS-kompatibel), die
  alle Batterie-Sensoren entdeckt, ihr Entladeverhalten in 7 Archetypen
  klassifiziert und einen Gesundheits-Status (Normal/Warning/Critical) ableitet.
- Auto-Discovery (`sensor`/`binary_sensor` mit `device_class: battery`,
  `voltage`-Sensoren 0.3–20 V, optional `battery_level`-Attribut).
- Recorder-Seeding bis 365 Tage Historie beim ersten Sehen einer Batterie.
- Persistenter History-Store (`.storage/battery_brain`) mit Roh-/Tagesaggregaten.
- Stale-Detection, Confidence-Level, vier Aggregat-Summary-Sensoren.
- Developer-Mode mit Test-Mode-Switch (200× Zeitraffer), Reclassify-Button und
  Debug-Logging; Always-on Production-Logging (JSONL, 30 Tage Retention).
- Einzelne Entities ausschließen (`OPT_EXCLUDE_ENTITIES`).

[Unreleased]: https://github.com/larsbaum/battery_brain/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/larsbaum/battery_brain/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/larsbaum/battery_brain/compare/v0.1.2_BETA...v0.1.3
[0.1.2]: https://github.com/larsbaum/battery_brain/compare/v0.1.1_BETA...v0.1.2_BETA
[0.1.1]: https://github.com/larsbaum/battery_brain/compare/v0.1.0_BETA...v0.1.1_BETA
[0.1.0]: https://github.com/larsbaum/battery_brain/releases/tag/v0.1.0_BETA
