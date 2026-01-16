"""Rule persistence placeholder."""
from __future__ import annotations

from typing import Iterable, List

from core.triage import KeywordRule, DEFAULT_RULES


class RuleStore:
    def __init__(self) -> None:
        self._rules: List[KeywordRule] = list(DEFAULT_RULES)

    def list_rules(self) -> List[KeywordRule]:
        return list(self._rules)

    def update_rules(self, rules: Iterable[KeywordRule]) -> None:
        self._rules = list(rules)


RULES = RuleStore()
