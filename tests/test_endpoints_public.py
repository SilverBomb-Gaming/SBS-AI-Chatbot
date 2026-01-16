import os

import pytest

from app import create_app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("APP_TIER", "public")
    test_app = create_app()
    return test_app.test_client()


def test_index_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_triage_endpoint_returns_json(client):
    response = client.post(
        "/api/triage",
        json={"title": "Billing outage", "description": "Users see billing outage"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "triage" in data
    assert data["triage"]["category"]


def test_triage_validation_errors(client):
    response = client.post("/api/triage", json={"title": "", "description": ""})
    assert response.status_code == 400
    assert response.get_json()["error"]
