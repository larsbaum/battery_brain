/*
 * BatteryBrain dashboard cards.
 *
 * Served by the integration itself (see frontend.py), so there is nothing to
 * install. Plain web components without a build step: no Lit, no third-party
 * cards. Everything is read from the attributes of the "all batteries"
 * sensor, which carry one detail dict per battery (see sensor.py).
 *
 *   custom:battery-brain-summary-card  compact status tile
 *   custom:battery-brain-card          full list / grid grouped by status
 */

const DOMAIN = "battery_brain";
const FALLBACK_ENTITY = "sensor.battery_brain_all_batteries";

const STATUSES = ["critical", "warning", "normal"];
const STATUS_RANK = { critical: 0, warning: 1, normal: 2 };
const STATUS_COLOR = {
  critical: "var(--error-color, #db4437)",
  warning: "var(--warning-color, #ffa600)",
  normal: "var(--success-color, #43a047)",
};
const STATUS_ICON = {
  critical: "mdi:battery-alert-variant",
  warning: "mdi:battery-alert",
  normal: "mdi:battery-check",
};
const CATEGORIES = [
  "linear",
  "plateau_cliff",
  "low_stable",
  "voltage",
  "binary",
  "rechargeable",
  "unknown_default",
];
const CATEGORY_ICON = {
  linear: "mdi:trending-down",
  plateau_cliff: "mdi:chart-bell-curve-cumulative",
  low_stable: "mdi:battery-low",
  voltage: "mdi:lightning-bolt",
  binary: "mdi:battery-outline",
  rechargeable: "mdi:battery-sync",
  unknown_default: "mdi:help-circle-outline",
};
// Every attribute a battery carries, in the order they are shown.
const FIELDS = [
  "last_value",
  "status",
  "category",
  "confidence",
  "stale",
  "remaining_days",
  "estimated_empty",
  "remaining_source",
  "source_entity",
];

// ---------------------------------------------------------------------------
// Translations
// ---------------------------------------------------------------------------

