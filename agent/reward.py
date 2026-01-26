"""Reward shaping helpers for health-based learning."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


DEFAULT_IDLE_PENALTY = 0.001


def compute_reward(
    *,
    enemy_prev: float,
    enemy_now: float,
    me_prev: float,
    me_now: float,
    idle_penalty: float = DEFAULT_IDLE_PENALTY,
) -> Tuple[float, float, float]:
    delta_enemy = enemy_prev - enemy_now
    delta_me = me_prev - me_now
    reward = delta_enemy - delta_me - idle_penalty
    return reward, delta_enemy, delta_me


def net_advantage(
    *,
    enemy_start: float,
    enemy_end: float,
    me_start: float,
    me_end: float,
) -> float:
    return (enemy_start - enemy_end) - (me_start - me_end)


@dataclass
class EMA:
    alpha: float = 0.2
    _value: float | None = None

    def update(self, value: float) -> float:
        if self._value is None:
            self._value = value
        else:
            self._value = self.alpha * value + (1.0 - self.alpha) * self._value
        return self._value
