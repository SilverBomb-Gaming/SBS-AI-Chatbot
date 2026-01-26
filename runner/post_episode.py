"""HTTP helpers for reporting Unity runs back to AI-E."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict
from urllib import error, request

from runner.config import RunnerConfig, redact_secret

LOGGER = logging.getLogger(__name__)
MAX_POST_ATTEMPTS = 2


@dataclass
class EpisodePostResult:
    """Outcome of attempting to POST an episode payload."""

    success: bool
    status_code: int | None = None
    episode_id: int | None = None
    response: Dict[str, Any] | None = None
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None


def post_episode(payload: Dict[str, Any], config: RunnerConfig) -> EpisodePostResult:
    """POST the episode payload to AI-E with one retry on network errors."""

    if not config.ai_e_base_url:
        return EpisodePostResult(
            success=False,
            skipped=True,
            skip_reason="API base URL not configured",
        )
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
                body_bytes = resp.read() or b""
                response_payload: Dict[str, Any] | None = None
                episode_id: int | None = None
                if body_bytes:
                    try:
                        response_payload = json.loads(body_bytes.decode("utf-8"))
                        if isinstance(response_payload, dict):
                            raw_id = response_payload.get("episode_id")
                            if isinstance(raw_id, int):
                                episode_id = raw_id
                    except json.JSONDecodeError:
                        LOGGER.debug("Episode POST returned non-JSON body")
                if 200 <= status < 300:
                    LOGGER.info("Episode posted successfully (status %s)", status)
                    return EpisodePostResult(
                        success=True,
                        status_code=status,
                        episode_id=episode_id,
                        response=response_payload,
                    )
                LOGGER.error("Episode POST failed with status %s", status)
                return EpisodePostResult(
                    success=False,
                    status_code=status,
                    response=response_payload,
                    error=f"HTTP {status}",
                )
        except error.HTTPError as http_exc:
            error_body = http_exc.read().decode("utf-8", errors="ignore")
            LOGGER.error(
                "Episode POST rejected (status %s): %s",
                http_exc.code,
                error_body,
            )
            return EpisodePostResult(
                success=False,
                status_code=http_exc.code,
                error=error_body or f"HTTP {http_exc.code}",
            )
        except error.URLError as net_exc:
            LOGGER.warning(
                "Network error posting episode (attempt %s, key %s): %s",
                attempt,
                redacted_key,
                net_exc,
            )
            if attempt >= MAX_POST_ATTEMPTS:
                return EpisodePostResult(
                    success=False,
                    error=str(
                        net_exc.reason if hasattr(net_exc, "reason") else net_exc
                    ),
                )
            time.sleep(1)
    return EpisodePostResult(success=False, error="Exhausted retries")
