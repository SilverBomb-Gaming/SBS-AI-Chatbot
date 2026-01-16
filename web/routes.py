"""Public web routes for the SBS AI Chatbot."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from flask import Blueprint, current_app, g, render_template, request

from core.triage import analyze_ticket
from services import brain, episodes
from services.audit import AUDIT_LOG
from services.auth import attach_roles
from services.decorators import (
    json_endpoint,
    rate_limit,
    require_api_key,
    require_feature,
    require_role,
)
from services.persistence import STORE, TicketRecord

bp = Blueprint("main", __name__)


@bp.before_app_request
def _enforce_limits() -> None:
    max_size = current_app.config.get("REQUEST_SIZE_LIMIT")
    if max_size and request.content_length and request.content_length > max_size:
        return ("Request too large", 413)


def _hydrate_roles() -> None:
    api_key = request.headers.get("X-API-Key")
    g.current_roles = attach_roles(api_key)


@bp.before_app_request
def _before_request():
    _hydrate_roles()


def _episode_actor() -> str:
    api_key = getattr(g, "current_api_key", None)
    if not api_key:
        return "api_key"
    prefix = api_key.strip()[:4]
    return f"key:{prefix}" if prefix else "api_key"


def _parse_limit(value: str | None) -> int:
    if not value:
        return 50
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("limit must be an integer") from exc
    if parsed < 1:
        raise ValueError("limit must be >= 1")
    return min(parsed, 200)


def _parse_offset(value: str | None) -> int:
    if not value:
        return 0
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("offset must be an integer") from exc
    if parsed < 0:
        raise ValueError("offset must be >= 0")
    return parsed


def _episode_filters() -> Dict[str, str]:
    filters: Dict[str, str] = {}
    for field in ("project", "status", "mode"):
        value = request.args.get(field)
        if value:
            filters[field] = value
    return filters


@bp.get("/")
def index():
    return render_template(
        "index.html", tier=current_app.config.get("APP_TIER", "public")
    )


@bp.get("/tickets")
def tickets_page():
    records = STORE.all()
    return render_template("tickets.html", records=records)


@bp.get("/admin/rules")
def admin_rules():
    return render_template("admin_rules.html")


@bp.get("/admin/status")
def admin_status():
    return render_template("admin_status.html")


@bp.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@bp.post("/api/triage")
@rate_limit(limit=10, window_seconds=60)
@json_endpoint
def api_triage() -> Dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    if not title:
        raise ValueError("Title is required")
    if not description:
        raise ValueError("Description is required")

    result = analyze_ticket(title, description)
    record = TicketRecord(
        title=title,
        description=description,
        triage=result.as_dict(),
        created_at=datetime.now(timezone.utc),
    )
    STORE.add(record)
    return {"triage": result.as_dict()}


@bp.post("/api/episodes")
@require_feature("FEATURE_EPISODES")
@require_api_key
@json_endpoint
def create_episode() -> tuple[Dict[str, Any], int]:
    payload = request.get_json(silent=True) or {}
    database_url = current_app.config["DATABASE_URL"]
    created_by = _episode_actor()
    episode_id = episodes.create_episode(database_url, payload, created_by)
    return {"ok": True, "episode_id": episode_id}, 201


@bp.get("/api/episodes")
@require_feature("FEATURE_EPISODES")
@require_api_key
@json_endpoint
def list_episodes() -> Dict[str, Any]:
    database_url = current_app.config["DATABASE_URL"]
    limit = _parse_limit(request.args.get("limit"))
    offset = _parse_offset(request.args.get("offset"))
    filters = _episode_filters()
    records = episodes.list_episodes(
        database_url, limit=limit, offset=offset, filters=filters or None
    )
    return {"episodes": records, "limit": limit, "offset": offset}


@bp.get("/api/episodes/<int:episode_id>")
@require_feature("FEATURE_EPISODES")
@require_api_key
@json_endpoint
def get_episode(episode_id: int) -> tuple[Dict[str, Any], int] | Dict[str, Any]:
    database_url = current_app.config["DATABASE_URL"]
    record = episodes.get_episode(database_url, episode_id)
    if not record:
        return {"error": "Episode not found"}, 404
    return {"episode": record}


@bp.post("/admin/brain/rollback/<int:version_id>")
@require_role("admin")
@json_endpoint
def brain_rollback(version_id: int) -> Dict[str, Any]:
    database_url = current_app.config["DATABASE_URL"]
    version = brain.rollback_to_version(database_url, version_id)
    actor = request.headers.get("X-API-Key", "system")
    AUDIT_LOG.record(event=f"Rollback to brain version {version_id}", actor=actor)
    return {"active_version_id": version["id"], "status": "ok"}
