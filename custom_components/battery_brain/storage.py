"""Persistent history storage and recorder seeding for BatteryBrain."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .analysis import merge_replacement_events
from .const import (
    HISTORY_MAX_DAYS,
    HISTORY_RAW_DAYS,
    LOGGER,
    STORAGE_KEY,
    STORAGE_VERSION,
)

# Like HA's restore_state: at most 15 min of data is lost on a crash, while a
# large store (hundreds of batteries) isn't rewritten every few minutes.
SAVE_DELAY = 900
# Decimals kept for imported means and daily means (more is just noise).
VALUE_DECIMALS = 3
# Persisted replacement events per battery (oldest are dropped).
MAX_REPLACEMENTS = 20

# Where a battery's values come from (stored as "source").
SOURCE_STATE = "state"
SOURCE_ATTRIBUTE = "attribute"


class BatteryHistoryStore:
    """Per-battery history with JSON persistence via HA Store.

    Layout per battery (all fields optional when loading older data):
    raw_points [[ts, value], …] of the last HISTORY_RAW_DAYS, daily_summaries
    for older data, first_seen/last_seen, seeded, source, category,
    last_classified, pending_category/pending_count (classification
    hysteresis) and replacements (timestamps, kept beyond the history).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, dict[str, Any]] = {}
        # Unused since 1.0 (test-mode state); kept so the file round-trips.
        self._meta: dict[str, Any] = {}
        # A delayed write is already scheduled (see _schedule_save).
        self._save_pending = False

    async def async_load(self) -> None:
        """Load stored history from .storage/."""
        stored = await self._store.async_load()
        if stored and isinstance(stored, dict):
            self._data = stored.get("batteries", {})
            self._meta = stored.get("meta", {})
        else:
            self._data = {}
            self._meta = {}

    def _schedule_save(self) -> None:
        """Write at most SAVE_DELAY after the first unsaved change.

        Store.async_delay_save() moves a pending write to "now + delay" on
        every call. Batteries report all the time, so calling it on each
        change would postpone the write until shutdown — a crash or power
        cut would lose everything since the last restart. Only the first
        change after a write schedules one.
        """
        if self._save_pending:
            return
        self._save_pending = True
        self._store.async_delay_save(self._serialize, SAVE_DELAY)

    async def async_save_immediate(self) -> None:
        """Force an immediate write to disk."""
        await self._store.async_save(self._serialize())

    def _serialize(self) -> dict[str, Any]:
        # Called when the data is actually written (delayed or immediate):
        # later changes need a new write.
        self._save_pending = False
        return {"batteries": self._data, "meta": self._meta}

    def as_dict(self) -> dict[str, dict[str, Any]]:
        """All stored battery data (read-only use, e.g. diagnostics)."""
        return self._data

    # --- Query helpers ---

    def has_battery(self, entity_id: str) -> bool:
        return entity_id in self._data

    def is_seeded(self, entity_id: str) -> bool:
        data = self._data.get(entity_id)
        return bool(data and data.get("seeded"))

    def get_raw_points(self, entity_id: str) -> list[list[float]]:
        data = self._data.get(entity_id)
        if not data:
            return []
        return data.get("raw_points", [])

    def get_daily_summaries(self, entity_id: str) -> list[dict[str, Any]]:
        data = self._data.get(entity_id)
        if not data:
            return []
        return data.get("daily_summaries", [])

    def get_history_days(
        self, entity_id: str, *, now_ts: float | None = None
    ) -> float:
        """Total history span in fractional days."""
        data = self._data.get(entity_id)
        if not data:
            return 0.0

        now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
        first = data.get("first_seen", now)

        summaries = data.get("daily_summaries", [])
        if summaries:
            first = min(first, _date_ts(min(s["date"] for s in summaries)))

        raw = data.get("raw_points", [])
        if raw:
            first = min(first, raw[0][0])

        return max((now - first) / 86400.0, 0.0)

    def get_all_values(self, entity_id: str) -> list[float]:
        """Return all known numeric values (raw + daily means) chronologically."""
        return [v for _, v in self.get_all_points(entity_id)]

    def get_all_points(self, entity_id: str) -> list[list[float]]:
        """Return all known [ts, value] points (raw + daily means) chronologically."""
        values: list[list[float]] = [
            [_date_ts(summary["date"]), summary["mean"]]
            for summary in self.get_daily_summaries(entity_id)
        ]
        values.extend(
            [point[0], point[1]]
            for point in self.get_raw_points(entity_id)
            if point[1] is not None
        )
        values.sort(key=lambda p: p[0])
        return values

    def get_first_seen(self, entity_id: str) -> float | None:
        data = self._data.get(entity_id)
        if not data:
            return None
        return data.get("first_seen")

    def get_last_seen_ts(self, entity_id: str) -> float | None:
        """Timestamp when the sensor was last observed alive by the coordinator."""
        data = self._data.get(entity_id)
        if not data:
            return None
        return data.get("last_seen")

    def set_last_seen(self, entity_id: str, ts: float) -> None:
        """Update the last-seen timestamp (in-memory only, no save triggered)."""
        data = self._data.get(entity_id)
        if data is not None:
            data["last_seen"] = ts

    def get_last_update_ts(self, entity_id: str) -> float | None:
        """Timestamp of the most recent data point."""
        data = self._data.get(entity_id)
        if not data:
            return None
        raw = data.get("raw_points", [])
        if raw:
            return raw[-1][0]
        return data.get("first_seen")

    def get_median_interval(self, entity_id: str) -> float | None:
        """Median reporting interval in seconds, or None if < 3 points."""
        raw = self.get_raw_points(entity_id)
        if len(raw) < 3:
            return None
        intervals = sorted(
            raw[i][0] - raw[i - 1][0] for i in range(1, len(raw))
        )
        mid = len(intervals) // 2
        if len(intervals) % 2 == 0:
            return (intervals[mid - 1] + intervals[mid]) / 2
        return intervals[mid]

    # --- Category persistence ---

    def get_category(self, entity_id: str) -> str | None:
        data = self._data.get(entity_id)
        if not data:
            return None
        return data.get("category")

    def get_last_classified(self, entity_id: str) -> float | None:
        data = self._data.get(entity_id)
        if not data:
            return None
        return data.get("last_classified")

    def reset_all_last_classified(self) -> None:
        for data in self._data.values():
            data.pop("last_classified", None)
        self._schedule_save()

    def set_category(
        self, entity_id: str, category: str, *, now_ts: float | None = None
    ) -> None:
        data = self._ensure_battery(entity_id)
        data["category"] = category
        data["last_classified"] = (
            now_ts if now_ts is not None else dt_util.utcnow().timestamp()
        )
        self._schedule_save()

    def get_pending_category(self, entity_id: str) -> tuple[str | None, int]:
        """Category waiting for confirmation and how often it was seen."""
        data = self._data.get(entity_id) or {}
        return data.get("pending_category"), data.get("pending_count", 0)

    def set_pending_category(
        self, entity_id: str, category: str | None, count: int = 0
    ) -> None:
        data = self._ensure_battery(entity_id)
        if category is None:
            if data.pop("pending_category", None) is None:
                return
            data.pop("pending_count", None)
        else:
            data["pending_category"] = category
            data["pending_count"] = count
        self._schedule_save()

    # --- Replacement events ---

    def get_replacements(self, entity_id: str) -> list[float]:
        data = self._data.get(entity_id)
        if not data:
            return []
        return data.get("replacements", [])

    def sync_replacements(
        self,
        entity_id: str,
        detected: list[float] | None,
        history_start: float,
    ) -> None:
        """Remember replacement events so they outlive the history pruning.

        Within the stored history (from *history_start*) only the *detected*
        events count, which also drops wrongly stored ones (charge bursts,
        solar spikes stored before 1.0 checked them). Older events are kept.
        None means this battery doesn't have replacements (e.g. it is
        recharged), and clears the list.
        """
        data = self._data.get(entity_id)
        if data is None:
            return
        known = data.get("replacements", [])
        if detected is None:
            merged: list[float] = []
        else:
            older = [ts for ts in known if ts < history_start]
            merged = merge_replacement_events(older, detected)[-MAX_REPLACEMENTS:]
        if merged != known:
            if merged:
                data["replacements"] = merged
            else:
                data.pop("replacements", None)
            self._schedule_save()

    # --- Mutation ---

    def _ensure_battery(
        self, entity_id: str, now_ts: float | None = None
    ) -> dict[str, Any]:
        if entity_id not in self._data:
            # Use the provided timestamp (virtual in test mode) so that
            # get_history_days() correctly computes virtual elapsed days.
            ts = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
            self._data[entity_id] = {
                "raw_points": [],
                "daily_summaries": [],
                "first_seen": ts,
                "last_seen": ts,
                "seeded": False,
            }
        return self._data[entity_id]

    def ensure_source(
        self, entity_id: str, source: str, *, now_ts: float | None = None
    ) -> bool:
        """Record where the values come from; reset the history if it changed.

        Before 1.0, batteries read from a ``battery_level`` attribute also
        stored the host entity's state (e.g. a temperature) and imported its
        recorder history. Such legacy entries (no source yet) are reset once.
        Returns True if the history was reset.
        """
        data = self._data.get(entity_id)
        if data is None:
            return False
        stored = data.get("source")
        if stored == source:
            return False
        reset = stored is not None or source == SOURCE_ATTRIBUTE
        if reset:
            ts = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
            for key in (
                "category",
                "last_classified",
                "pending_category",
                "pending_count",
                "replacements",
            ):
                data.pop(key, None)
            data.update(
                raw_points=[],
                daily_summaries=[],
                first_seen=ts,
                last_seen=ts,
                seeded=True,
            )
        data["source"] = source
        self._schedule_save()
        return reset

    def add_point(
        self, entity_id: str, timestamp: float, value: float | None
    ) -> None:
        """Append a single data point (deduplicates by timestamp)."""
        if value is None:
            return
        data = self._ensure_battery(entity_id, now_ts=timestamp)
        raw = data["raw_points"]
        if raw and raw[-1][0] >= timestamp:
            return
        raw.append([timestamp, value])
        self._schedule_save()

    def add_points_bulk(
        self, entity_id: str, points: list[tuple[float, float | None]]
    ) -> None:
        """Add multiple points at once (recorder seeding)."""
        data = self._ensure_battery(entity_id)
        raw = data["raw_points"]
        existing_ts = {p[0] for p in raw}
        added = 0
        for ts, val in points:
            if val is None or ts in existing_ts:
                continue
            raw.append([ts, val])
            existing_ts.add(ts)
            added += 1
        if added:
            raw.sort(key=lambda p: p[0])
            if raw:
                data["first_seen"] = min(data["first_seen"], raw[0][0])
            self._schedule_save()

    def mark_seeded(self, entity_id: str) -> None:
        self._ensure_battery(entity_id)
        self._data[entity_id]["seeded"] = True
        self._schedule_save()

    # --- Aggregation ---

    def aggregate(self, *, now_ts: float | None = None) -> None:
        """Promote raw points older than 30 d to daily summaries, prune > 365 d.

        Batteries without any data left whose entity hasn't been seen for
        HISTORY_MAX_DAYS are dropped entirely.
        """
        now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
        cutoff_raw = now - HISTORY_RAW_DAYS * 86400
        cutoff_max = now - HISTORY_MAX_DAYS * 86400
        cutoff_max_str = datetime.fromtimestamp(
            cutoff_max, tz=timezone.utc
        ).strftime("%Y-%m-%d")
        dirty = False

        for entity_id in list(self._data):
            data = self._data[entity_id]
            raw = data.get("raw_points", [])
            summaries = data.setdefault("daily_summaries", [])

            old = [p for p in raw if p[0] < cutoff_raw]
            if old:
                data["raw_points"] = raw = [p for p in raw if p[0] >= cutoff_raw]
                _merge_into_summaries(summaries, old)
                dirty = True

            pruned = [s for s in summaries if s["date"] >= cutoff_max_str]
            if len(pruned) != len(summaries):
                summaries[:] = pruned
                dirty = True

            if (
                not raw
                and not summaries
                and data.get("last_seen", now) < cutoff_max
            ):
                del self._data[entity_id]
                dirty = True

        if dirty:
            self._schedule_save()


