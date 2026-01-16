"""Brain version helpers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Iterable, List

from services import persistence


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_rules(rules: Iterable[Dict[str, object]]) -> str:
    payload = {"rules": list(rules)}
    return json.dumps(payload, separators=(",", ":"))


def ensure_brain_initialized(
    database_url: str, default_rules: Iterable[Dict[str, object]]
) -> None:
    """Insert the baseline brain when none exists."""

    conn = persistence.get_connection(database_url)
    existing = conn.execute(
        "SELECT id FROM brain_versions ORDER BY id LIMIT 1"
    ).fetchone()
    if existing:
        active = conn.execute(
            "SELECT active_version_id FROM brain_active WHERE id = 1"
        ).fetchone()
        if not active:
            conn.execute(
                "INSERT OR REPLACE INTO brain_active (id, active_version_id) VALUES (1, ?)",
                (existing["id"],),
            )
            conn.commit()
        return

    blob = _serialize_rules(default_rules)
    cursor = conn.execute(
        """
        INSERT INTO brain_versions (
            created_at,
            created_by,
            parent_id,
            status,
            notes,
            brain_blob,
            health_score,
            eval_report
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _now_iso(),
            "system",
            None,
            "approved",
            "Initial brain",
            blob,
            1.0,
            "Baseline",
        ),
    )
    version_id = cursor.lastrowid
    conn.execute(
        "INSERT OR REPLACE INTO brain_active (id, active_version_id) VALUES (1, ?)",
        (version_id,),
    )
    conn.commit()


def fetch_active_version(database_url: str) -> Dict[str, object] | None:
    conn = persistence.get_connection(database_url)
    row = conn.execute(
        """
        SELECT v.id, v.created_at, v.created_by, v.status, v.brain_blob, v.health_score, v.eval_report
        FROM brain_active a
        JOIN brain_versions v ON v.id = a.active_version_id
        WHERE a.id = 1
        """
    ).fetchone()
    return dict(row) if row else None


def load_active_rules(database_url: str) -> List[Dict[str, object]]:
    version = fetch_active_version(database_url)
    if not version:
        return []
    blob = json.loads(version.get("brain_blob") or "{}")
    rules = blob.get("rules")
    if not isinstance(rules, list):
        return []
    return rules


def get_version(database_url: str, version_id: int) -> Dict[str, object] | None:
    conn = persistence.get_connection(database_url)
    row = conn.execute(
        "SELECT id, status, brain_blob, created_at, created_by, parent_id FROM brain_versions WHERE id = ?",
        (version_id,),
    ).fetchone()
    return dict(row) if row else None


def rollback_to_version(database_url: str, version_id: int) -> Dict[str, object]:
    version = get_version(database_url, version_id)
    if not version:
        raise ValueError("Brain version does not exist")
    if version.get("status") != "approved":
        raise ValueError("Only approved versions can be activated")
    conn = persistence.get_connection(database_url)
    conn.execute(
        "INSERT OR REPLACE INTO brain_active (id, active_version_id) VALUES (1, ?)",
        (version_id,),
    )
    conn.commit()
    return version
