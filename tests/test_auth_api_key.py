import pytest
from flask import Flask

from services.decorators import require_api_key


@pytest.fixture()
def auth_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["X_API_KEYS"] = {"alpha", "beta"}

    @app.get("/protected")
    @require_api_key
    def protected():
        return "ok"

    @app.get("/api/protected")
    @require_api_key
    def api_protected():
        return {"ok": True}

    return app


def test_missing_key_returns_401(auth_app):
    client = auth_app.test_client()
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "ApiKey"


def test_invalid_key_returns_401(auth_app):
    client = auth_app.test_client()
    response = client.get("/protected", headers={"X-API-Key": "nope"})
    assert response.status_code == 401


def test_valid_key_returns_200(auth_app):
    client = auth_app.test_client()
    response = client.get("/protected", headers={"X-API-Key": "alpha"})
    assert response.status_code == 200
    assert response.data == b"ok"


def test_fail_closed_when_keys_missing(auth_app):
    auth_app.config.pop("X_API_KEYS", None)
    response = auth_app.test_client().get("/protected", headers={"X-API-Key": "alpha"})
    assert response.status_code == 401


def test_json_error_payload(auth_app):
    client = auth_app.test_client()
    response = client.get("/api/protected")
    assert response.status_code == 401
    assert response.is_json
    assert response.get_json()["error"] == "Unauthorized"
