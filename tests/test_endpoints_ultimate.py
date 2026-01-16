import pytest

from app import create_app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("APP_TIER", "ultimate")
    test_app = create_app()
    return test_app.test_client()


def test_admin_pages_placeholder(client):
    assert client.get("/admin/rules").status_code == 200
    assert client.get("/admin/status").status_code == 200