const STRINGS = {
  en: {
    batteries: { one: "{n} battery", other: "{n} batteries" },
    title: "Batteries",
    count_critical: "{n} critical",
    count_warning: "{n} warning",
    count_normal: "{n} OK",
    all_ok: "All OK",
    none: "No batteries",
    not_found: "BatteryBrain sensor not found. Is the integration set up?",
    wrong_entity: "{e} is not a BatteryBrain sensor.",
    starting: "BatteryBrain is starting …",
    more: "+{n} more",
    status: { critical: "Critical", warning: "Warning", normal: "OK" },
    category: {
      linear: "Linear",
      plateau_cliff: "Plateau / cliff",
      low_stable: "Low & stable",
      voltage: "Voltage",
      binary: "Low signal",
      rechargeable: "Rechargeable",
      unknown_default: "Unknown",
    },
    confidence: { high: "high", medium: "medium", low: "low", default: "none yet" },
    source: {
      measured: "measured trend",
      history: "from history",
      similar: "similar devices",
      typical: "typical lifetime",
      stale: "last known value",
    },
    low: "Low",
    ok: "OK",
    stale: "unreachable",
    left: "~{v} left",
    lt_day: "< 1 day left",
    days: { one: "{n} day", other: "{n} days" },
    months: { one: "{n} month", other: "{n} months" },
    years: { one: "{n} year", other: "{n} years" },
    empty_on: "empty ≈ {d}",
    confidence_title: "Confidence: {c}",
    field: {
      last_value: "Value",
      status: "Status",
      category: "Battery type",
      confidence: "Confidence (stars)",
      stale: "Unreachable marker",
      remaining_days: "Remaining time",
      estimated_empty: "Estimated empty date",
      remaining_source: "Estimate based on",
      source_entity: "Entity ID",
    },
    editor: {
      entity: "BatteryBrain sensor",
      entity_helper: "Leave empty to detect it automatically.",
      name: "Name",
      icon: "Icon",
      title: "Title",
      sec_content: "Content",
      sec_look: "Appearance",
      sec_list: "Battery list",
      sec_filter: "Filter & sorting",
      sec_actions: "Interactions",
      show_counts: "Counters in the second line",
      hide_zero: "Hide counters that are 0",
      show_badge: "Badge with number of critical batteries",
      color_by_status: "Colour icon by worst status",
      vertical: "Vertical layout",
      tap_action: "Tap action",
      hold_action: "Hold action",
      show_list: "List affected batteries (critical & warning)",
      list_max: "Maximum entries",
      fields: "Shown details",
      group_by_status: "Group by status",
      statuses: "Shown status groups",
      hide_empty: "Hide empty groups",
      collapse_normal: "Collapse the OK group",
      layout: "Layout",
      layout_list: "List",
      layout_grid: "Tiles",
      columns: "Columns (tiles)",
      icon_mode: "Icon",
      icon_category: "By battery type",
      icon_entity: "Icon of the battery entity",
      sort: "Sort by",
      sort_status: "Status, then remaining time",
      sort_remaining: "Remaining time",
      sort_value: "Value (lowest first)",
      sort_name: "Name",
      categories: "Battery types",
      categories_helper: "Nothing selected = all types.",
      stale_filter: "Unreachable batteries",
      stale_all: "Show",
      stale_hide: "Hide",
      stale_only: "Show only these",
      max_per_group: "Maximum per group",
      max_helper: "0 = no limit.",
    },
  },
  de: {
    batteries: { one: "{n} Batterie", other: "{n} Batterien" },
    title: "Batterien",
    count_critical: "{n} kritisch",
    count_warning: "{n} Warnung",
    count_normal: "{n} OK",
    all_ok: "Alles in Ordnung",
    none: "Keine Batterien",
    not_found: "BatteryBrain-Sensor nicht gefunden. Ist die Integration eingerichtet?",
    wrong_entity: "{e} ist kein BatteryBrain-Sensor.",
    starting: "BatteryBrain startet …",
    more: "+{n} weitere",
    status: { critical: "Kritisch", warning: "Warnung", normal: "OK" },
    category: {
      linear: "Linear",
      plateau_cliff: "Plateau / Abfall",
      low_stable: "Niedrig & stabil",
      voltage: "Spannung",
      binary: "Low-Signal",
      rechargeable: "Akku",
      unknown_default: "Unbekannt",
    },
    confidence: { high: "hoch", medium: "mittel", low: "niedrig", default: "noch keine" },
    source: {
      measured: "gemessener Trend",
      history: "aus dem Verlauf",
      similar: "ähnliche Geräte",
      typical: "typische Lebensdauer",
      stale: "letzter bekannter Wert",
    },
    low: "Niedrig",
    ok: "OK",
    stale: "nicht erreichbar",
    left: "noch ~{v}",
    lt_day: "noch < 1 Tag",
    days: { one: "{n} Tag", other: "{n} Tage" },
    months: { one: "{n} Monat", other: "{n} Monate" },
    years: { one: "{n} Jahr", other: "{n} Jahre" },
    empty_on: "leer ≈ {d}",
    confidence_title: "Konfidenz: {c}",
    field: {
      last_value: "Wert",
      status: "Status",
      category: "Batterietyp",
      confidence: "Konfidenz (Sterne)",
      stale: "Hinweis „nicht erreichbar“",
      remaining_days: "Restlaufzeit",
      estimated_empty: "Voraussichtlich leer am",
      remaining_source: "Grundlage der Schätzung",
      source_entity: "Entity-ID",
    },
    editor: {
      entity: "BatteryBrain-Sensor",
      entity_helper: "Leer lassen für automatische Erkennung.",
      name: "Name",
      icon: "Icon",
      title: "Titel",
      sec_content: "Inhalt",
      sec_look: "Darstellung",
      sec_list: "Batterieliste",
      sec_filter: "Filter & Sortierung",
      sec_actions: "Interaktionen",
      show_counts: "Zähler in der zweiten Zeile",
      hide_zero: "Zähler mit 0 ausblenden",
      show_badge: "Badge mit Anzahl kritischer Batterien",
      color_by_status: "Icon nach schlimmstem Status einfärben",
      vertical: "Vertikales Layout",
      tap_action: "Aktion beim Tippen",
      hold_action: "Aktion beim Halten",
      show_list: "Betroffene Batterien auflisten (kritisch & Warnung)",
      list_max: "Maximale Anzahl",
      fields: "Angezeigte Details",
      group_by_status: "Nach Status gruppieren",
      statuses: "Angezeigte Status-Gruppen",
      hide_empty: "Leere Gruppen ausblenden",
      collapse_normal: "OK-Gruppe eingeklappt",
      layout: "Layout",
      layout_list: "Liste",
      layout_grid: "Kacheln",
      columns: "Spalten (Kacheln)",
      icon_mode: "Icon",
      icon_category: "Nach Batterietyp",
      icon_entity: "Icon der Batterie-Entity",
      sort: "Sortieren nach",
      sort_status: "Status, dann Restlaufzeit",
      sort_remaining: "Restlaufzeit",
      sort_value: "Wert (niedrigster zuerst)",
      sort_name: "Name",
      categories: "Batterietypen",
      categories_helper: "Nichts ausgewählt = alle Typen.",
      stale_filter: "Nicht erreichbare Batterien",
      stale_all: "Anzeigen",
      stale_hide: "Ausblenden",
      stale_only: "Nur diese anzeigen",
      max_per_group: "Maximal pro Gruppe",
      max_helper: "0 = unbegrenzt.",
    },
  },
};

function lang(hass) {
  const l = (hass && (hass.locale?.language || hass.language)) || "en";
  return l.split("-")[0];
}

function strings(hass) {
  return STRINGS[lang(hass)] || STRINGS.en;
}

function fmt(template, vars) {
  return template.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : ""));
}

function plural(hass, forms, n, shown = n) {
  const rule = new Intl.PluralRules(lang(hass)).select(n);
  return fmt(forms[rule] || forms.other, { n: shown });
}

function num(hass, value, digits, grouping = true) {
  return new Intl.NumberFormat(hass?.locale?.language || lang(hass), {
    maximumFractionDigits: digits,
    useGrouping: grouping,
  }).format(value);
}

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

