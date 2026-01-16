"""Deterministic ticket triage utilities.

The goal of this module is to provide predictable outputs so the
application stays explainable even when more advanced tiers add LLM
assistance. All heuristics rely on the rules defined below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List


@dataclass(frozen=True)
class KeywordRule:
    keyword: str
    weight: int
    category: str
    suggested_action: str
    suggested_reply: str


DEFAULT_RULES: List[KeywordRule] = [
    KeywordRule(
        keyword="outage",
        weight=5,
        category="incident",
        suggested_action="Escalate to on-call engineer",
        suggested_reply="We are investigating the outage and will update you shortly.",
    ),
    KeywordRule(
        keyword="slow",
        weight=3,
        category="performance",
        suggested_action="Collect logs and run performance diagnostics",
        suggested_reply="Thanks for flagging the slowdown; we are analyzing the metrics now.",
    ),
    KeywordRule(
        keyword="billing",
        weight=4,
        category="billing",
        suggested_action="Loop in finance representative",
        suggested_reply="We are reviewing your billing question and will respond soon.",
    ),
    KeywordRule(
        keyword="login",
        weight=3,
        category="access",
        suggested_action="Check authentication service health",
        suggested_reply="We are checking the authentication service to restore your access.",
    ),
]


@dataclass
class TriageResult:
    category: str
    priority: str
    confidence: float
    matched_keywords: List[str] = field(default_factory=list)
    suggested_action: str = "Review ticket details"
    suggested_reply: str = "Thanks for contacting support. We are on it."

    def as_dict(self) -> Dict[str, object]:
        return {
            "category": self.category,
            "priority": self.priority,
            "confidence": round(self.confidence, 2),
            "matched_keywords": self.matched_keywords,
            "suggested_action": self.suggested_action,
            "suggested_reply": self.suggested_reply,
        }


def _score_text(text: str, rules: Iterable[KeywordRule]) -> Dict[str, int]:
    normalized = text.lower()
    scores: Dict[str, int] = {}
    for rule in rules:
        if rule.keyword in normalized:
            scores[rule.category] = scores.get(rule.category, 0) + rule.weight
    return scores


def _determine_priority(score: int) -> str:
    if score >= 8:
        return "critical"
    if score >= 5:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


_rule_provider: Callable[[], Iterable[KeywordRule]] | None = None


def configure_rule_provider(provider: Callable[[], Iterable[KeywordRule]]) -> None:
    """Register a callable that supplies active rules."""

    global _rule_provider
    _rule_provider = provider


def _provided_rules() -> List[KeywordRule]:
    if _rule_provider:
        supplied = list(_rule_provider())
        if supplied:
            return supplied
    return list(DEFAULT_RULES)


def analyze_ticket(title: str, description: str, rules: Iterable[KeywordRule] | None = None) -> TriageResult:
    """Return a deterministic triage result from textual input."""
    if not title and not description:
        return TriageResult(category="general", priority="low", confidence=0.2)

    combined = f"{title}\n{description}".strip()
    active_rules = list(rules or _provided_rules())
    scores = _score_text(combined, active_rules)

    if scores:
        category = max(scores, key=scores.get)
        total_score = scores[category]
        matched_rules = [rule for rule in active_rules if rule.category == category and rule.keyword in combined.lower()]
        matched_keywords = sorted({rule.keyword for rule in matched_rules})
        suggested_action = matched_rules[0].suggested_action
        suggested_reply = matched_rules[0].suggested_reply
    else:
        category = "general"
        total_score = 1
        matched_keywords = []
        suggested_action = "Gather more context"
        suggested_reply = "Thanks for the report; we are reviewing the details."

    priority = _determine_priority(total_score)
    confidence = min(0.95, 0.3 + 0.08 * total_score)

    return TriageResult(
        category=category,
        priority=priority,
        confidence=confidence,
        matched_keywords=matched_keywords,
        suggested_action=suggested_action,
        suggested_reply=suggested_reply,
    )


def serialize_rules(rules: Iterable[KeywordRule]) -> List[Dict[str, object]]:
    return [
        {
            "keyword": rule.keyword,
            "weight": rule.weight,
            "category": rule.category,
            "suggested_action": rule.suggested_action,
            "suggested_reply": rule.suggested_reply,
        }
        for rule in rules
    ]


def deserialize_rules(payload: Iterable[Dict[str, object]]) -> List[KeywordRule]:
    result: List[KeywordRule] = []
    for entry in payload:
        result.append(
            KeywordRule(
                keyword=str(entry.get("keyword", "")),
                weight=int(entry.get("weight", 1)),
                category=str(entry.get("category", "general")),
                suggested_action=str(entry.get("suggested_action", "Review ticket")),
                suggested_reply=str(entry.get("suggested_reply", "Thanks for contacting support.")),
            )
        )
    return result
