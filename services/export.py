"""Export helpers (CSV, etc.)."""
from __future__ import annotations

from io import StringIO
from typing import Iterable

from .persistence import TicketRecord


def to_csv(records: Iterable[TicketRecord]) -> str:
    buffer = StringIO()
    buffer.write("title,description,category,priority,confidence,created_at\n")
    for record in records:
        triage = record.triage
        buffer.write(
            f"{record.title},{record.description},{triage.get('category')},{triage.get('priority')},{triage.get('confidence')},{record.created_at.isoformat()}\n"
        )
    return buffer.getvalue()