/** The "all batteries" sensor: configured, found via the registry, or the default ID. */
function findSensor(hass, config) {
  if (config.entity) return config.entity;
  for (const entry of Object.values(hass.entities || {})) {
    if (entry.platform === DOMAIN && entry.translation_key === "all_batteries") {
      return entry.entity_id;
    }
  }
  return FALLBACK_ENTITY;
}

/** One object per battery from the sensor's attributes. */
function readBatteries(stateObj) {
  const result = [];
  for (const [name, d] of Object.entries(stateObj.attributes)) {
    if (d && typeof d === "object" && !Array.isArray(d) && d.source_entity) {
      result.push({ name, ...d });
    }
  }
  return result;
}

function countByStatus(batteries) {
  const counts = { critical: 0, warning: 0, normal: 0 };
  for (const b of batteries) if (b.status in counts) counts[b.status] += 1;
  return counts;
}

function worstStatus(counts) {
  return STATUSES.find((s) => s !== "normal" && counts[s] > 0) || "normal";
}

const SORTERS = {
  name: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
  remaining: (a, b) =>
    (a.remaining_days ?? Infinity) - (b.remaining_days ?? Infinity) ||
    SORTERS.name(a, b),
  value: (a, b) =>
    (typeof a.last_value === "number" ? a.last_value : Infinity) -
      (typeof b.last_value === "number" ? b.last_value : Infinity) ||
    SORTERS.name(a, b),
  status: (a, b) =>
    (STATUS_RANK[a.status] ?? 3) - (STATUS_RANK[b.status] ?? 3) ||
    // Unreachable ones after the readable ones of the same status: an
    // empty battery is the clearer case to act on.
    Number(a.stale) - Number(b.stale) ||
    SORTERS.remaining(a, b),
};

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function formatValue(hass, b) {
  const s = strings(hass);
  const v = b.last_value;
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "boolean") return v ? s.low : s.ok;
  if (b.category === "binary") {
    return v === 1 || v === "on" || v === "low" ? s.low : s.ok;
  }
  if (typeof v !== "number") return String(v);
  if (b.category === "voltage") {
    // The attributes carry no unit; millivolt sensors report e.g. 2997.
    const unit = hass?.states?.[b.source_entity]?.attributes?.unit_of_measurement;
    // No thousands separator: "2.989 mV" (de) reads like a fraction.
    if (String(unit).toLowerCase() === "mv") return `${num(hass, v, 0, false)} mV`;
    return `${num(hass, v, 3)} V`;
  }
  return `${num(hass, v, 1)} %`;
}

function formatDuration(hass, days) {
  const s = strings(hass);
  if (days < 1) return s.lt_day;
  let text;
  if (days < 60) {
    const n = Math.round(days);
    text = plural(hass, s.days, n);
  } else if (days < 730) {
    const n = Math.round(days / 30.44);
    text = plural(hass, s.months, n);
  } else {
    const n = Math.round((days / 365.25) * 10) / 10;
    text = plural(hass, s.years, n, num(hass, n, 1));
  }
  return fmt(s.left, { v: text });
}

function formatDate(hass, iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso));
  // Date-only strings are calendar dates, not UTC midnight.
  const date = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return new Intl.DateTimeFormat(hass?.locale?.language || lang(hass), {
    dateStyle: "medium",
  }).format(date);
}

const STARS = { high: "★★★", medium: "★★☆", low: "★☆☆", default: "☆☆☆" };

// Unreachable: no current value, and the forecast is only a stale guess.
const HIDDEN_WHEN_STALE = new Set(["last_value", "remaining_days", "estimated_empty"]);

/** HTML snippet for one attribute of a battery, or "" if there is nothing to show. */
function formatField(hass, b, field) {
  const s = strings(hass);
  if (b.stale && HIDDEN_WHEN_STALE.has(field)) return "";
  switch (field) {
    case "last_value":
      return esc(formatValue(hass, b));
    case "status":
      return esc(s.status[b.status] || b.status || "");
    case "category":
      return esc(s.category[b.category] || b.category || "");
    case "confidence": {
      const c = b.confidence || "default";
      const title = fmt(s.confidence_title, { c: s.confidence[c] || c });
      return `<span title="${esc(title)}">${STARS[c] || esc(c)}</span>`;
    }
    case "stale":
      return b.stale ? `<span class="stale">⚠ ${esc(s.stale)}</span>` : "";
    case "remaining_days":
      return typeof b.remaining_days === "number"
        ? esc(formatDuration(hass, b.remaining_days))
        : "";
    case "estimated_empty":
      return b.estimated_empty
        ? esc(fmt(s.empty_on, { d: formatDate(hass, b.estimated_empty) }))
        : "";
    case "remaining_source":
      return b.remaining_source
        ? esc(s.source[b.remaining_source] || b.remaining_source)
        : "";
    case "source_entity":
      return esc(b.source_entity);
    default:
      return "";
  }
}

function details(hass, b, fields) {
  // Each detail stays in one piece; tiles wrap only between them.
  return FIELDS.filter((f) => fields.includes(f))
    .map((f) => formatField(hass, b, f))
    .filter(Boolean)
    .map((part) => `<span class="part">${part}</span>`)
    .join(" · ");
}

