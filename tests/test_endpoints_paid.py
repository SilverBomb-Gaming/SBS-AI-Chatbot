import pytest

from app import create_app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("APP_TIER", "paid")
    test_app = create_app()
    return test_app.test_client()


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_tickets_placeholder(client):
    response = client.get("/tickets")
    assert response.status_code == 200
