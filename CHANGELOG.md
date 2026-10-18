# Changelog

Alle nennenswerten Änderungen an BatteryBrain werden in dieser Datei
festgehalten.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
und das Projekt folgt [Semantic Versioning](https://semver.org/lang/de/).

Die Versionsnummer hier muss immer mit `custom_components/battery_brain/manifest.json`
und dem zugehörigen Git-Tag übereinstimmen.

## [Unreleased]

## [1.0.0] - 2026-10-18

Erste stabile Version. Das Update braucht keinen Eingriff: Einstellungen,
Entities (inkl. Entity-IDs) und die gesammelte Historie bleiben erhalten.

### Added
- **Zwei Dashboard-Karten, direkt mit der Integration ausgeliefert.** Keine
  HACS-Frontend-Karten und keine Lovelace-Ressource nötig, alles im
  visuellen Editor einstellbar (kein YAML), Sprache Deutsch/Englisch,
  HA-Standardoptik in hellem und dunklem Theme:
  - **BatteryBrain: Summary**: kompakte Kachel mit Anzahl, Zählern je
    Status, Badge für kritische Batterien und Farbe nach schlimmstem
    Status; optional mit Liste der betroffenen Batterien. Tap-/Halte-
    Aktion frei wählbar.
  - **BatteryBrain: Battery list**: alle Batterien nach Kritisch / Warnung /
    OK gruppiert (einklappbar), als Liste oder Kacheln (1–4 Spalten, auf
    schmalen Bildschirmen eine). Frei wählbar, welche Attribute angezeigt
    werden (alle 9 möglich), Sortierung, Filter nach Batterietyp und nicht
    erreichbaren Batterien.

  Die Karten finden den Sensor selbst, auch wenn er umbenannt wurde. Bei
  nicht erreichbaren Batterien zeigen sie statt veraltetem Wert und
  Prognose den Hinweis „nicht erreichbar“.
- **Restlaufzeit für jede Batterie, ohne Ausnahme.** Wo der eigene Verlauf
  keinen Trend hergibt, wird stufenweise geschätzt. Das neue Attribut
  `remaining_source` zeigt die Herkunft:
  - `measured`: eigener Trend
  - `history`: frühere Batterien des Geräts, übliche Entladerate zwischen
    zwei Ladungen, frühere Dauer des Low-Signals
  - `similar`: gleiche Gerätemodelle im Haushalt
  - `typical`: feste typische Lebensdauer je Batterietyp minus Alter der
    Batterie
  - `stale`: letzter bekannter Wert, Batterie nicht erreichbar

  Damit bekommen jetzt auch Knopfzellen auf dem Plateau, bei 1 % hängende
  Batterien, Binärsensoren, Akkus beim Laden und dauerhaft geladene Geräte
  (Tablet per Automation, Saugroboter an der Station: „Laufzeit ohne
  Laden“) einen Wert. Nur gemessene Schätzungen beeinflussen den Status.
  Begrenzung auf 100 Jahre, damit `estimated_empty` immer gesetzt ist.
- Batteriestände als Text (`low`, `medium`, `high`, …) werden als Prozent
  gewertet (15/50/90 %, `critical` 5, `empty` 0, `full` 100).
- **Restlaufzeit für mehr Batterietypen und deutlich genauer.** Messwerte
  werden zwischen den Meldungen interpoliert und auf ein gleichmäßiges
  Zeitraster gebracht. Es spielt also keine Rolle mehr, wie oft ein Gerät
  meldet, und Zeit ohne Änderung zählt als „kein Verbrauch“. Neu bzw.
  verbessert:
  - `linear`: Jüngere Tage zählen stärker. Beschleunigt sich die Entladung
    zum Lebensende hin deutlich, wird der jüngste Trend verwendet
    (simulierte Alkaline-Kurve 15 Tage vor Ende: 3 % statt 170 % Fehler).
  - `rechargeable`: aktuelle Entladerate gemischt mit der typischen Rate
    früherer Entladephasen. Dadurch gibt es direkt nach dem Abstecken eine
    Schätzung, und Zeit am Ladegerät verfälscht die Rate nicht mehr
    (simuliertes Handy: ≤ 5 % statt bis zu 400 % Fehler).
  - `voltage`: Schätzung jetzt auch auf der ersten Batterie, über eine
    typische Abschaltspannung je Batterietyp (z. B. 2,3 V für 3-V-Zellen,
    3,3 V für Li-Ion, 11,8 V für 12-V-Blei). Sobald ein Wechsel beobachtet
    wurde, gilt die Spannung, bei der die vorherige Batterie endete.
  - `plateau_cliff`: Nach dem Verlassen des Plateaus wird der Trend seitdem
    hochgerechnet. Batteriewechsel werden dauerhaft gespeichert (auch über
    die 365-Tage-Historie hinaus) für die Lebensdauer-Schätzung.
  - `unknown_default`: Schätzung bei mindestens 7 Tagen klar fallendem Trend.
- **Bewertungsmodus „Nur bei niedrigem Stand“** (opt-in, Issue #3):
  Eine Batterie wird erst ab einem selbst gewählten Stand zur Warnung
  (Standard 10 %, einstellbar 5–50 %) und ab der Hälfte davon kritisch.
  Prognosen lösen dann keine Warnung aus, Restlaufzeit und Co. bleiben aber
  in den Attributen sichtbar; der Wechsel zurück zum intelligenten Modus
  wirkt sofort. Unverändert in beiden Modi: nicht erreichbare Batterien
  (kritisch), Spannungs- und Ein/Aus-Batteriesensoren. Textstände `low` /
  `critical` / `empty` zählen in diesem Modus wie ein Niedrig-Signal.
  Standard bleibt der intelligente Modus.
- **Diagnose-Download** (Einstellungen → Geräte & Dienste → BatteryBrain →
  ⋮ → Diagnose herunterladen) mit Einstellungen, aktueller Bewertung und
  gespeicherter Historie aller Batterien.
- **Deutsche Übersetzung** der Oberfläche.
- Option **„Spannungssensoren einbeziehen“** (Standard: an), um z. B. die
  3,3-V-Versorgung eines ESP-Boards auszublenden.
- Erkennung von Spannungssensoren in **mV**.

### Changed
- **Konfiguration übersichtlicher:** Die Einrichtung braucht keine Eingaben
  mehr. Die Optionen sind in die Bereiche Erkennung, Ausschlüsse, Bewertung
  und Erweitert (eingeklappt, Developer-Mode) gegliedert, mit verständlicheren
  Hilfetexten. Ausgeschlossene Batterien werden als „Name (entity_id)“
  angezeigt, Integrationen mit ihrem echten Namen. Die gespeicherten
  Options-Schlüssel sind unverändert.
- **Spannungsstatus** wird zwischen Voll- und Leer-Spannung der Batterie
  bewertet statt relativ zu Min/Max der Historie.
- Ein Wechsel des Archetyps wird erst nach **drei aufeinanderfolgenden
  gleichen Klassifikationen** übernommen (Ausnahmen: Erstklassifikation,
  Wechsel weg von `unknown_default`, Reclassify-Button). Das verhindert
  Status-Flattern.
- Spannungssensoren werden anhand der Einheit (V/mV) sofort als `voltage`
  eingestuft, ohne 7 Tage Historie abzuwarten.
- Die Batterie-Details der Summary-Sensoren werden nicht mehr in die
  Recorder-Datenbank geschrieben (verhindert Datenbank-Wachstum und die
  HA-Warnung „> 16 KB“). Die Live-Attribute sind unverändert.
- Production-Log: Snapshot aller Batterien stündlich statt alle 5 Minuten,
  `state_change` nur noch bei echter Wert- oder Statusänderung. Das Format
  ist unverändert.
- Recorder-Import beim ersten Start gebündelt (eine Abfrage für alle neuen
  Batterien statt zwei pro Batterie).
- Entity-IDs der BatteryBrain-Sensoren sind sprachunabhängig fest
  (`sensor.battery_brain_…`), auch bei Neuinstallation auf Deutsch.
- BatteryBrain lässt sich nur einmal einrichten (`single_config_entry`);
  ein zweiter Versuch wird schon vor dem Dialog abgelehnt.
- Interne Aufräumarbeiten: gemeinsame Auswertung für Update-Zyklus und
  Live-Ereignisse, ein gemeinsames Event-Logging, gemeinsame Entity-Basis,
  toter Code entfernt.
- **README neu gegliedert:** oben Überblick, Vergleich mit festen
  Schwellwert-Automationen und Funktionen; technische Details weiter unten
  in aufklappbaren Abschnitten.

### Fixed
- Der **5-Minuten-Zyklus lief bei häufig meldenden Batterien praktisch nie**:
  Jedes Batterie-Ereignis setzte den Timer zurück. Dadurch fehlten Discovery,
  Reklassifikation, Stale-Erkennung und Aggregation.
- **Optionen ließen sich oft nicht ohne Neustart übernehmen** („Entladen
  fehlgeschlagen“): Der State-Listener wurde beim Entladen doppelt abgemeldet.
- Batterien aus dem **`battery_level`-Attribut** speicherten bei
  Live-Ereignissen und beim Recorder-Import den Zustand der Entity (z. B. eine
  Temperatur) als Batteriewert. Die betroffene Historie wird beim Update
  einmalig zurückgesetzt.
- **`plateau_cliff` blieb nach einem Batteriewechsel CRITICAL**, potenziell
  monatelang.
- **Nach einem Batteriewechsel wurde eine leer gelaufene Batterie
  `low_stable`**: Die Prüfung sah die monatelangen niedrigen Werte der alten
  Batterie, die neue galt als „dauerhaft niedrig“ und bekam keine gemessene
  Restlaufzeit. Jetzt zählt nur die aktuelle Batterie. Ein Wechsel gilt
  sofort ab ≥ 90 %, sonst nach 24 Stunden; Sonnenspitzen bei
  Solar-Außensensoren zählen nicht als Wechsel.
- **`plateau_cliff` warnte, sobald eine Batterie ihr Plateau verließ**
  (unter 90 % des Plateaus), auch wenn sie noch Monate hält (Issue #3).
  Jetzt entscheidet unterhalb des Plateaus die gemessene Restlaufzeit:
  WARNING unter 21 Tagen, CRITICAL unter 5 Tagen, dazu wie bei `linear`
  ≤ 20 % WARNING und ≤ 10 % CRITICAL. In Simulationen echter
  Knopfzellen-Klippen kommt die Warnung 7–12 Tage, CRITICAL 2–4 Tage vor
  leer.
- **Spannungsbatterien wurden auf der ersten Batterie CRITICAL**, sobald die
  Spannung leicht sank, und neue Spannungssensoren in den ersten 7 Tagen.
- %-Batterien, die die gesamte Historie bei 1–5 % standen, wurden als
  `voltage` eingestuft.
- **Langsam entladende Batterien im unteren Bereich wurden als `low_stable`
  eingestuft** und bekamen deshalb nie eine Restlaufzeit und keine Warnung
  (z. B. ein Türsensor, der seit dem Wechsel gleichmäßig von 64 % auf 26 %
  fiel und dabei zwischen 26/27/28 % pendelte, oder ein leicht schwankender
  Sensor, der bei 11 % „normal“ war). `low_stable` gilt jetzt nur noch, wenn
  die aktuelle Batterie seit mindestens 30 Tagen beobachtet wird und in
  diesen 30 Tagen nicht mehr erkennbar gefallen ist. Der Wechsel zu
  `linear` greift nach dem Update innerhalb von etwa 3 Stunden.
- Nicht mehr verfügbare Spannungssensoren verschwanden aus der Überwachung,
  statt als stale/critical gemeldet zu werden.
- Batterien mit gleichem Namen überschrieben sich in den Sensor-Attributen.
  Bei Namensgleichheit lautet der Schlüssel jetzt „Name (entity_id)“.
- Eine stale Batterie sprang bei einem Ereignis kurz auf NORMAL; eine wieder
  erreichbare blieb bis zum nächsten Zyklus stale.
- Reine Attribut-Änderungen erzeugten doppelte Messpunkte.
- Beim Neuladen der Integration gingen bis zu 5 Minuten Historie verloren.
- Akku-Status: Ein graduelles Laden wurde für die Herabstufung CRITICAL →
  WARNING nicht erkannt.
- Ladevorgänge (z. B. Tablet, Saugroboter) und sonnige Tage bei
  Solar-Sensoren wurden als Batteriewechsel gespeichert. Ein Wechsel zählt
  jetzt nur, wenn das neue Niveau mindestens 50 % erreicht und 24 h hält,
  und nur bei `linear`, `plateau_cliff` und `low_stable`. Bei Binärsensoren
  zählt ein Low-Signal, das nach mindestens 24 h verschwindet und
  verschwunden bleibt. Bereits gespeicherte falsche Einträge werden
  automatisch bereinigt.
- Batterien mit Text-Wert wurden nach 24 h fälschlich als stale (CRITICAL)
  gemeldet, weil sie nicht als „lebend“ galten.
- Einzelne Ausreißer-Messwerte (z. B. kurz 0 %) wurden als Batteriewechsel
  gewertet.
- Tageszusammenfassungen von Batterien ohne neue Messwerte wurden nie
  gelöscht. Einträge ohne Daten, die seit über 365 Tagen nicht mehr gesehen
  wurden, werden jetzt entfernt.
- Der Options-Dialog stürzte ab, wenn die Integration nicht geladen war.
- README: Stale-Erkennung, Voltage-Erkennung, `battery_level`-Domains,
  Status- und Restlaufzeit-Tabellen und Optionen stimmen jetzt mit dem
  tatsächlichen Verhalten überein.
- **Die gesammelte Historie wurde im laufenden Betrieb nie gespeichert**,
  nur beim Neustart oder Neuladen. Jeder neue Batteriewert verschob das
  geplante Speichern erneut um 5 Minuten. Nach einem Absturz oder
  Stromausfall fehlte deshalb alles seit dem letzten Neustart. Jetzt wird
  spätestens 15 Minuten nach der ersten Änderung gespeichert; importierte
  Mittelwerte werden auf 3 Nachkommastellen gerundet (kleinere Datei).
- **Handys, Tablets, Uhren und Laptops wurden aus der importierten
  Historie fast nie als Akku erkannt** und standen dadurch teils auf
  CRITICAL (`linear` mit „leer in unter 2 Tagen“, schon bei 30–40 %), teils
  ohne Akku-Regeln auf `unknown_default`. Importierte Werte sind
  Stundenmittel; schnelles Laden (40–60 % pro Stunde) sah dort wie ein
  Batteriewechsel aus. Schnelle Ladungen in Stundenwerten zählen jetzt mit.
  Ein per Steckdose zwischen 40 und 60 % gehaltenes Wandtablet gilt nicht
  mehr als `linear`.
- **Archetypen und Status änderten sich Stunden nach der Installation**: Die
  erste Einstufung lief auf einem Jahr Stundenwerten, alle späteren auf
  Tagesmitteln. Importierte Historie wird jetzt sofort zusammengefasst.
- **Ein einzelner Ausreißer nach unten löste sofort CRITICAL aus**, z. B. ein
  Z-Wave-Thermostat bei 97 %, das einmal 0 % meldet (bis zu seiner nächsten
  Meldung, oft eine Stunde). Ein Abfall um 30 Punkte oder mehr in einem
  Schritt (bei Spannungen 30 %) zählt jetzt erst, wenn ein weiterer Wert ihn
  bestätigt oder 2 Stunden vergangen sind.
- **Verwaiste Entities blieben dauerhaft „nicht erreichbar“ (CRITICAL)**:
  Entities, die nach dem Entfernen eines Geräts, einer YAML-Definition oder
  einer Integration in der Entity-Registry zurückbleiben, zeigt Home
  Assistant dauerhaft als „nicht verfügbar“. Sie werden jetzt nach 15
  Minuten ignoriert. Batterien einer Integration, die nur gerade nicht
  startet, bleiben überwacht und werden wie bisher als nicht erreichbar
  gemeldet.
- **Eine 12-V-Autobatterie war bei 12,7 V CRITICAL**: Jedes Laden durch die
  Lichtmaschine galt als Batteriewechsel und die Ruhespannung davor als
  „leer“. Regelmäßig nachgeladene Spannungsquellen nutzen jetzt die typische
  Leerspannung.
- **Beim Entfernen der Integration blieben Historie und Logs liegen.** Wer
  BatteryBrain neu hinzufügte, um frisch anzufangen, bekam die alte
  Historie zurück, und der Import aus dem Recorder wurde übersprungen.
  Entfernen löscht jetzt `.storage/battery_brain`, `battery_brain/logs/`
  und das Debug-Log.
- **Die Diagnose-Datei war bei vielen Batterien zu groß für einen
  GitHub-Anhang** (324 Batterien: 26,5 MB, GitHub erlaubt 25 MB). Die
  Messpunkte jeder Batterie stehen jetzt als kompakte Liste in einer Zeile
  (ca. 7 MB).
- Ein Batteriewert, der genau während des 5-Minuten-Durchlaufs gemeldet
  wurde, konnte bis zum nächsten Durchlauf wieder durch den älteren Wert
  ersetzt werden. Außerdem konnten dabei einzelne Log-Einträge verloren
  gehen.
- Die Log-Dateien in `config/battery_brain/logs` wurden bei vielen
  Batterien sehr groß (326 Batterien: etwa 7 MB pro Tag, 210 MB bei 30 Tagen
  Aufbewahrung, in jedem HA-Backup enthalten). Die stündliche Prüfung jeder
  Batterie wird nur noch protokolliert, wenn sich dabei etwas ändert. Der
  Recorder-Import schreibt eine Zeile statt einer pro Batterie (vorher
  warnte Home Assistant „logging too frequently“).
- Eine frische Batterie bekam über baugleiche Geräte (`similar`) teils viel
  zu kurze Restlaufzeiten (Fernbedienung bei 100 %: 48 statt rund 600
  Tage), wenn ein baugleiches Gerät gerade am Ende seiner Batterie schnell
  abfiel. Jetzt zählt die durchschnittliche Entladung seit dem Einsetzen.
- Das Gerät hieß „Battery Brain“ statt „BatteryBrain“; die Sensoren heißen
  jetzt z. B. „BatteryBrain Alle Batterien“. Die Entity-IDs bleiben gleich.
- Nach einem Batteriewechsel zeigten exakt gleichbleibende Werte manchmal
  „gemessen: 100 Jahre“ statt einer Schätzung über baugleiche Geräte oder
  typische Lebensdauern (Rechenrauschen ergab eine winzige Steigung).
- Ein einzelner Ausreißer (z. B. kurz 0 %) wurde bei Batterien ohne
  erkennbares Muster als Ladevorgang gewertet und änderte die
  Restlaufzeit-Schätzung.

### Removed
- README: die YAML-Dashboard-Beispiele (Entities-Übersicht und
  auto-entities/Mushroom-Dashboard). Die mitgelieferten Karten ersetzen
  sie, die README zeigt jetzt Screenshots der Karten.

## [0.2.0] - 2026-10-05

### Added
- Restlaufzeit-Schätzung für `rechargeable` (Regression über die aktuelle
  Entladephase seit dem letzten Laden, bis 0 %; nur Anzeige, kein Einfluss auf
  den Status) ([#2](https://github.com/larsbaum/battery_brain/issues/2)).
- Restlaufzeit-Schätzung für `voltage` (Trend bis zur Spannung, bei der die
  vorherige Batterie leer war) und `plateau_cliff` (Median-Lebensdauer früherer
  Batterien minus Alter der aktuellen).
- Neue Attribute `remaining_days` und `estimated_empty` pro Batterie in allen
  Summary-Sensoren; `remaining_days` zusätzlich im `update`-Event des
  Production- und Debug-Logs.

### Changed
- Aufräumarbeiten: `manifest.json`-Version an den aktuellen Release-Stand
  angeglichen, `CHANGELOG.md` eingeführt, SPEC.md um einen verbindlichen
  Pflege-/Release-Prozess ergänzt. Keine funktionalen Änderungen.
- `linear`: Die Restlaufzeit-Regression läuft jetzt über die Tagesmittel der
  gesamten Lebensdauer der aktuellen Batterie (seit dem letzten Sprung > 20pp)
  statt über ein 14-Tage-Fenster. Bei langsam entladenden Sensoren mit
  1-%-Auflösung war die 14-Tage-Steigung reines Rauschen. Frisch getauschte
  Batterien (< 7 Tage) nutzen weiter die Rohpunkte der letzten 14 Tage.
  Die Status-Eskalation (< 7 bzw. < 2 Tage) nutzt dieselbe Schätzung.

### Fixed
- Die im README beworbene Restlaufzeit-Schätzung wurde zwar berechnet (für
  `linear`), aber nirgends angezeigt: Das Ergebnis floss nur in die
  Status-Ableitung ein und wurde dann verworfen.
- README: Warnschwelle für `plateau_cliff` korrigiert (< 90 % statt < 95 %),
  fehlende Option „Exclude integrations“ ergänzt, Speicherauflösung der
  Rohpunkte korrigiert (bei Wertänderung statt stündlich).
- Mindestversion von Home Assistant in `hacs.json` und README von 2024.6 auf
  **2025.8** korrigiert. Die Integration nutzt `OptionsFlowWithReload` (seit
  HA 2025.8) und `AddConfigEntryEntitiesCallback` (seit HA 2025.3) und ließ
  sich auf älteren Versionen gar nicht laden.

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

[Unreleased]: https://github.com/larsbaum/battery_brain/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/larsbaum/battery_brain/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/larsbaum/battery_brain/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/larsbaum/battery_brain/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/larsbaum/battery_brain/compare/v0.1.2_BETA...v0.1.3
[0.1.2]: https://github.com/larsbaum/battery_brain/compare/v0.1.1_BETA...v0.1.2_BETA
[0.1.1]: https://github.com/larsbaum/battery_brain/compare/v0.1.0_BETA...v0.1.1_BETA
[0.1.0]: https://github.com/larsbaum/battery_brain/releases/tag/v0.1.0_BETA