function batteryIcon(b) {
  if (b.stale) return "mdi:battery-unknown";
  return CATEGORY_ICON[b.category] || CATEGORY_ICON.unknown_default;
}

// ---------------------------------------------------------------------------
// Shared rendering
// ---------------------------------------------------------------------------

const BASE_STYLE = `
  :host { display: block; }
  ha-card { height: 100%; box-sizing: border-box; overflow: hidden; }
  .icon-wrap {
    position: relative; flex: none;
    width: 36px; height: 36px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    color: var(--c, var(--state-icon-color));
    background: color-mix(in srgb, var(--c, var(--state-icon-color)) 20%, transparent);
  }
  .icon-wrap ha-icon, .icon-wrap ha-state-icon { --mdc-icon-size: 22px; color: inherit; }
  .text { min-width: 0; flex: 1; display: flex; flex-direction: column; }
  .primary {
    font-size: var(--ha-font-size-m, 14px); font-weight: var(--ha-font-weight-medium, 500);
    line-height: 20px; color: var(--primary-text-color);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .secondary {
    font-size: var(--ha-font-size-s, 12px); line-height: 16px;
    color: var(--secondary-text-color);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .stale { color: var(--error-color, #db4437); }
  .part { white-space: nowrap; }
  .clickable { cursor: pointer; }
  .clickable:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  .row {
    display: flex; align-items: center; gap: 12px;
    padding: 6px 16px; min-height: 48px; box-sizing: border-box;
  }
  .row:hover, .tile:hover { background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); }
  .message { padding: 16px; color: var(--secondary-text-color); }
`;

function iconHtml(b, iconMode, color) {
  const inner =
    iconMode === "entity"
      ? `<ha-state-icon data-state-icon="${esc(b.source_entity)}"></ha-state-icon>`
      : `<ha-icon icon="${esc(batteryIcon(b))}"></ha-icon>`;
  return `<div class="icon-wrap" style="--c:${color}">${inner}</div>`;
}

function batteryRow(hass, b, fields, iconMode, cls = "row") {
  const color = STATUS_COLOR[b.status] || STATUS_COLOR.normal;
  const secondary = details(hass, b, fields);
  return `
    <div class="${cls} clickable" role="button" tabindex="0" data-more-info="${esc(b.source_entity)}">
      ${iconHtml(b, iconMode, color)}
      <div class="text">
        <span class="primary" title="${esc(b.name)}">${esc(b.name)}</span>
        ${secondary ? `<span class="secondary">${secondary}</span>` : ""}
      </div>
    </div>`;
}

function fireEvent(node, type, detail) {
  node.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
}

class BatteryBrainBaseCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._renderKey = null;
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        const target = ev.composedPath()[0];
        if (target?.getAttribute?.("role") === "button") {
          ev.preventDefault();
          target.click();
        }
      }
    });
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    this._config = { ...this.constructor.defaults(), ...config };
    this._renderKey = null;
    this._configChanged();
    this._update();
  }

  _configChanged() {}

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  get hass() {
    return this._hass;
  }

  /** Re-render only when the sensor, the config or the language changed. */
  _update() {
    if (!this._hass || !this._config) return;
    const entityId = findSensor(this._hass, this._config);
    const stateObj = this._hass.states[entityId];
    const key = [stateObj, this._config, lang(this._hass), this._extraKey()];
    const old = this._renderKey;
    if (!old || key.some((v, i) => v !== old[i])) {
      this._renderKey = key;
      this._entityId = entityId;
      this.shadowRoot.innerHTML = this._render(stateObj);
    }
    // Entity icons follow their entity without a full re-render.
    this.shadowRoot.querySelectorAll("ha-state-icon").forEach((el) => {
      el.hass = this._hass;
      el.stateObj = this._hass.states[el.dataset.stateIcon];
    });
  }

  _extraKey() {
    return null;
  }

  /** Common states before any battery can be shown; null when the data is usable. */
  _problem(stateObj) {
    const s = strings(this._hass);
    if (!stateObj) return s.not_found;
    const entry = this._hass.entities?.[stateObj.entity_id];
    if (entry && entry.platform !== DOMAIN) {
      return fmt(s.wrong_entity, { e: stateObj.entity_id });
    }
    if (stateObj.state === "unavailable" || stateObj.state === "unknown") return s.starting;
    return null;
  }

  _onClick(ev) {
    const target = ev.composedPath().find((el) => el.dataset);
    const el = target?.closest?.("[data-more-info]");
    if (el) fireEvent(this, "hass-more-info", { entityId: el.dataset.moreInfo });
  }
}

// ---------------------------------------------------------------------------
// Card A: summary
// ---------------------------------------------------------------------------

class BatteryBrainSummaryCard extends BatteryBrainBaseCard {
  static defaults() {
    return {
      show_counts: ["critical", "warning"],
      hide_zero: false,
      show_badge: true,
      color_by_status: true,
      vertical: false,
      tap_action: { action: "more-info" },
      show_list: false,
      list_max: 3,
      fields: ["last_value", "stale", "remaining_days"],
    };
  }

  static getStubConfig() {
    return { show_counts: ["critical", "warning"] };
  }

  static async getConfigElement() {
    await ensureHaForm();
    return document.createElement("battery-brain-summary-card-editor");
  }

