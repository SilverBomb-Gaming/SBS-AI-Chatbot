"""Event logging helpers for Unity human-observed runs."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


class EventLogger:
    """Thread-safe logger that writes run events for reporting."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.write_text("# Unity Runner Events\n", encoding="utf-8")
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = {}

    def log(self, event_type: str, message: str | None = None) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"{timestamp}\t{event_type}\t{message or ''}\n"
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            self._counts[event_type] = self._counts.get(event_type, 0) + 1

    def count(self, event_type: str) -> int:
        return self._counts.get(event_type, 0)

    def counts(self) -> Dict[str, int]:
        return dict(self._counts)
