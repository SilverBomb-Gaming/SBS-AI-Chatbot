"""LLM integration scaffold."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class LLMResponse:
    improved_reply: str
    next_steps: str


class LLMProvider:
    def generate(self, ticket_payload: Dict[str, object]) -> LLMResponse:
        raise NotImplementedError


class NullProvider(LLMProvider):
    def generate(self, ticket_payload: Dict[str, object]) -> LLMResponse:
        return LLMResponse(
            improved_reply=ticket_payload.get("suggested_reply", "Thanks for your patience."),
            next_steps="LLM assist disabled.",
        )