  constructor() {
    super();
    this._holdTimer = null;
    this._held = false;
    const root = this.shadowRoot;
    root.addEventListener("pointerdown", (ev) => {
      if (!ev.composedPath().some((el) => el.classList?.contains("main"))) return;
      this._held = false;
      clearTimeout(this._holdTimer);
      this._holdTimer = setTimeout(() => {
        this._held = true;
        this._action("hold");
      }, 500);
    });
    const cancel = () => clearTimeout(this._holdTimer);
    root.addEventListener("pointerup", cancel);
    root.addEventListener("pointercancel", cancel);
    root.addEventListener(
      "pointerleave",
      (ev) => ev.target.classList?.contains("main") && cancel(),
      true
    );
  }

  _onClick(ev) {
    const path = ev.composedPath();
    if (path.some((el) => el.classList?.contains("main"))) {
      // A hold already fired its own action.
      if (this._held) {
        this._held = false;
        return;
      }
      this._action("tap");
      return;
    }
    super._onClick(ev);
  }

  _action(action) {
    const config = this._config;
    const actionConfig = config[`${action}_action`];
    if (!actionConfig || actionConfig.action === "none") return;
    fireEvent(this, "hass-action", {
      config: {
        entity: this._entityId,
        tap_action: config.tap_action,
        hold_action: config.hold_action,
      },
      action,
    });
  }

  getCardSize() {
    const c = this._config || {};
    return (c.vertical ? 2 : 1) + (c.show_list ? Math.min(c.list_max || 0, 5) : 0);
  }

  getGridOptions() {
    const c = this._config || {};
    // Three counters don't fit into half a section ("30 critical · 13
    // warning · 283 OK"): full width then.
    const columns = !c.vertical && (c.show_counts || []).length >= 3 ? 12 : 6;
    if (c.show_list) return { columns, rows: "auto", min_columns: 4 };
    return { columns, rows: c.vertical ? 2 : 1, min_columns: c.vertical ? 2 : 4 };
  }

  _render(stateObj) {
    const c = this._config;
    const hass = this._hass;
    const s = strings(hass);
    const problem = this._problem(stateObj);
    const batteries = problem ? [] : readBatteries(stateObj);
    const counts = countByStatus(batteries);
    const worst = problem ? null : worstStatus(counts);

    const color =
      worst && c.color_by_status ? STATUS_COLOR[worst] : "var(--state-icon-color)";
    const icon = c.icon || (worst ? STATUS_ICON[worst] : "mdi:battery-unknown");
    const name =
      c.name || (problem ? "BatteryBrain" : plural(hass, s.batteries, batteries.length));

    let secondary = problem;
    if (!problem) {
      const parts = STATUSES.filter((st) => (c.show_counts || []).includes(st))
        .filter((st) => !c.hide_zero || counts[st] > 0)
        .map((st) => fmt(s[`count_${st}`], { n: counts[st] }));
      secondary =
        parts.join(" · ") ||
        (counts.critical + counts.warning === 0 ? s.all_ok : "");
    }

    const badge =
      c.show_badge && counts.critical > 0
        ? `<span class="badge">${counts.critical > 99 ? "99+" : counts.critical}</span>`
        : "";

    let list = "";
    if (c.show_list && !problem) {
      const affected = batteries
        .filter((b) => b.status !== "normal")
        .sort(SORTERS.status);
      const max = Math.max(0, Number(c.list_max) || 0);
      const shown = max ? affected.slice(0, max) : affected;
      if (shown.length) {
        list = `<div class="list">${shown
          .map((b) => batteryRow(hass, b, c.fields || [], "category"))
          .join("")}${
          affected.length > shown.length
            ? `<div class="more">${esc(fmt(s.more, { n: affected.length - shown.length }))}</div>`
            : ""
        }</div>`;
      }
    }

    return `
      <style>${BASE_STYLE}
        .main {
          display: flex; align-items: center; gap: 10px; padding: 10px;
          min-height: 56px; box-sizing: border-box; user-select: none;
        }
        .main.vertical { flex-direction: column; justify-content: center; text-align: center; gap: 6px; height: 100%; }
        .main.vertical .text { align-items: center; flex: none; max-width: 100%; }
        .badge {
          position: absolute; top: -4px; right: -6px; min-width: 16px; height: 16px;
          padding: 0 4px; box-sizing: border-box; border-radius: 8px;
          background: var(--error-color, #db4437); color: var(--text-primary-color, #fff);
          font-size: 10px; font-weight: 600; line-height: 16px; text-align: center;
        }
        .list { border-top: 1px solid var(--divider-color); padding: 4px 0; }
        .list .row { padding: 4px 12px; min-height: 44px; }
        .list .icon-wrap { width: 30px; height: 30px; }
        .list .icon-wrap ha-icon { --mdc-icon-size: 18px; }
        .more { padding: 4px 12px 8px 54px; font-size: 12px; color: var(--secondary-text-color); }
      </style>
      <ha-card>
        <div class="main clickable ${c.vertical ? "vertical" : ""}" role="button" tabindex="0">
          <div class="icon-wrap" style="--c:${color}">
            <ha-icon icon="${esc(icon)}"></ha-icon>${badge}
          </div>
          <div class="text">
            <span class="primary">${esc(name)}</span>
            ${secondary ? `<span class="secondary">${esc(secondary)}</span>` : ""}
          </div>
        </div>
        ${list}
      </ha-card>`;
  }
}

