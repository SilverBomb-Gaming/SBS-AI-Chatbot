"""Simple tabular Q-learning with epsilon-greedy exploration."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class QLearner:
    alpha: float = 0.15
    gamma: float = 0.95
    epsilon: float = 0.8
    epsilon_end: float = 0.1
    epsilon_decay: float = 0.995
    q_table: Dict[str, Dict[str, float]] = None

    def __post_init__(self) -> None:
        if self.q_table is None:
            self.q_table = {}

    @classmethod
    def load(cls, path: Path) -> "QLearner":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        learner = cls()
        learner.q_table = data.get("q_table", {})
        learner.alpha = data.get("alpha", learner.alpha)
        learner.gamma = data.get("gamma", learner.gamma)
        learner.epsilon = data.get("epsilon", learner.epsilon)
        learner.epsilon_end = data.get("epsilon_end", learner.epsilon_end)
        learner.epsilon_decay = data.get("epsilon_decay", learner.epsilon_decay)
        return learner

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "alpha": self.alpha,
            "gamma": self.gamma,
            "epsilon": self.epsilon,
            "epsilon_end": self.epsilon_end,
            "epsilon_decay": self.epsilon_decay,
            "q_table": self.q_table,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def select_action(self, state: str, legal_actions: List[str]) -> str:
        if not legal_actions:
            raise ValueError("No legal actions provided.")
        if random.random() < self.epsilon:
            return random.choice(legal_actions)
        values = self.q_table.get(state, {})
        best = max(legal_actions, key=lambda a: values.get(a, 0.0))
        return best

    def update(self, state: str, action: str, reward: float, next_state: str, legal_actions: List[str]) -> None:
        state_map = self.q_table.setdefault(state, {})
        current = state_map.get(action, 0.0)
        next_values = self.q_table.get(next_state, {})
        best_next = 0.0
        if legal_actions:
            best_next = max(next_values.get(a, 0.0) for a in legal_actions)
        updated = (1.0 - self.alpha) * current + self.alpha * (reward + self.gamma * best_next)
        state_map[action] = updated

        if self.epsilon > self.epsilon_end:
            self.epsilon *= self.epsilon_decay
            if self.epsilon < self.epsilon_end:
                self.epsilon = self.epsilon_end
