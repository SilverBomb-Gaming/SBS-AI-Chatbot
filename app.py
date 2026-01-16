"""Application entrypoint for SBS AI Chatbot."""
from __future__ import annotations

from flask import Flask

from config import load_config
from core.triage import DEFAULT_RULES, configure_rule_provider, deserialize_rules, serialize_rules
from services import brain, persistence
from web.routes import bp as main_blueprint


def create_app() -> Flask:
    config = load_config()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=config.secret_key,
        APP_TIER=config.app_tier,
        REQUEST_SIZE_LIMIT=config.request_size_limit,
        RATE_LIMIT_REQUESTS=config.rate_limit_requests,
        RATE_LIMIT_WINDOW=config.rate_limit_window,
        API_KEYS=config.api_keys,
        DATABASE_URL=config.database_url,
    )
    app.config["FEATURE_FLAGS"] = dict(config.features)
    app.config.update(config.features)
    app.config["X_API_KEYS"] = set(config.api_keys)
    persistence.init_storage(config.database_url)
    brain.ensure_brain_initialized(config.database_url, serialize_rules(DEFAULT_RULES))
    
    def _brain_rule_loader():
        payload = brain.load_active_rules(config.database_url)
        if not payload:
            return DEFAULT_RULES
        return deserialize_rules(payload)

    configure_rule_provider(_brain_rule_loader)
    app.register_blueprint(main_blueprint)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