// ---------------------------------------------------------------------------
// Card B: detailed list / grid
// ---------------------------------------------------------------------------

const PICKER_MAX_PER_GROUP = 2;

class BatteryBrainCard extends BatteryBrainBaseCard {
  static defaults() {
    return {
      group_by_status: true,
      statuses: [...STATUSES],
      hide_empty: true,
      collapse_normal: true,
      layout: "list",
      columns: 2,
      icon_mode: "category",
      fields: ["last_value", "category", "confidence", "stale", "estimated_empty"],
      sort: "remaining",
      categories: [],
      stale_filter: "all",
      max_per_group: 0,
    };
  }

  static getStubConfig(hass) {
    // OK is collapsed by default: a compact start that shows what needs
    // attention first.
    return { title: strings(hass).title };
  }

  static async getConfigElement() {
    await ensureHaForm();
    return document.createElement("battery-brain-card-editor");
  }

  constructor() {
    super();
    this._collapsed = null;
  }

  _configChanged() {
    this._collapsed = new Set(this._config.collapse_normal ? ["normal"] : []);
    this._collapsedKey = [...this._collapsed].join(",");
  }

  _extraKey() {
    // Toggling a section must re-render although nothing else changed.
    return `${this._collapsedKey}|${this._inCardPicker()}`;
  }

  connectedCallback() {
    // Only now is it known whether the card sits in the card picker.
    this._renderKey = null;
    this._update();
  }

  /** Shown as a preview in "Add card" (HA passes no preview flag). */
  _inCardPicker() {
    return this.getRootNode?.()?.host?.localName === "hui-card-picker";
  }

  _onClick(ev) {
    const toggle = ev
      .composedPath()
      .find((el) => el.dataset && el.dataset.toggle !== undefined);
    if (toggle) {
      const status = toggle.dataset.toggle;
      if (this._collapsed.has(status)) this._collapsed.delete(status);
      else this._collapsed.add(status);
      this._collapsedKey = [...this._collapsed].join(",");
      this._update();
      return;
    }
    super._onClick(ev);
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: "full", rows: "auto", min_columns: 6 };
  }

  _filtered(batteries) {
    const c = this._config;
    const cats = c.categories || [];
    return batteries.filter(
      (b) =>
        (c.statuses || STATUSES).includes(b.status) &&
        (!cats.length || cats.includes(b.category)) &&
        (c.stale_filter === "hide" ? !b.stale : c.stale_filter === "only" ? b.stale : true)
    );
  }

  _items(hass, batteries) {
    const c = this._config;
    const grid = c.layout === "grid";
    // In the card picker the whole list (hundreds of batteries) made the
    // row so tall that the summary card next to it was out of sight.
    const max = this._inCardPicker()
      ? PICKER_MAX_PER_GROUP
      : Math.max(0, Number(c.max_per_group) || 0);
    const shown = max ? batteries.slice(0, max) : batteries;
    const html = shown
      .map((b) => batteryRow(hass, b, c.fields || [], c.icon_mode, grid ? "tile" : "row"))
      .join("");
    const more =
      batteries.length > shown.length
        ? `<div class="more">${esc(fmt(strings(hass).more, { n: batteries.length - shown.length }))}</div>`
        : "";
    const cols = Math.min(4, Math.max(1, Number(c.columns) || 2));
    return grid
      ? `<div class="grid" style="--cols:${cols}">${html}</div>${more}`
      : `<div class="list">${html}</div>${more}`;
  }

  _render(stateObj) {
    const c = this._config;
    const hass = this._hass;
    const s = strings(hass);
    const problem = this._problem(stateObj);
    const header = c.title ? `<h1 class="card-header">${esc(c.title)}</h1>` : "";

    let body;
    if (problem) {
      body = `<div class="message">${esc(problem)}</div>`;
    } else {
      const batteries = this._filtered(readBatteries(stateObj));
      const sorter = SORTERS[c.sort] || SORTERS.remaining;
      if (c.group_by_status) {
        body = STATUSES.filter((st) => (c.statuses || STATUSES).includes(st))
          .map((st) => {
            const group = batteries.filter((b) => b.status === st).sort(sorter);
            if (!group.length && c.hide_empty) return "";
            const collapsed = this._collapsed.has(st);
            return `
              <section>
                <div class="section-header clickable" role="button" tabindex="0"
                     data-toggle="${st}" aria-expanded="${!collapsed}">
                  <span class="dot" style="background:${STATUS_COLOR[st]}"></span>
                  <span class="section-title">${esc(s.status[st])}</span>
                  <span class="count">${group.length}</span>
                  <ha-icon class="chevron ${collapsed ? "collapsed" : ""}" icon="mdi:chevron-down"></ha-icon>
                </div>
                ${collapsed || !group.length ? "" : this._items(hass, group)}
              </section>`;
          })
          .join("");
      } else {
        body = batteries.length ? this._items(hass, [...batteries].sort(sorter)) : "";
      }
      if (!body.trim()) body = `<div class="message">${esc(s.none)}</div>`;
    }

    return `
      <style>${BASE_STYLE}
        .card-header {
          margin: 0; padding: 12px 16px 4px;
          font-size: var(--ha-card-header-font-size, 24px); font-weight: normal;
          line-height: 40px; color: var(--ha-card-header-color, var(--primary-text-color));
        }
        .content { padding: 8px 0; container-type: inline-size; }
        section + section { border-top: 1px solid var(--divider-color); }
        .section-header {
          display: flex; align-items: center; gap: 8px;
          padding: 10px 16px; user-select: none;
        }
        .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
        .section-title { font-weight: var(--ha-font-weight-medium, 500); color: var(--primary-text-color); }
        .count {
          font-size: 12px; color: var(--secondary-text-color);
          padding: 0 8px; border-radius: 10px; line-height: 20px;
          background: color-mix(in srgb, var(--primary-text-color) 6%, transparent);
        }
        .chevron { margin-left: auto; color: var(--secondary-text-color); transition: transform 0.2s; }
        .chevron.collapsed { transform: rotate(-90deg); }
        .list { padding-bottom: 4px; }
        .grid {
          display: grid; gap: 8px; padding: 4px 16px 12px;
          grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
        }
        /* Narrow cards (phones, small columns): one tile per row. */
        @container (max-width: 420px) {
          .grid { grid-template-columns: minmax(0, 1fr); }
        }
        .tile {
          display: flex; align-items: flex-start; gap: 10px; padding: 10px;
          border: 1px solid var(--divider-color);
          border-radius: var(--ha-card-border-radius, 12px);
        }
        .tile .primary, .tile .secondary { white-space: normal; overflow-wrap: anywhere; }
        .tile .primary {
          display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
        }
        .more { padding: 0 16px 8px 64px; font-size: 12px; color: var(--secondary-text-color); }
        .grid + .more { padding-left: 16px; }
      </style>
      <ha-card>
        ${header}
        <div class="content">${body}</div>
      </ha-card>`;
  }
}

