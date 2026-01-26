"""State encoding helpers for the trainer."""
from __future__ import annotations

import json
from typing import Any

HEALTH_BUCKETS = 20
TIME_BUCKETS = 6


def _bucket(value: float, buckets: int) -> int:
    clamped = max(0.0, min(1.0, value))
    return min(buckets - 1, int(clamped * buckets))


def _time_bucket(t: float, episode_seconds: float) -> int:
    if episode_seconds <= 0:
        return 0
    ratio = max(0.0, min(1.0, t / episode_seconds))
    return min(TIME_BUCKETS - 1, int(ratio * TIME_BUCKETS))


def make_state(
    my_hp: float,
    enemy_hp: float,
    t: float,
    last_action: str,
    episode_seconds: float,
) -> str:
    state: dict[str, Any] = {
        "my": _bucket(my_hp, HEALTH_BUCKETS),
        "enemy": _bucket(enemy_hp, HEALTH_BUCKETS),
        "time": _time_bucket(t, episode_seconds),
        "last": last_action,
    }
    return json.dumps(state, sort_keys=True)