def _date_ts(date_str: str) -> float:
    return (
        datetime.strptime(date_str, "%Y-%m-%d")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )


def _merge_into_summaries(
    summaries: list[dict[str, Any]], points: list[list[float]]
) -> None:
    by_date: dict[str, list[float]] = defaultdict(list)
    for ts, val in points:
        if val is not None:
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            by_date[date_str].append(val)

    existing_idx = {s["date"]: i for i, s in enumerate(summaries)}
    for date_str, values in by_date.items():
        if date_str in existing_idx:
            s = summaries[existing_idx[date_str]]
            total = s["count"] + len(values)
            s["mean"] = round(
                (s["mean"] * s["count"] + sum(values)) / total, VALUE_DECIMALS
            )
            s["min"] = min(s["min"], min(values))
            s["max"] = max(s["max"], max(values))
            s["count"] = total
        else:
            summaries.append(
                {
                    "date": date_str,
                    "min": min(values),
                    "mean": round(sum(values) / len(values), VALUE_DECIMALS),
                    "max": max(values),
                    "count": len(values),
                }
            )
    summaries.sort(key=lambda s: s["date"])


# --- Recorder seeding ---


async def async_seed_from_recorder(
    hass: HomeAssistant,
    store: BatteryHistoryStore,
    entity_ids: list[str],
    binary_ids: set[str],
) -> None:
    """Import up to HISTORY_MAX_DAYS of recorder history for new batteries.

    One Long-Term-Statistics query (hourly means) for all numeric entities,
    then one state-history query for everything without statistics.
    """
    from homeassistant.components.recorder import get_instance

    instance = get_instance(hass)
    start_time = dt_util.utcnow() - timedelta(days=HISTORY_MAX_DAYS)

    numeric = {e for e in entity_ids if e not in binary_ids}
    history = (
        await _long_term_statistics(hass, instance, numeric, start_time)
        if numeric
        else {}
    )
    missing = [e for e in entity_ids if not history.get(e)]
    if missing:
        history.update(
            await _state_history(hass, instance, missing, start_time, binary_ids)
        )

    imported = 0
    for entity_id in entity_ids:
        points = history.get(entity_id)
        if points:
            points.sort(key=lambda p: p[0])
            store.add_points_bulk(entity_id, points)
            imported += 1
            LOGGER.debug(
                "Seeded %d historical data points for %s", len(points), entity_id
            )
        store.mark_seeded(entity_id)
    # One line: hundreds of batteries triggered HA's "logging too frequently".
    LOGGER.info(
        "Imported recorder history for %d of %d new batteries",
        imported,
        len(entity_ids),
    )


