"""Episode ingestion and query helpers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import persistence

ALLOWED_MODES = {"freestyle", "instructed", "breaker"}
ALLOWED_STATUS = {"pass", "fail", "error"}
MAX_SUMMARY_LENGTH = 2000
MAX_JSON_LENGTH = 8000
MAX_SOURCE_LENGTH = 64
MAX_TEXT_LENGTH = 255


def _require_payload(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object")
    return payload


def _require_string(
    payload: Dict[str, Any],
    field: str,
    *,
    allowed: set[str] | None = None,
    max_length: int = MAX_TEXT_LENGTH,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} is required")
    if len(value) > max_length:
        raise ValueError(f"{field} is too long")
    if allowed and value not in allowed:
        raise ValueError(f"Invalid {field}: {value}")
    return value


def _optional_string(
    payload: Dict[str, Any], field: str, *, max_length: int = MAX_TEXT_LENGTH
) -> Optional[str]:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if not value:
        return None
    if len(value) > max_length:
        raise ValueError(f"{field} is too long")
    return value


def _optional_int(payload: Dict[str, Any], field: str) -> Optional[int]:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def _serialize_json_field(name: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        serialized = json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON serializable") from exc
    if len(serialized) > MAX_JSON_LENGTH:
        raise ValueError(f"{name} payload is too large")
    return serialized


def _prepare_labels(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        normalized: List[str] = []
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError("labels list must contain strings")
            entry = raw.strip()
            if entry:
                normalized.append(entry)
        return normalized
    raise ValueError("labels must be a list or object")


def _prepare_artifacts(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    raise ValueError("artifacts must be a list or object")


def validate_episode_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = _require_payload(payload)
    cleaned: Dict[str, Any] = {}
    cleaned["source"] = _require_string(
        data, "source", max_length=MAX_SOURCE_LENGTH
    )
    cleaned["mode"] = _require_string(data, "mode", allowed=ALLOWED_MODES)
    cleaned["status"] = _require_string(data, "status", allowed=ALLOWED_STATUS)
    cleaned["project"] = _optional_string(data, "project")
    cleaned["build_id"] = _optional_string(data, "build_id")
    cleaned["seed"] = _optional_int(data, "seed")
    cleaned["summary"] = _optional_string(
        data, "summary", max_length=MAX_SUMMARY_LENGTH
    )

    metrics = data.get("metrics")
    if metrics is not None and not isinstance(metrics, dict):
        raise ValueError("metrics must be an object")
    cleaned["metrics_json"] = _serialize_json_field("metrics", metrics)

    artifacts = _prepare_artifacts(data.get("artifacts"))
    cleaned["artifacts_json"] = _serialize_json_field("artifacts", artifacts)

    labels = _prepare_labels(data.get("labels"))
    cleaned["labels_json"] = _serialize_json_field("labels", labels)

    return cleaned


def create_episode(database_url: str, payload: Dict[str, Any], created_by: str) -> int:
    cleaned = validate_episode_payload(payload)
    cleaned["created_at"] = datetime.now(timezone.utc).isoformat()
    cleaned["created_by"] = created_by

    conn = persistence.get_connection(database_url)
    cursor = conn.execute(
        """
        INSERT INTO episodes (
            created_at,
            created_by,
            source,
            mode,
            project,
            build_id,
            seed,
            status,
            summary,
            metrics_json,
            artifacts_json,
            labels_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cleaned["created_at"],
            cleaned["created_by"],
            cleaned["source"],
            cleaned["mode"],
            cleaned["project"],
            cleaned["build_id"],
            cleaned["seed"],
            cleaned["status"],
            cleaned["summary"],
            cleaned["metrics_json"],
            cleaned["artifacts_json"],
            cleaned["labels_json"],
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def _coerce_filters(filters: Dict[str, str] | None) -> Dict[str, str]:
    if not filters:
        return {}
    coerced: Dict[str, str] = {}
    for key, value in filters.items():
        if value is None:
            continue
        trimmed = value.strip()
        if not trimmed:
            continue
        if key == "status" and trimmed not in ALLOWED_STATUS:
            raise ValueError("Invalid status filter")
        if key == "mode" and trimmed not in ALLOWED_MODES:
            raise ValueError("Invalid mode filter")
        coerced[key] = trimmed
    return coerced


def _deserialize_json(blob: Optional[str]) -> Any:
    if not blob:
        return None
    return json.loads(blob)


def _row_to_episode(row: Any) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "created_by": row["created_by"],
        "source": row["source"],
        "mode": row["mode"],
        "project": row["project"],
        "build_id": row["build_id"],
        "seed": row["seed"],
        "status": row["status"],
        "summary": row["summary"],
        "metrics": _deserialize_json(row["metrics_json"]),
        "artifacts": _deserialize_json(row["artifacts_json"]),
        "labels": _deserialize_json(row["labels_json"]),
    }


def list_episodes(
    database_url: str,
    *,
    limit: int = 50,
    offset: int = 0,
    filters: Dict[str, str] | None = None,
) -> List[Dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    limit = min(limit, 200)
    if offset < 0:
        raise ValueError("offset must be >= 0")

    coerced_filters = _coerce_filters(filters)
    conditions: List[str] = []
    params: List[Any] = []
    for key, column in ("status", "status"), ("mode", "mode"), ("project", "project"):
        value = coerced_filters.get(key)
        if value:
            conditions.append(f"{column} = ?")
            params.append(value)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = persistence.get_connection(database_url)
    query = (
        "SELECT id, created_at, created_by, source, mode, project, build_id, seed, "
        "status, summary, metrics_json, artifacts_json, labels_json "
        "FROM episodes"
        f"{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    return [_row_to_episode(row) for row in rows]


def get_episode(database_url: str, episode_id: int) -> Optional[Dict[str, Any]]:
    conn = persistence.get_connection(database_url)
    row = conn.execute(
        """
        SELECT id, created_at, created_by, source, mode, project, build_id, seed,
               status, summary, metrics_json, artifacts_json, labels_json
        FROM episodes
        WHERE id = ?
        """,
        (episode_id,),
    ).fetchone()
    if not row:
        return None
    return _row_to_episode(row)
