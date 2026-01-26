"""Run plan parsing helpers for the Unity runner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List


class RunPlanError(ValueError):
    """Raised when an invalid run plan is requested."""


@dataclass(frozen=True)
class RunPlan:
    """Normalized representation of the requested execution plan."""

    kind: str  # single, queue, schedule
    scenarios: List[str]
    every_minutes: int | None = None
    max_runs: int | None = None
    duration_minutes: int | None = None
    stop_on_fail: bool = False

    def scenario_for_index(self, index: int) -> str | None:
        if not self.scenarios:
            return None
        if self.kind == "queue":
            return self.scenarios[index]
        return self.scenarios[0]


def build_run_plan(args: Any) -> RunPlan:
    """Validate CLI arguments and construct a RunPlan instance."""

    kind = (args.plan or "single").strip().lower()
    if kind not in {"single", "queue", "schedule"}:
        raise RunPlanError("--plan must be single, queue, or schedule")

    stop_on_fail = bool(getattr(args, "stop_on_fail", False))

    if kind == "single":
        scenarios = _single_scenarios(args)
        return RunPlan(kind=kind, scenarios=scenarios, stop_on_fail=stop_on_fail)

    if kind == "queue":
        scenarios = _queue_scenarios(args)
        return RunPlan(kind=kind, scenarios=scenarios, stop_on_fail=stop_on_fail)

    # schedule
    scenario = _require_scenario(args, "schedule")
    every_minutes = _require_positive_int(args.every_minutes, "--every-minutes")
    max_runs = _optional_positive_int(args.max_runs, "--max-runs")
    duration_minutes = _optional_positive_int(
        args.duration_minutes, "--duration-minutes"
    )
    return RunPlan(
        kind=kind,
        scenarios=[scenario],
        every_minutes=every_minutes,
        max_runs=max_runs,
        duration_minutes=duration_minutes,
        stop_on_fail=stop_on_fail,
    )


def _single_scenarios(args: Any) -> List[str]:
    scenario = getattr(args, "scenario", None)
    return [scenario.strip()] if scenario and scenario.strip() else []


def _queue_scenarios(args: Any) -> List[str]:
    raw = getattr(args, "scenarios", None)
    if not raw or not raw.strip():
        raise RunPlanError("--plan queue requires --scenarios")
    parts = [piece.strip() for piece in raw.split(",")]
    scenarios = [piece for piece in parts if piece]
    if not scenarios:
        raise RunPlanError("--scenarios must list at least one scenario")
    return scenarios


def _require_scenario(args: Any, plan: str) -> str:
    scenario = getattr(args, "scenario", None)
    if not scenario or not scenario.strip():
        raise RunPlanError(f"--plan {plan} requires --scenario")
    return scenario.strip()


def _require_positive_int(value, flag: str) -> int:
    if value is None:
        raise RunPlanError(f"{flag} is required")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RunPlanError(f"{flag} must be an integer") from exc
    if parsed <= 0:
        raise RunPlanError(f"{flag} must be greater than zero")
    return parsed


def _optional_positive_int(value, flag: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RunPlanError(f"{flag} must be an integer") from exc
    if parsed <= 0:
        raise RunPlanError(f"{flag} must be greater than zero")
    return parsed
