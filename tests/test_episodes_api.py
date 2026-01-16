import pytest

from app import create_app


@pytest.fixture()
def paid_app(monkeypatch, tmp_path):
    db_path = tmp_path / "episodes.sqlite"
    monkeypatch.setenv("APP_TIER", "paid")
    monkeypatch.setenv("X_API_KEYS", "alpha,bravo")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    app = create_app()
    app.config["TESTING"] = True
    yield app


@pytest.fixture()
def client(paid_app):
    return paid_app.test_client()


@pytest.fixture()
def public_app(monkeypatch, tmp_path):
    db_path = tmp_path / "episodes_public.sqlite"
    monkeypatch.setenv("APP_TIER", "public")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    app = create_app()
    app.config["TESTING"] = True
    yield app


def _valid_payload(**overrides):
    payload = {
        "source": "unity-runner",
        "mode": "freestyle",
        "status": "pass",
        "project": "Babylon",
        "build_id": "build-123",
        "seed": 42,
        "summary": "All systems green.",
        "metrics": {"steps": 120, "fps": 59.9},
        "artifacts": ["logs/run.log"],
        "labels": ["smoke", "nightly"],
    }
    payload.update(overrides)
    return payload


def test_feature_off_returns_404(public_app):
    response = public_app.test_client().post(
        "/api/episodes", json=_valid_payload(), headers={"X-API-Key": "alpha"}
    )
    assert response.status_code == 404


def test_auth_required_for_episodes(client):
    response = client.post("/api/episodes", json=_valid_payload())
    assert response.status_code == 401

    bad = client.post(
        "/api/episodes",
        json=_valid_payload(),
        headers={"X-API-Key": "invalid"},
    )
    assert bad.status_code == 401


def test_happy_path_create_and_list(client):
    response = client.post(
        "/api/episodes",
        json=_valid_payload(),
        headers={"X-API-Key": "alpha"},
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["ok"] is True
    episode_id = data["episode_id"]

    list_response = client.get(
        "/api/episodes",
        headers={"X-API-Key": "alpha"},
    )
    assert list_response.status_code == 200
    listing = list_response.get_json()
    assert listing["episodes"][0]["id"] == episode_id

    detail = client.get(
        f"/api/episodes/{episode_id}",
        headers={"X-API-Key": "alpha"},
    )
    assert detail.status_code == 200
    detail_json = detail.get_json()
    assert detail_json["episode"]["source"] == "unity-runner"


def test_validation_errors(client):
    bad_mode = client.post(
        "/api/episodes",
        json=_valid_payload(mode="unknown"),
        headers={"X-API-Key": "alpha"},
    )
    assert bad_mode.status_code == 400

    bad_status = client.post(
        "/api/episodes",
        json=_valid_payload(status="meh"),
        headers={"X-API-Key": "alpha"},
    )
    assert bad_status.status_code == 400

    bad_metrics = client.post(
        "/api/episodes",
        json=_valid_payload(metrics=[1, 2, 3]),
        headers={"X-API-Key": "alpha"},
    )
    assert bad_metrics.status_code == 400

    long_summary = "A" * 4000
    response = client.post(
        "/api/episodes",
        json=_valid_payload(summary=long_summary),
        headers={"X-API-Key": "alpha"},
    )
    assert response.status_code == 400


def test_filters_require_valid_values(client):
    client.post(
        "/api/episodes",
        json=_valid_payload(),
        headers={"X-API-Key": "alpha"},
    )
    response = client.get(
        "/api/episodes?status=bad",
        headers={"X-API-Key": "alpha"},
    )
    assert response.status_code == 400

    response = client.get(
        "/api/episodes?mode=bad",
        headers={"X-API-Key": "alpha"},
    )
    assert response.status_code == 400


def test_limit_offset_validation(client):
    response = client.get(
        "/api/episodes?limit=-1",
        headers={"X-API-Key": "alpha"},
    )
    assert response.status_code == 400

    response = client.get(
        "/api/episodes?offset=-10",
        headers={"X-API-Key": "alpha"},
    )
    assert response.status_code == 400
