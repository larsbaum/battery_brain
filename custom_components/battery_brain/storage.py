"""Persistent history storage and recorder seeding for BatteryBrain."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    HISTORY_MAX_DAYS,
    HISTORY_RAW_DAYS,
    LOGGER,
    STORAGE_KEY,
    STORAGE_VERSION,
)

SAVE_DELAY = 300


class BatteryHistoryStore:
    """Per-battery history with JSON persistence via HA Store."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, dict[str, Any]] = {}
        self._meta: dict[str, Any] = {}

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
        self._store.async_delay_save(self._serialize, SAVE_DELAY)

    async def async_save_immediate(self) -> None:
        """Force an immediate write to disk."""
        await self._store.async_save(self._serialize())

    def _serialize(self) -> dict[str, Any]:
        return {"batteries": self._data, "meta": self._meta}

    # --- Global meta (test mode state, etc.) ---

    def get_meta(self, key: str, default: Any = None) -> Any:
        return self._meta.get(key, default)

    def set_meta(self, key: str, value: Any) -> None:
        self._meta[key] = value
        self._schedule_save()

    # --- Query helpers ---

    def get_battery_data(self, entity_id: str) -> dict[str, Any] | None:
        return self._data.get(entity_id)

    def has_history(self, entity_id: str) -> bool:
        data = self._data.get(entity_id)
        if not data:
            return False
        return bool(data.get("raw_points")) or bool(data.get("daily_summaries"))

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
            oldest_str = min(s["date"] for s in summaries)
            oldest_ts = (
                datetime.strptime(oldest_str, "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
            first = min(first, oldest_ts)

        raw = data.get("raw_points", [])
        if raw:
            first = min(first, raw[0][0])

        return max((now - first) / 86400.0, 0.0)

    def get_all_values(self, entity_id: str) -> list[float]:
        """Return all known numeric values (raw + daily means) chronologically."""
        values: list[tuple[float, float]] = []

        for summary in self.get_daily_summaries(entity_id):
            ts = (
                datetime.strptime(summary["date"], "%Y-%m-%d")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
            values.append((ts, summary["mean"]))

        for point in self.get_raw_points(entity_id):
            if point[1] is not None:
                values.append((point[0], point[1]))

        values.sort(key=lambda p: p[0])
        return [v for _, v in values]

    def get_last_update_ts(self, entity_id: str) -> float | None:
        """Timestamp of the most recent data point."""
        data = self._data.get(entity_id)
        if not data:
            return None
        raw = data.get("raw_points", [])
        if raw:
            return raw[-1][0]
        return data.get("first_seen")

    def get_recent_points(
        self, entity_id: str, days: int = 7, *, now_ts: float | None = None
    ) -> list[list[float]]:
        """Raw points from the last N days."""
        now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
        cutoff = now - days * 86400
        return [
            p for p in self.get_raw_points(entity_id) if p[0] >= cutoff
        ]

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

    def set_category(
        self, entity_id: str, category: str, *, now_ts: float | None = None
    ) -> None:
        data = self._ensure_battery(entity_id)
        data["category"] = category
        data["last_classified"] = (
            now_ts if now_ts is not None else dt_util.utcnow().timestamp()
        )
        self._schedule_save()

    # --- Mutation ---

    def _ensure_battery(self, entity_id: str) -> dict[str, Any]:
        if entity_id not in self._data:
            self._data[entity_id] = {
                "raw_points": [],
                "daily_summaries": [],
                "first_seen": dt_util.utcnow().timestamp(),
                "seeded": False,
            }
        return self._data[entity_id]

    def add_point(
        self, entity_id: str, timestamp: float, value: float | None
    ) -> None:
        """Append a single data point (deduplicates by timestamp)."""
        if value is None:
            return
        data = self._ensure_battery(entity_id)
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

    def remove_battery(self, entity_id: str) -> None:
        if entity_id in self._data:
            del self._data[entity_id]
            self._schedule_save()

    # --- Aggregation ---

    def aggregate(self, *, now_ts: float | None = None) -> None:
        """Promote raw points older than 30d to daily summaries, prune >365d."""
        now = now_ts if now_ts is not None else dt_util.utcnow().timestamp()
        cutoff_raw = now - HISTORY_RAW_DAYS * 86400
        cutoff_max_str = datetime.fromtimestamp(
            now - HISTORY_MAX_DAYS * 86400, tz=timezone.utc
        ).strftime("%Y-%m-%d")
        dirty = False

        for data in self._data.values():
            raw = data.get("raw_points", [])
            if not raw:
                continue

            old = [p for p in raw if p[0] < cutoff_raw]
            if not old:
                # Still prune ancient summaries
                summaries = data.get("daily_summaries", [])
                pruned = [s for s in summaries if s["date"] >= cutoff_max_str]
                if len(pruned) != len(summaries):
                    data["daily_summaries"] = pruned
                    dirty = True
                continue

            data["raw_points"] = [p for p in raw if p[0] >= cutoff_raw]

            by_date: dict[str, list[float]] = defaultdict(list)
            for ts, val in old:
                if val is not None:
                    date_str = datetime.fromtimestamp(
                        ts, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                    by_date[date_str].append(val)

            summaries = data.setdefault("daily_summaries", [])
            existing_idx = {s["date"]: i for i, s in enumerate(summaries)}

            for date_str, values in by_date.items():
                if date_str in existing_idx:
                    s = summaries[existing_idx[date_str]]
                    total = s["count"] + len(values)
                    s["mean"] = (
                        s["mean"] * s["count"] + sum(values)
                    ) / total
                    s["min"] = min(s["min"], min(values))
                    s["max"] = max(s["max"], max(values))
                    s["count"] = total
                else:
                    summaries.append(
                        {
                            "date": date_str,
                            "min": min(values),
                            "mean": sum(values) / len(values),
                            "max": max(values),
                            "count": len(values),
                        }
                    )

            summaries[:] = [
                s for s in summaries if s["date"] >= cutoff_max_str
            ]
            dirty = True

        if dirty:
            self._schedule_save()


# --- Recorder seeding ---


async def async_seed_from_recorder(
    hass: HomeAssistant,
    store: BatteryHistoryStore,
    entity_id: str,
    *,
    is_binary: bool = False,
) -> int:
    """Import historical data from the HA recorder. Returns points added."""
    from homeassistant.components.recorder import get_instance

    instance = get_instance(hass)
    start_time = dt_util.utcnow() - timedelta(days=HISTORY_MAX_DAYS)
    points: list[tuple[float, float | None]] = []

    points = await _try_long_term_statistics(
        hass, instance, entity_id, start_time
    )

    if not points:
        points = await _try_state_history(
            hass, instance, entity_id, start_time, is_binary=is_binary
        )

    if points:
        points.sort(key=lambda p: p[0])
        store.add_points_bulk(entity_id, points)
        LOGGER.info(
            "Seeded %d historical data points for %s", len(points), entity_id
        )

    store.mark_seeded(entity_id)
    return len(points)


async def _try_long_term_statistics(
    hass: HomeAssistant,
    instance: Any,
    entity_id: str,
    start_time: datetime,
) -> list[tuple[float, float | None]]:
    """Try to pull data from Long-Term Statistics."""
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
                {entity_id},
                "hour",
                None,
                {"mean"},
            )
        )

        if entity_id not in stats or not stats[entity_id]:
            return []

        points: list[tuple[float, float | None]] = []
        for row in stats[entity_id]:
            ts = row.get("start")
            if ts is None:
                continue
            if isinstance(ts, datetime):
                ts = ts.timestamp()
            elif not isinstance(ts, (int, float)):
                continue
            mean_val = row.get("mean")
            if mean_val is not None:
                points.append((float(ts), float(mean_val)))
        return points

    except Exception:
        LOGGER.debug(
            "Could not read LTS for %s, will try state history", entity_id
        )
        return []


async def _try_state_history(
    hass: HomeAssistant,
    instance: Any,
    entity_id: str,
    start_time: datetime,
    *,
    is_binary: bool = False,
) -> list[tuple[float, float | None]]:
    """Fall back to reading raw state history."""
    try:
        from homeassistant.components.recorder.history import (
            get_significant_states,
        )

        states_dict = await instance.async_add_executor_job(
            get_significant_states,
            hass,
            start_time,
            None,
            [entity_id],
        )

        if entity_id not in states_dict:
            return []

        points: list[tuple[float, float | None]] = []
        for state_obj in states_dict[entity_id]:
            if state_obj.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            ts = state_obj.last_updated.timestamp()
            if is_binary:
                val = 1.0 if state_obj.state == STATE_ON else 0.0
            else:
                try:
                    val = float(state_obj.state)
                except (ValueError, TypeError):
                    continue
            points.append((ts, val))
        return points

    except Exception:
        LOGGER.debug("Could not read state history for %s", entity_id)
        return []