// ---------------------------------------------------------------------------
// Editors (ha-form, no YAML needed)
// ---------------------------------------------------------------------------

/** ha-form is lazy-loaded by HA; loading a built-in card editor pulls it in. */
async function ensureHaForm() {
  if (customElements.get("ha-form")) return;
  try {
    const helpers = await window.loadCardHelpers();
    const card = await helpers.createCardElement({ type: "entities", entities: [] });
    await card.constructor.getConfigElement();
  } catch (err) {
    // The editor still renders once HA loads ha-form on its own.
  }
}

function options(values, labels) {
  return values.map((value) => ({ value, label: labels[value] || value }));
}

function fieldSelector(s) {
  return {
    select: { multiple: true, mode: "list", options: options(FIELDS, s.field) },
  };
}

class BatteryBrainBaseEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    const languageChanged = lang(hass) !== lang(this._hass);
    this._hass = hass;
    if (this._form) {
      this._form.hass = hass;
      if (languageChanged) this._form.schema = this._schema(strings(hass));
    } else {
      this._render();
    }
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (item) =>
        strings(this._hass).editor[item.name] || item.label || item.name;
      this._form.computeHelper = (item) => {
        const helpers = this._helpers(strings(this._hass));
        return helpers[item.name];
      };
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        // Keep the YAML short: drop empty values and untouched defaults.
        const defaults = this._card.defaults();
        const config = { ...ev.detail.value };
        for (const [k, v] of Object.entries(config)) {
          if (
            v === "" ||
            v === undefined ||
            (k in defaults && JSON.stringify(v) === JSON.stringify(defaults[k]))
          ) {
            delete config[k];
          }
        }
        this._config = config;
        fireEvent(this, "config-changed", { config });
      });
      this.appendChild(this._form);
      this._form.schema = this._schema(strings(this._hass));
    }
    this._form.hass = this._hass;
    this._form.data = { ...this._card.defaults(), ...this._config };
  }

  _helpers(s) {
    return {
      entity: s.editor.entity_helper,
      categories: s.editor.categories_helper,
      max_per_group: s.editor.max_helper,
    };
  }

  _entitySchema() {
    return {
      name: "entity",
      selector: { entity: { filter: { integration: DOMAIN, domain: "sensor" } } },
    };
  }
}

class BatteryBrainSummaryCardEditor extends BatteryBrainBaseEditor {
  get _card() {
    return BatteryBrainSummaryCard;
  }

