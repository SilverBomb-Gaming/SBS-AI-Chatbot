"""HTTP helpers for reporting Unity runs back to AI-E."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict
from urllib import error, request

from runner.config import RunnerConfig, redact_secret

LOGGER = logging.getLogger(__name__)
MAX_POST_ATTEMPTS = 2


def post_episode(payload: Dict[str, Any], config: RunnerConfig) -> bool:
    """POST the episode payload to AI-E with one retry on network errors."""
    endpoint = config.episodes_endpoint()
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": config.ai_e_api_key,
    }
    redacted_key = redact_secret(config.ai_e_api_key)

    for attempt in range(1, MAX_POST_ATTEMPTS + 1):
        req = request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            LOGGER.info("Posting episode to %s (attempt %s)", endpoint, attempt)
            with request.urlopen(req, timeout=config.poster_timeout_seconds) as resp:
                status = getattr(resp, "status", resp.getcode())
                if 200 <= status < 300:
                    LOGGER.info("Episode posted successfully (status %s)", status)
                    return True
                LOGGER.error("Episode POST failed with status %s", status)
                return False
        except error.HTTPError as http_exc:
            LOGGER.error(
                "Episode POST rejected (status %s): %s",
                http_exc.code,
                http_exc.read().decode("utf-8", errors="ignore"),
            )
            return False
        except error.URLError as net_exc:
            LOGGER.warning(
                "Network error posting episode (attempt %s, key %s): %s",
                attempt,
                redacted_key,
                net_exc,
            )
            if attempt >= MAX_POST_ATTEMPTS:
                return False
            time.sleep(1)
    return False
