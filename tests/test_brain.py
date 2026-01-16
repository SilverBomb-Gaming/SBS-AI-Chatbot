import json

from app import create_app
from services import brain, persistence


def _make_app_with_db(monkeypatch, tmp_path):
    db_path = tmp_path / "brain.sqlite"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    app = create_app()
    return app, url


def _insert_version(database_url, template_blob: str, status: str = "approved") -> int:
    conn = persistence.get_connection(database_url)
    payload = json.loads(template_blob)
    payload["rules"][0]["keyword"] = f"kw-{status}"
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
        ("2026-01-15T00:00:00Z", "tester", 1, status, "test", json.dumps(payload), 0.9, "manual"),
    )
    conn.commit()
    return cursor.lastrowid


def test_initial_brain_seeded(monkeypatch, tmp_path):
    _, db_url = _make_app_with_db(monkeypatch, tmp_path)
    version = brain.fetch_active_version(db_url)
    assert version is not None
    assert version["status"] == "approved"


def test_active_rules_match_defaults(monkeypatch, tmp_path):
    _, db_url = _make_app_with_db(monkeypatch, tmp_path)
    rules = brain.load_active_rules(db_url)
    assert isinstance(rules, list)
    assert len(rules) >= 1


def test_rollback_endpoint_switches_active_version(monkeypatch, tmp_path):
    app, db_url = _make_app_with_db(monkeypatch, tmp_path)
    active = brain.fetch_active_version(db_url)
    new_version_id = _insert_version(db_url, active["brain_blob"], status="approved")

    client = app.test_client()
    response = client.post(f"/admin/brain/rollback/{new_version_id}", headers={"X-API-Key": "alpha-admin"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["active_version_id"] == new_version_id

    active_after = brain.fetch_active_version(db_url)
    assert active_after["id"] == new_version_id


def test_rollback_rejects_invalid_version(monkeypatch, tmp_path):
    app, db_url = _make_app_with_db(monkeypatch, tmp_path)
    active = brain.fetch_active_version(db_url)
    pending_version = _insert_version(db_url, active["brain_blob"], status="proposed")

    client = app.test_client()
    missing = client.post("/admin/brain/rollback/9999", headers={"X-API-Key": "alpha-admin"})
    assert missing.status_code == 400

    rejected = client.post(f"/admin/brain/rollback/{pending_version}", headers={"X-API-Key": "alpha-admin"})
    assert rejected.status_code == 400
    assert "approved" in rejected.get_json()["error"].lower()
