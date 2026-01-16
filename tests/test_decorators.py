import pytest
from flask import Flask, g, request

from services import decorators
from services.decorators import json_endpoint, rate_limit, require_api_key, require_role


@pytest.fixture()
def app_client():
    decorators._rate_limiter.reset()
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["API_KEYS"] = ["alpha", "beta-admin"]
    app.config["X_API_KEYS"] = {"alpha", "beta-admin"}

    @app.before_request
    def attach_roles():
        roles = request.headers.get("X-Test-Roles")
        g.current_roles = roles.split(",") if roles else []

    @app.route("/json")
    @json_endpoint
    def json_view():
        return {"status": "ok"}

    @app.route("/json-error")
    @json_endpoint
    def json_error():
        raise ValueError("bad input")

    @app.route("/limited")
    @rate_limit(limit=1, window_seconds=60)
    @json_endpoint
    def limited():
        return {"message": "allowed"}

    @app.route("/secure")
    @require_api_key
    @json_endpoint
    def secure():
        return {"secure": True}

    @app.route("/admin")
    @require_role("admin")
    @json_endpoint
    def admin_route():
        return {"admin": True}

    return app.test_client()


def test_json_endpoint_success(app_client):
    response = app_client.get("/json")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_json_endpoint_handles_value_error(app_client):
    response = app_client.get("/json-error")
    assert response.status_code == 400
    assert response.get_json()["error"] == "bad input"


def test_rate_limit_blocks_second_request(app_client):
    first = app_client.get("/limited")
    assert first.status_code == 200
    second = app_client.get("/limited")
    assert second.status_code == 429


def test_require_api_key_allows_known_key(app_client):
    response = app_client.get("/secure", headers={"X-API-Key": "alpha"})
    assert response.status_code == 200


def test_require_api_key_rejects_unknown_key(app_client):
    response = app_client.get("/secure")
    assert response.status_code == 401


def test_require_role_enforces_admin(app_client):
    denied = app_client.get("/admin")
    assert denied.status_code == 403
    allowed = app_client.get("/admin", headers={"X-Test-Roles": "admin"})
    assert allowed.status_code == 200
