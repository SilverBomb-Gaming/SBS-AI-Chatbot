"""Public web routes for the SBS AI Chatbot."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from flask import Blueprint, current_app, g, render_template, request

from core.triage import analyze_ticket
from services import brain
from services.audit import AUDIT_LOG
from services.auth import attach_roles
from services.decorators import json_endpoint, rate_limit, require_role
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


@bp.post("/admin/brain/rollback/<int:version_id>")
@require_role("admin")
@json_endpoint
def brain_rollback(version_id: int) -> Dict[str, Any]:
    database_url = current_app.config["DATABASE_URL"]
    version = brain.rollback_to_version(database_url, version_id)
    actor = request.headers.get("X-API-Key", "system")
    AUDIT_LOG.record(event=f"Rollback to brain version {version_id}", actor=actor)
    return {"active_version_id": version["id"], "status": "ok"}
