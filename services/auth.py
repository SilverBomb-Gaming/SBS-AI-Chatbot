"""Authentication helpers.

For the bootstrap commit these helpers are intentionally light-weight. Later
commits will add persistence-backed API keys and RBAC handling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class AuthContext:
    api_key: str | None = None
    roles: List[str] | None = None


def attach_roles(api_key: str | None) -> Iterable[str]:
    """Return roles associated with an API key.

    Baseline implementation returns empty roles so that RBAC decorators can be
    exercised in tests without persisting data yet.
    """

    if not api_key:
        return []
    if api_key.endswith("-admin"):
        return ["admin", "analyst"]
    return ["analyst"]
