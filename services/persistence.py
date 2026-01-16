"""Persistence layer abstractions."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List


@dataclass
class TicketRecord:
    title: str
    description: str
    triage: Dict[str, object]
    created_at: datetime


class InMemoryStore:
    """Placeholder store used until SQLite wiring lands."""

    def __init__(self) -> None:
        self._records: List[TicketRecord] = []

    def add(self, record: TicketRecord) -> None:
        self._records.append(record)

    def all(self) -> List[TicketRecord]:
        return list(self._records)


STORE = InMemoryStore()

_CONNECTION_CACHE: Dict[str, sqlite3.Connection] = {}


def _sqlite_path(database_url: str) -> str:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Only sqlite:/// URLs are supported")
    path = database_url[len(prefix) :]
    if path == ":memory":
        return ":memory:"
    return path


def get_connection(database_url: str) -> sqlite3.Connection:
    """Return a cached sqlite3 connection for the provided URL."""

    if database_url not in _CONNECTION_CACHE:
        path = _sqlite_path(database_url)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _CONNECTION_CACHE[database_url] = conn
    return _CONNECTION_CACHE[database_url]


def init_storage(database_url: str) -> None:
    """Ensure required tables exist."""

    conn = get_connection(database_url)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS brain_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            parent_id INTEGER,
            status TEXT NOT NULL,
            notes TEXT,
            brain_blob TEXT NOT NULL,
            health_score REAL,
            eval_report TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS brain_active (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_version_id INTEGER NOT NULL
        )
        """
    )
    conn.commit()
