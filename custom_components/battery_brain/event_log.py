"""JSONL event logs for BatteryBrain.

Both logs buffer entries in memory (safe from event-loop callbacks) and
write them from the executor. One JSON object per line, so files can be
streamed, tailed or attached to bug reports.

- ProductionLog — always on: daily files in ``battery_brain/logs/``
  (``YYYY-MM-DD_batterybrain_logging.jsonl``), kept for 30 days.
- DebugLog — developer mode only: ``battery_brain_debug.jsonl`` with more
  detail, rotated to ``.old`` at 50 MB.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant

from .const import LOGGER

PRODUCTION_LOG_DIR = os.path.join("battery_brain", "logs")
PRODUCTION_LOG_SUFFIX = "_batterybrain_logging.jsonl"
PRODUCTION_LOG_RETENTION_DAYS = 30
DEBUG_LOG_FILE = "battery_brain_debug.jsonl"
DEBUG_LOG_MAX_BYTES = 50 * 1024 * 1024


class _JsonlLog:
    """Buffered append-only JSONL writer."""

    def __init__(self) -> None:
        self._buffer: list[dict[str, Any]] = []
        self._seq = 0

    def log(self, entry: dict[str, Any]) -> None:
        """Buffer an entry (no I/O)."""
        self._seq += 1
        entry["seq"] = self._seq
        self._buffer.append(entry)

    async def async_flush(self, hass: HomeAssistant) -> None:
        """Write buffered entries from the executor.

        The buffer is swapped here, in the event loop: entries logged while
        the executor writes go into the new buffer instead of being cleared
        together with the written ones.
        """
        if not self._buffer:
            return
        entries, self._buffer = self._buffer, []
        if not await hass.async_add_executor_job(self._write, entries):
            self._buffer[:0] = entries  # keep them for the next attempt

    def _target_path(self) -> str | None:
        """Path to append to; prepares the target (rotation, cleanup)."""
        raise NotImplementedError

    def _write(self, entries: list[dict[str, Any]]) -> bool:
        """Append *entries*; False if the file couldn't be written."""
        path = self._target_path()
        if path is None:
            return True
        try:
            with open(path, "a", encoding="utf-8") as fh:
                for entry in entries:
                    json.dump(entry, fh, separators=(", ", ": "), default=str)
                    fh.write("\n")
        except OSError:
            LOGGER.warning("Could not write log file %s", path)
            return False
        return True


class ProductionLog(_JsonlLog):
    """Daily log files with 30-day retention."""

    def __init__(self, base_dir: str) -> None:
        super().__init__()
        self._base_dir = base_dir
        self._last_cleanup_date: str | None = None

    def _target_path(self) -> str | None:
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        try:
            os.makedirs(self._base_dir, exist_ok=True)
        except OSError:
            LOGGER.warning("Could not create log directory %s", self._base_dir)
            return None
        if self._last_cleanup_date != today:
            self._last_cleanup_date = today
            self._remove_old_files()
        return os.path.join(self._base_dir, f"{today}{PRODUCTION_LOG_SUFFIX}")

    def _remove_old_files(self) -> None:
        now = datetime.now(tz=timezone.utc)
        try:
            for filename in os.listdir(self._base_dir):
                if not filename.endswith(PRODUCTION_LOG_SUFFIX):
                    continue
                try:
                    file_date = datetime.strptime(
                        filename[:10], "%Y-%m-%d"
                    ).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if (now - file_date).days > PRODUCTION_LOG_RETENTION_DAYS:
                    os.remove(os.path.join(self._base_dir, filename))
                    LOGGER.debug("Removed old log file: %s", filename)
        except OSError:
            LOGGER.warning("Error during log cleanup in %s", self._base_dir)


class DebugLog(_JsonlLog):
    """Single verbose log file, rotated when it gets too large."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path

    def _target_path(self) -> str | None:
        try:
            if (
                os.path.exists(self.path)
                and os.path.getsize(self.path) > DEBUG_LOG_MAX_BYTES
            ):
                os.replace(self.path, self.path + ".old")
        except OSError:
            pass
        return self.path
