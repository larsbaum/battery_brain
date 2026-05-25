"""Always-on production logger for BatteryBrain.

Writes daily JSONL files to hass.config.path("battery_brain/logs/").
Naming: YYYY-MM-DD_batterybrain_logging.jsonl
Retention: 30 days.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from .const import LOGGER

LOG_RETENTION_DAYS = 30
LOG_DIR = os.path.join("battery_brain", "logs")


class ProductionLogger:
    """Append-only JSONL logger with daily rotation and 30-day retention."""

    def __init__(self, base_dir: str) -> None:
        self._base_dir = base_dir
        self._buffer: list[dict[str, Any]] = []
        self._seq = 0
        self._last_cleanup_date: str | None = None

    def log(self, entry: dict[str, Any]) -> None:
        """Buffer a log entry (no I/O -- safe from event-loop)."""
        self._seq += 1
        entry["seq"] = self._seq
        self._buffer.append(entry)

    def _current_date_str(self) -> str:
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    def _log_path_for_date(self, date_str: str) -> str:
        return os.path.join(
            self._base_dir,
            f"{date_str}_batterybrain_logging.jsonl",
        )

    def _flush_sync(self) -> None:
        """Write buffered entries and run daily cleanup (blocking)."""
        self._maybe_cleanup_sync()

        if not self._buffer:
            return

        today = self._current_date_str()
        path = self._log_path_for_date(today)

        try:
            os.makedirs(self._base_dir, exist_ok=True)
        except OSError:
            LOGGER.warning("Could not create log directory %s", self._base_dir)
            return

        try:
            with open(path, "a", encoding="utf-8") as fh:
                for entry in self._buffer:
                    json.dump(entry, fh, separators=(", ", ": "), default=str)
                    fh.write("\n")
            self._buffer.clear()
        except OSError:
            LOGGER.warning("Could not write production log to %s", path)

    def _maybe_cleanup_sync(self) -> None:
        """Delete log files older than 30 days (at most once per day)."""
        today = self._current_date_str()
        if self._last_cleanup_date == today:
            return
        self._last_cleanup_date = today

        try:
            if not os.path.isdir(self._base_dir):
                return
            now = datetime.now(tz=timezone.utc)
            for filename in os.listdir(self._base_dir):
                if not filename.endswith("_batterybrain_logging.jsonl"):
                    continue
                date_part = filename[:10]
                try:
                    file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    continue
                if (now - file_date).days > LOG_RETENTION_DAYS:
                    os.remove(os.path.join(self._base_dir, filename))
                    LOGGER.debug("Removed old log file: %s", filename)
        except OSError:
            LOGGER.warning("Error during log cleanup in %s", self._base_dir)

    async def async_flush(self, hass: Any) -> None:
        """Non-blocking flush via executor."""
        await hass.async_add_executor_job(self._flush_sync)