async def _long_term_statistics(
    hass: HomeAssistant,
    instance: Any,
    entity_ids: set[str],
    start_time: datetime,
) -> dict[str, list[tuple[float, float]]]:
    """Hourly means from Long-Term Statistics, per entity."""
    try:
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
        )

        stats: dict[str, list[dict[str, Any]]] = (
            await instance.async_add_executor_job(
                statistics_during_period,
                hass,
                start_time,
                None,
                entity_ids,
                "hour",
                None,
                {"mean"},
            )
        )
    except Exception:  # noqa: BLE001 - recorder errors must not break setup
        LOGGER.debug("Could not read long-term statistics", exc_info=True)
        return {}

    result: dict[str, list[tuple[float, float]]] = {}
    for entity_id, rows in stats.items():
        points: list[tuple[float, float]] = []
        for row in rows:
            ts = row.get("start")
            if isinstance(ts, datetime):
                ts = ts.timestamp()
            elif not isinstance(ts, (int, float)):
                continue
            mean_val = row.get("mean")
            if mean_val is not None:
                points.append((float(ts), round(float(mean_val), VALUE_DECIMALS)))
        if points:
            result[entity_id] = points
    return result


async def _state_history(
    hass: HomeAssistant,
    instance: Any,
    entity_ids: list[str],
    start_time: datetime,
    binary_ids: set[str],
) -> dict[str, list[tuple[float, float]]]:
    """Fallback: values from the raw state history, per entity."""
    try:
        from homeassistant.components.recorder.history import (
            get_significant_states,
        )

        states_dict = await instance.async_add_executor_job(
            get_significant_states,
            hass,
            start_time,
            None,
            entity_ids,
        )
    except Exception:  # noqa: BLE001 - recorder errors must not break setup
        LOGGER.debug("Could not read state history", exc_info=True)
        return {}

    result: dict[str, list[tuple[float, float]]] = {}
    for entity_id, states in states_dict.items():
        points: list[tuple[float, float]] = []
        for state_obj in states:
            if state_obj.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            if entity_id in binary_ids:
                val = 1.0 if state_obj.state == STATE_ON else 0.0
            else:
                try:
                    val = float(state_obj.state)
                except (ValueError, TypeError):
                    continue
            points.append((state_obj.last_updated.timestamp(), val))
        if points:
            result[entity_id] = points
    return result