  _schema(s) {
    const e = s.editor;
    return [
      this._entitySchema(),
      {
        type: "grid",
        name: "",
        schema: [
          { name: "name", selector: { text: {} } },
          { name: "icon", selector: { icon: {} } },
        ],
      },
      {
        type: "expandable",
        name: "",
        flatten: true,
        title: e.sec_content,
        icon: "mdi:text-short",
        expanded: true,
        schema: [
          {
            name: "show_counts",
            selector: {
              select: { multiple: true, mode: "list", options: options(STATUSES, s.status) },
            },
          },
          { name: "hide_zero", selector: { boolean: {} } },
        ],
      },
      {
        type: "expandable",
        name: "",
        flatten: true,
        title: e.sec_look,
        icon: "mdi:palette-outline",
        schema: [
          { name: "show_badge", selector: { boolean: {} } },
          { name: "color_by_status", selector: { boolean: {} } },
          { name: "vertical", selector: { boolean: {} } },
        ],
      },
      {
        type: "expandable",
        name: "",
        flatten: true,
        title: e.sec_list,
        icon: "mdi:format-list-bulleted",
        schema: [
          { name: "show_list", selector: { boolean: {} } },
          { name: "list_max", selector: { number: { min: 0, max: 50, mode: "box" } } },
          { name: "fields", selector: fieldSelector(s) },
        ],
      },
      {
        type: "expandable",
        name: "",
        flatten: true,
        title: e.sec_actions,
        icon: "mdi:gesture-tap",
        schema: [
          { name: "tap_action", selector: { ui_action: { default_action: "more-info" } } },
          { name: "hold_action", selector: { ui_action: { default_action: "none" } } },
        ],
      },
    ];
  }
}

class BatteryBrainCardEditor extends BatteryBrainBaseEditor {
  get _card() {
    return BatteryBrainCard;
  }

  _schema(s) {
    const e = s.editor;
    return [
      this._entitySchema(),
      { name: "title", selector: { text: {} } },
      {
        type: "expandable",
        name: "",
        flatten: true,
        title: e.sec_content,
        icon: "mdi:text-short",
        expanded: true,
        schema: [
          { name: "fields", selector: fieldSelector(s) },
          {
            name: "statuses",
            selector: {
              select: { multiple: true, mode: "list", options: options(STATUSES, s.status) },
            },
          },
          { name: "group_by_status", selector: { boolean: {} } },
          { name: "hide_empty", selector: { boolean: {} } },
          { name: "collapse_normal", selector: { boolean: {} } },
        ],
      },
      {
        type: "expandable",
        name: "",
        flatten: true,
        title: e.sec_look,
        icon: "mdi:palette-outline",
        schema: [
          {
            name: "layout",
            selector: {
              select: {
                mode: "dropdown",
                options: [
                  { value: "list", label: e.layout_list },
                  { value: "grid", label: e.layout_grid },
                ],
              },
            },
          },
          { name: "columns", selector: { number: { min: 1, max: 4, mode: "slider" } } },
          {
            name: "icon_mode",
            selector: {
              select: {
                mode: "dropdown",
                options: [
                  { value: "category", label: e.icon_category },
                  { value: "entity", label: e.icon_entity },
                ],
              },
            },
          },
        ],
      },
      {
        type: "expandable",
        name: "",
        flatten: true,
        title: e.sec_filter,
        icon: "mdi:filter-variant",
        schema: [
          {
            name: "sort",
            selector: {
              select: {
                mode: "dropdown",
                options: ["status", "remaining", "value", "name"].map((v) => ({
                  value: v,
                  label: e[`sort_${v}`],
                })),
              },
            },
          },
          {
            name: "categories",
            selector: {
              select: { multiple: true, mode: "list", options: options(CATEGORIES, s.category) },
            },
          },
          {
            name: "stale_filter",
            selector: {
              select: {
                mode: "dropdown",
                options: ["all", "hide", "only"].map((v) => ({
                  value: v,
                  label: e[`stale_${v}`],
                })),
              },
            },
          },
          { name: "max_per_group", selector: { number: { min: 0, max: 100, mode: "box" } } },
        ],
      },
    ];
  }
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

const ELEMENTS = {
  "battery-brain-summary-card": BatteryBrainSummaryCard,
  "battery-brain-card": BatteryBrainCard,
  "battery-brain-summary-card-editor": BatteryBrainSummaryCardEditor,
  "battery-brain-card-editor": BatteryBrainCardEditor,
};
function defineElements() {
  for (const [tag, cls] of Object.entries(ELEMENTS)) {
    if (!customElements.get(tag)) customElements.define(tag, cls);
  }
}

// While booting, HA replaces window.customElements with a scoped-registry
// polyfill. This module is loaded as an extra module in parallel to the app
// and may run first; elements defined on the native registry are then
// invisible to HA ("Custom element not found"). HA's root element only
// exists once the polyfill is in place, so wait for it — without a timeout:
// on slow devices the app can take longer than any fixed delay, and defining
// too early is exactly the failure. This module is only loaded by HA's app.
Promise.race([
  customElements.whenDefined("home-assistant"),
  customElements.whenDefined("hc-main"),
]).then(defineElements);

window.customCards = window.customCards || [];
const DOCS = "https://github.com/larsbaum/battery_brain#dashboard-cards";
const CARDS = [
  {
    type: "battery-brain-summary-card",
    name: "BatteryBrain: Summary",
    description: "Compact status of all batteries, optionally with the batteries that need attention.",
  },
  {
    type: "battery-brain-card",
    name: "BatteryBrain: Battery list",
    description: "All batteries grouped by status with value, remaining time and more.",
  },
];
for (const card of CARDS) {
  if (!window.customCards.some((c) => c.type === card.type)) {
    window.customCards.push({ ...card, preview: true, documentationURL: DOCS });
  }
}
