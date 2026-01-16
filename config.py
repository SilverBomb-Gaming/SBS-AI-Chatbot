"""Runtime configuration helpers."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

BASE_DIR = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)

DEFAULT_SECRET = "dev-secret"
DEFAULT_APP_TIER = "public"

_DEFAULT_DATABASE_URL = f"sqlite:///{BASE_DIR / 'tickets.db'}"

VALID_APP_TIERS = {"public", "paid", "ultimate"}

FEATURE_MATRIX: Dict[str, Dict[str, bool]] = {
    "public": {
        "FEATURE_RATE_LIMIT": True,
        "FEATURE_AUTH": False,
        "FEATURE_PERSISTENCE": False,
        "FEATURE_EXPORT": False,
        "FEATURE_RBAC": False,
        "FEATURE_AUDIT": True,  # minimal admin logging allowed
        "FEATURE_WEBHOOKS": False,
        "FEATURE_RULES_EDITOR": False,
        "FEATURE_LLM_ASSIST": False,
    },
    "paid": {
        "FEATURE_RATE_LIMIT": True,
        "FEATURE_AUTH": True,
        "FEATURE_PERSISTENCE": True,
        "FEATURE_EXPORT": True,
        "FEATURE_RBAC": False,
        "FEATURE_AUDIT": True,
        "FEATURE_WEBHOOKS": False,
        "FEATURE_RULES_EDITOR": False,
        "FEATURE_LLM_ASSIST": False,
    },
    "ultimate": {
        "FEATURE_RATE_LIMIT": True,
        "FEATURE_AUTH": True,
        "FEATURE_PERSISTENCE": True,
        "FEATURE_EXPORT": True,
        "FEATURE_RBAC": True,
        "FEATURE_AUDIT": True,
        "FEATURE_WEBHOOKS": True,
        "FEATURE_RULES_EDITOR": True,
        "FEATURE_LLM_ASSIST": False,
    },
}


@dataclass
class Config:
    secret_key: str = DEFAULT_SECRET
    app_tier: str = DEFAULT_APP_TIER
    request_size_limit: int = 64 * 1024  # 64KB by default
    rate_limit_requests: int = 20
    rate_limit_window: int = 60
    api_keys: List[str] = field(default_factory=list)
    database_url: str = field(default_factory=lambda: _DEFAULT_DATABASE_URL)
    webhook_url: str | None = None
    openai_api_key: str | None = None
    features: Dict[str, bool] = field(default_factory=dict)


def _parse_api_keys(raw_value: str | None) -> List[str]:
    if not raw_value:
        return []
    candidate = raw_value.strip()
    if not candidate:
        return []
    keys: List[str] = []
    if candidate.startswith("["):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            LOGGER.warning("Invalid JSON provided for X_API_KEYS; ignoring value")
            return []
        if isinstance(parsed, list):
            for item in parsed:
                value = str(item).strip()
                if value:
                    keys.append(value)
        else:
            LOGGER.warning("X_API_KEYS JSON payload must be a list; got %s", type(parsed).__name__)
    else:
        keys = [piece for piece in (part.strip() for part in candidate.split(",")) if piece]
    # Remove duplicates while preserving order
    deduped: List[str] = []
    seen = set()
    for key in keys:
        if key not in seen:
            deduped.append(key)
            seen.add(key)
    if deduped:
        LOGGER.info("API key slots configured: %d", len(deduped))
    else:
        LOGGER.info("API key slots configured: 0")
    return deduped


def _sanitize_tier(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    if value in VALID_APP_TIERS:
        return value
    if value:
        LOGGER.warning("Invalid APP_TIER '%s'; falling back to '%s'", value, DEFAULT_APP_TIER)
    return DEFAULT_APP_TIER


def _feature_flags(tier: str, openai_api_key: str | None) -> Dict[str, bool]:
    base = dict(FEATURE_MATRIX[tier])
    if tier == "ultimate" and openai_api_key:
        base["FEATURE_LLM_ASSIST"] = True
    return base


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        LOGGER.warning("Invalid value '%s' for %s; using %s", raw, name, default)
        return default


def load_config() -> Config:
    """Read environment variables into a Config object."""
    app_tier = _sanitize_tier(os.getenv("APP_TIER"))
    openai_api_key = os.getenv("OPENAI_API_KEY")
    features = _feature_flags(app_tier, openai_api_key)
    api_keys = _parse_api_keys(os.getenv("X_API_KEYS"))

    return Config(
        secret_key=os.getenv("SECRET_KEY", DEFAULT_SECRET),
        app_tier=app_tier,
        request_size_limit=_int_from_env("REQUEST_MAX_BYTES", Config.request_size_limit),
        rate_limit_requests=_int_from_env("RATE_LIMIT_REQUESTS", Config.rate_limit_requests),
        rate_limit_window=_int_from_env("RATE_LIMIT_WINDOW", Config.rate_limit_window),
        api_keys=api_keys,
        database_url=os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL),
        webhook_url=os.getenv("WEBHOOK_URL"),
        openai_api_key=openai_api_key,
        features=features,
    )
