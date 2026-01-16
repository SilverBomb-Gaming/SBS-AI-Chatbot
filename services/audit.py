"""Audit log utilities (stub for bootstrap)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List


@dataclass
class AuditEntry:
    event: str
    actor: str
    created_at: datetime


class InMemoryAuditLog:
    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    def record(self, event: str, actor: str = "system") -> None:
        self._entries.append(
            AuditEntry(event=event, actor=actor, created_at=datetime.now(timezone.utc))
        )

    def latest(self, limit: int = 20) -> List[AuditEntry]:
        return self._entries[-limit:]


AUDIT_LOG = InMemoryAuditLog()
