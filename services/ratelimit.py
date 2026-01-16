"""Tiny in-memory rate limiter."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict


class RateLimiter:
    def __init__(self) -> None:
        self._store: Dict[str, Deque[float]] = defaultdict(deque)

    def check_allow(self, identifier: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        window = self._store[identifier]
        while window and now - window[0] > window_seconds:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    def reset(self) -> None:
        self._store.clear()
