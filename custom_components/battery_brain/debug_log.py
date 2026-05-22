"""Developer debug logger for BatteryBrain.

Writes a JSONL file (one JSON object per line) to the HA config directory.
Each line is self-contained so the file can be streamed, tailed, or sent
for remote analysis without needing the full context.

Activate by enabling developer mode in the integration config flow.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .const import LOGGER

MAX_LOG_SIZE = 50 * 1024 * 1024  # 50 MB — rotate after this


class DebugLogger:
    """Append-only JSONL debug log for developer diagnostics."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._buffer: list[dict[str, Any]] = []
        self._seq = 0

    @property
    def path(self) -> str:
        return self._path

    def log(self, entry: dict[str, Any]) -> None:
        """Buffer a log entry (no I/O — safe from event-loop callbacks)."""
        self._seq += 1
        entry["seq"] = self._seq
        self._buffer.append(entry)

    def _flush_sync(self) -> None:
        """Write buffered entries to disk (blocking — call from executor)."""
        if not self._buffer:
            return

        try:
            if (
                os.path.exists(self._path)
                and os.path.getsize(self._path) > MAX_LOG_SIZE
            ):
                rotated = self._path + ".old"
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.rename(self._path, rotated)
        except OSError:
            pass

        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                for entry in self._buffer:
                    json.dump(entry, fh, separators=(", ", ": "), default=str)
                    fh.write("\n")
            self._buffer.clear()
        except OSError:
            LOGGER.warning("Could not write debug log to %s", self._path)

    async def async_flush(self, hass: Any) -> None:
        """Non-blocking flush via executor."""
        if not self._buffer:
            return
        await hass.async_add_executor_job(self._flush_sync)
