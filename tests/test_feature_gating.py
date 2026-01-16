import pytest
from flask import Flask

from services.decorators import require_feature


@pytest.fixture()
def gated_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["FEATURE_FLAGS"] = {"FEATURE_EXPORT": False}
    app.config["FEATURE_EXPORT"] = False

    @app.get("/feature-demo")
    @require_feature("FEATURE_EXPORT")
    def feature_demo():
        return "export ready"

    @app.get("/api/feature-demo")
    @require_feature("FEATURE_EXPORT")
    def api_feature_demo():
        return {"ok": True}

    return app


def test_feature_off_returns_404(gated_app):
    client = gated_app.test_client()
    response = client.get("/feature-demo")
    assert response.status_code == 404


def test_feature_on_allows_access(gated_app):
    gated_app.config["FEATURE_FLAGS"]["FEATURE_EXPORT"] = True
    gated_app.config["FEATURE_EXPORT"] = True
    response = gated_app.test_client().get("/feature-demo")
    assert response.status_code == 200
    assert b"export ready" in response.data


def test_fail_closed_when_flag_missing(gated_app):
    gated_app.config.pop("FEATURE_FLAGS", None)
    gated_app.config.pop("FEATURE_EXPORT", None)
    response = gated_app.test_client().get("/feature-demo")
    assert response.status_code == 404


def test_json_vs_html_behavior(gated_app):
    client = gated_app.test_client()
    html_response = client.get("/feature-demo")
    assert html_response.status_code == 404
    assert not html_response.is_json

    json_response = client.get(
        "/api/feature-demo", headers={"Accept": "application/json"}
    )
    assert json_response.status_code == 404
    assert json_response.is_json
    assert json_response.get_json()["error"] in {"Resource not found", "Forbidden"}
