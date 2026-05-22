"""Tests for BatteryHistoryStore logic (aggregation, deduplication, helpers)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import FROZEN_NOW, FakeDtUtil

from custom_components.battery_brain.storage import BatteryHistoryStore

NOW_TS = FROZEN_NOW.timestamp()


class FakeHass:
    """Minimal hass stub for BatteryHistoryStore."""

    pass


def _make_store() -> BatteryHistoryStore:
    store = BatteryHistoryStore(FakeHass())
    store._store = _FakeStoreBackend()
    return store


class _FakeStoreBackend:
    """Drop-in for homeassistant.helpers.storage.Store (no disk I/O)."""

    def __init__(self) -> None:
        self._data = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self._data = data

    def async_delay_save(self, func, delay):
        self._data = func()


# =====================================================================
#  add_point / deduplication
# =====================================================================


class TestAddPoint:
    def test_appends_point(self):
        s = _make_store()
        s.add_point("sensor.bat", 1000.0, 95.0)
        assert s.get_raw_points("sensor.bat") == [[1000.0, 95.0]]

    def test_dedup_same_timestamp(self):
        s = _make_store()
        s.add_point("sensor.bat", 1000.0, 95.0)
        s.add_point("sensor.bat", 1000.0, 90.0)
        assert len(s.get_raw_points("sensor.bat")) == 1

    def test_dedup_older_timestamp(self):
        s = _make_store()
        s.add_point("sensor.bat", 1000.0, 95.0)
        s.add_point("sensor.bat", 999.0, 90.0)
        assert len(s.get_raw_points("sensor.bat")) == 1

    def test_skip_none_value(self):
        s = _make_store()
        s.add_point("sensor.bat", 1000.0, None)
        assert s.get_raw_points("sensor.bat") == []

    def test_multiple_points(self):
        s = _make_store()
        s.add_point("sensor.bat", 1000.0, 90.0)
        s.add_point("sensor.bat", 2000.0, 85.0)
        s.add_point("sensor.bat", 3000.0, 80.0)
        assert len(s.get_raw_points("sensor.bat")) == 3


# =====================================================================
#  add_points_bulk
# =====================================================================


class TestAddPointsBulk:
    def test_bulk_add(self):
        s = _make_store()
        pts = [(1000.0, 90.0), (2000.0, 85.0), (3000.0, 80.0)]
        s.add_points_bulk("sensor.bat", pts)
        assert len(s.get_raw_points("sensor.bat")) == 3

    def test_bulk_skips_none(self):
        s = _make_store()
        pts = [(1000.0, 90.0), (2000.0, None), (3000.0, 80.0)]
        s.add_points_bulk("sensor.bat", pts)
        assert len(s.get_raw_points("sensor.bat")) == 2

    def test_bulk_sorts_by_timestamp(self):
        s = _make_store()
        pts = [(3000.0, 80.0), (1000.0, 90.0), (2000.0, 85.0)]
        s.add_points_bulk("sensor.bat", pts)
        raw = s.get_raw_points("sensor.bat")
        assert raw[0][0] < raw[1][0] < raw[2][0]

    def test_bulk_dedup(self):
        s = _make_store()
        s.add_point("sensor.bat", 1000.0, 90.0)
        s.add_points_bulk(
            "sensor.bat",
            [(1000.0, 91.0), (2000.0, 85.0)],
        )
        assert len(s.get_raw_points("sensor.bat")) == 2

    def test_bulk_updates_first_seen(self):
        s = _make_store()
        s.add_point("sensor.bat", NOW_TS, 50.0)
        earlier = NOW_TS - 86400 * 30
        s.add_points_bulk("sensor.bat", [(earlier, 80.0)])
        data = s.get_battery_data("sensor.bat")
        assert data["first_seen"] <= earlier


# =====================================================================
#  Aggregation
# =====================================================================


class TestAggregation:
    def test_old_points_promoted_to_daily(self):
        s = _make_store()
        base = NOW_TS - 40 * 86400
        for i in range(10):
            s.add_point("sensor.bat", base + i * 3600, 80.0 - i)
        s.add_point("sensor.bat", NOW_TS, 50.0)
        s.aggregate()

        raw = s.get_raw_points("sensor.bat")
        summaries = s.get_daily_summaries("sensor.bat")
        assert all(p[0] >= NOW_TS - 30 * 86400 for p in raw)
        assert len(summaries) > 0

    def test_summary_has_correct_fields(self):
        s = _make_store()
        base = NOW_TS - 40 * 86400
        s.add_point("sensor.bat", base, 90.0)
        s.add_point("sensor.bat", base + 3600, 80.0)
        s.add_point("sensor.bat", NOW_TS, 50.0)
        s.aggregate()

        for summary in s.get_daily_summaries("sensor.bat"):
            assert "date" in summary
            assert "min" in summary
            assert "mean" in summary
            assert "max" in summary
            assert "count" in summary

    def test_ancient_summaries_pruned(self):
        s = _make_store()
        s._data["sensor.bat"] = {
            "raw_points": [[NOW_TS, 50.0]],
            "daily_summaries": [
                {
                    "date": "2023-01-01",
                    "min": 80.0,
                    "mean": 85.0,
                    "max": 90.0,
                    "count": 10,
                }
            ],
            "first_seen": NOW_TS - 400 * 86400,
            "seeded": True,
        }
        s.aggregate()
        assert len(s.get_daily_summaries("sensor.bat")) == 0


# =====================================================================
#  get_all_values / get_history_days / get_median_interval
# =====================================================================


class TestQueryHelpers:
    def test_get_all_values(self):
        s = _make_store()
        s.add_point("sensor.bat", 1000.0, 90.0)
        s.add_point("sensor.bat", 2000.0, 85.0)
        vals = s.get_all_values("sensor.bat")
        assert vals == [90.0, 85.0]

    def test_get_all_values_includes_summaries(self):
        s = _make_store()
        s._data["sensor.bat"] = {
            "raw_points": [[NOW_TS, 50.0]],
            "daily_summaries": [
                {
                    "date": "2025-04-01",
                    "min": 80.0,
                    "mean": 85.0,
                    "max": 90.0,
                    "count": 10,
                }
            ],
            "first_seen": NOW_TS - 60 * 86400,
            "seeded": True,
        }
        vals = s.get_all_values("sensor.bat")
        assert len(vals) == 2
        assert 85.0 in vals
        assert 50.0 in vals

    def test_get_history_days(self):
        s = _make_store()
        ten_days_ago = NOW_TS - 10 * 86400
        s._data["sensor.bat"] = {
            "raw_points": [[ten_days_ago, 90.0], [NOW_TS, 50.0]],
            "daily_summaries": [],
            "first_seen": ten_days_ago,
            "seeded": True,
        }
        days = s.get_history_days("sensor.bat")
        assert 9.5 < days < 10.5

    def test_get_median_interval(self):
        s = _make_store()
        s._data["sensor.bat"] = {
            "raw_points": [
                [1000.0, 90.0],
                [2000.0, 85.0],
                [3000.0, 80.0],
                [4000.0, 75.0],
            ],
            "daily_summaries": [],
            "first_seen": 1000.0,
            "seeded": True,
        }
        assert s.get_median_interval("sensor.bat") == 1000.0

    def test_get_median_interval_too_few(self):
        s = _make_store()
        s._data["sensor.bat"] = {
            "raw_points": [[1000.0, 90.0], [2000.0, 85.0]],
            "daily_summaries": [],
            "first_seen": 1000.0,
            "seeded": True,
        }
        assert s.get_median_interval("sensor.bat") is None


# =====================================================================
#  Category persistence
# =====================================================================


class TestCategoryPersistence:
    def test_set_and_get_category(self):
        s = _make_store()
        s.set_category("sensor.bat", "linear")
        assert s.get_category("sensor.bat") == "linear"

    def test_get_category_nonexistent(self):
        s = _make_store()
        assert s.get_category("sensor.nope") is None

    def test_last_classified_set(self):
        s = _make_store()
        s.set_category("sensor.bat", "linear")
        lc = s.get_last_classified("sensor.bat")
        assert lc is not None
        assert abs(lc - NOW_TS) < 5
