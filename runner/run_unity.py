"""Unity runner entrypoint for AI-E episodes."""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from runner.capture import ArtifactPaths, ScreenshotRecorder, create_artifact_paths
from runner.config import (
    ALLOWED_RUN_MODES,
    RunnerConfig,
    RunnerConfigError,
    load_runner_config,
    redact_secret,
)
from runner.post_episode import post_episode

LOGGER = logging.getLogger(__name__)

BREAKER_MAX_DURATION_SECONDS = 90
BREAKER_SCREENSHOT_INTERVAL_SECONDS = 2
BREAKER_MAX_SCREENSHOTS = 20


class RunnerScenarioError(RunnerConfigError):
    """Raised when scenario configuration is invalid."""


@dataclass
class ScenarioPlan:
    scenario: Dict[str, Any]
    overrides: Dict[str, Any]


@dataclass
class RunResult:
    """Outcome of a Unity execution."""

    runtime_seconds: float
    exit_code: int | None
    logs: List[Path]
    screenshots: List[Path]
    status: str
    started_at: str
    finished_at: str
    error: str | None = None
    artifacts_dir: Path | None = None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute a Unity build and report episodes."
    )
    parser.add_argument(
        "--mode", choices=sorted(ALLOWED_RUN_MODES), help="Override RUN_MODE"
    )
    parser.add_argument("--scenario", help="Scenario identifier to execute")
    parser.add_argument(
        "--scenarios-file",
        help="Path to a scenarios.json file (defaults to runner/scenarios.json)",
    )
    parser.add_argument("--duration", type=int, help="Maximum runtime in seconds")
    parser.add_argument(
        "--screenshots",
        type=int,
        help="Maximum screenshots to capture (0 disables screenshots)",
    )
    parser.add_argument(
        "--screenshot-interval",
        type=int,
        help="Seconds between screenshots when enabled",
    )
    return parser.parse_args(argv)


def apply_cli_overrides(args: argparse.Namespace) -> None:
    env = os.environ
    if args.mode:
        env["RUN_MODE"] = args.mode
    if args.scenario:
        env["SCENARIO_ID"] = args.scenario
    if args.scenarios_file:
        env["SCENARIOS_FILE"] = args.scenarios_file
    if args.duration is not None:
        env["RUN_DURATION_SECONDS"] = str(args.duration)
    if args.screenshots is not None:
        env["SCREENSHOT_MAX_CAPTURES"] = str(args.screenshots)
        env["RUNNER_SCREENSHOT_MAX_CAPTURES"] = str(args.screenshots)
        env["RUNNER_SCREENSHOTS"] = "1" if args.screenshots > 0 else "0"
    if args.screenshot_interval is not None:
        env["SCREENSHOT_INTERVAL_SECONDS"] = str(args.screenshot_interval)
        env["RUNNER_SCREENSHOT_INTERVAL"] = str(args.screenshot_interval)
        if args.screenshot_interval > 0 and "RUNNER_SCREENSHOTS" not in env:
            env["RUNNER_SCREENSHOTS"] = "1"


def _prepare_config(config: RunnerConfig) -> None:
    plan: ScenarioPlan | None = None
    if config.scenario_id:
        plan = load_scenario_plan(config.scenarios_file, config.scenario_id)
    if config.run_mode in {"instructed", "breaker"} and plan is None:
        raise RunnerScenarioError(
            f"RUN_MODE '{config.run_mode}' requires a scenario (set SCENARIO_ID or --scenario)"
        )
    if plan:
        config.scenario = plan.scenario
        config.scenario_overrides = plan.overrides
    _apply_scenario_overrides(config)


def _apply_scenario_overrides(config: RunnerConfig) -> None:
    overrides = config.scenario_overrides or {}
    duration = overrides.get("duration_seconds")
    if duration:
        config.run_duration_seconds = duration
    interval = overrides.get("screenshot_interval_seconds")
    if interval and not config.screenshots_opt_out:
        config.screenshot_interval_seconds = interval
    max_shots = overrides.get("max_screenshots")
    if max_shots is not None and not config.screenshots_opt_out:
        config.screenshot_max_captures = max_shots
    if labels := overrides.get("labels"):
        config.episode_labels = _merge_labels(config.episode_labels, tuple(labels))

    if config.run_mode == "instructed":
        config.episode_labels = _merge_labels(config.episode_labels, ("instructed",))
    if config.run_mode == "breaker":
        config.episode_labels = _merge_labels(config.episode_labels, ("breaker",))
        config.run_duration_seconds = min(
            config.run_duration_seconds, BREAKER_MAX_DURATION_SECONDS
        )
        if not config.screenshots_opt_out:
            if (
                config.screenshot_interval_seconds is None
                or config.screenshot_interval_seconds
                > BREAKER_SCREENSHOT_INTERVAL_SECONDS
            ):
                config.screenshot_interval_seconds = BREAKER_SCREENSHOT_INTERVAL_SECONDS
            if config.screenshot_max_captures is None:
                config.screenshot_max_captures = BREAKER_MAX_SCREENSHOTS


def _merge_labels(
    existing: Sequence[str], new_labels: Sequence[str]
) -> tuple[str, ...]:
    merged = list(existing)
    for label in new_labels:
        cleaned = (label or "").strip()
        if cleaned and cleaned not in merged:
            merged.append(cleaned)
    return tuple(merged)


def _build_scenario_payload(
    scenario_source: Dict[str, Any],
    result: RunResult,
    logs: List[str],
    screenshots: List[str],
) -> Dict[str, Any]:
    scenario_payload = copy.deepcopy(scenario_source)
    observed = {
        "runtime_seconds": result.runtime_seconds,
        "exit_code": result.exit_code,
        "status": result.status,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "logs": logs,
        "screenshots": screenshots,
    }
    if result.error:
        observed["error"] = result.error
    scenario_payload["observed"] = observed
    return scenario_payload


def load_scenario_plan(file_path: Path, scenario_id: str) -> ScenarioPlan:
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunnerScenarioError(f"Scenarios file not found: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise RunnerScenarioError(
            f"Scenarios file {file_path} is not valid JSON"
        ) from exc

    entries = _coerce_scenario_entries(raw)
    requested = scenario_id.strip()
    for entry in entries:
        candidate = entry.get("scenario_id") or entry.get("id")
        if isinstance(candidate, str) and candidate.strip() == requested:
            return _normalize_scenario_entry(entry)
    raise RunnerScenarioError(
        f"Scenario '{scenario_id}' was not found inside {file_path}"
    )


def _coerce_scenario_entries(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        return [entry for entry in raw if isinstance(entry, dict)]
    if isinstance(raw, dict):
        if isinstance(raw.get("scenarios"), list):
            return _coerce_scenario_entries(raw["scenarios"])
        entries: List[Dict[str, Any]] = []
        for key, value in raw.items():
            if isinstance(value, dict):
                candidate = dict(value)
                candidate.setdefault("scenario_id", str(key))
                entries.append(candidate)
        if entries:
            return entries
    raise RunnerScenarioError("Scenarios file must be a list or mapping of objects")


def _normalize_scenario_entry(entry: Dict[str, Any]) -> ScenarioPlan:
    scenario_id = _require_string(entry, ("scenario_id", "id"), "scenario id")
    scenario_name = _require_string(entry, ("scenario_name", "name"), "scenario name")
    steps = _normalize_steps(entry)
    expected = entry.get("expected")
    if not isinstance(expected, dict) or not expected:
        raise RunnerScenarioError("scenario expected block must be an object")
    scenario: Dict[str, Any] = {
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "scenario_steps": steps,
        "expected": expected,
    }
    seed = entry.get("scenario_seed", entry.get("seed"))
    if seed is not None:
        scenario["scenario_seed"] = _coerce_int(seed, "scenario_seed")
    observed = entry.get("observed")
    if observed is not None:
        if not isinstance(observed, dict):
            raise RunnerScenarioError("scenario observed block must be an object")
        scenario["observed"] = observed
    overrides = _extract_runner_overrides(entry)
    return ScenarioPlan(scenario=scenario, overrides=overrides)


def _require_string(entry: Dict[str, Any], keys: Sequence[str], label: str) -> str:
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RunnerScenarioError(f"{label} is required for scenario definitions")


def _normalize_steps(entry: Dict[str, Any]) -> List[str]:
    raw_steps = entry.get("scenario_steps") or entry.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RunnerScenarioError("scenario_steps must be a non-empty list")
    normalized: List[str] = []
    for step in raw_steps:
        if not isinstance(step, str):
            raise RunnerScenarioError("scenario_steps entries must be strings")
        cleaned = step.strip()
        if cleaned:
            normalized.append(cleaned)
    if not normalized:
        raise RunnerScenarioError("scenario_steps cannot be empty")
    return normalized


def _extract_runner_overrides(entry: Dict[str, Any]) -> Dict[str, Any]:
    overrides: Dict[str, Any] = {}
    runner_block = entry.get("runner") if isinstance(entry.get("runner"), dict) else {}

    def _maybe(source: Dict[str, Any], key: str, *, allow_zero: bool = False) -> None:
        if key not in source:
            return
        value = source[key]
        if key == "labels":
            overrides[key] = _normalize_labels(value)
            return
        parsed = _coerce_int(value, key, allow_zero=allow_zero)
        overrides[key] = parsed

    _maybe(runner_block, "duration_seconds")
    _maybe(entry, "duration_seconds")
    _maybe(runner_block, "screenshot_interval_seconds")
    _maybe(entry, "screenshot_interval_seconds")
    _maybe(runner_block, "max_screenshots", allow_zero=True)
    _maybe(entry, "max_screenshots", allow_zero=True)
    if "labels" in runner_block:
        overrides["labels"] = _normalize_labels(runner_block["labels"])
    elif "labels" in entry:
        overrides["labels"] = _normalize_labels(entry["labels"])
    return overrides


def _normalize_labels(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = value.split(",")
    else:
        candidates = list(value)
    normalized: List[str] = []
    for raw in candidates:
        cleaned = str(raw).strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _coerce_int(value: Any, field: str, *, allow_zero: bool = False) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RunnerScenarioError(f"{field} must be an integer") from exc
    if parsed < 0 or (parsed == 0 and not allow_zero):
        comparison = "zero" if allow_zero else "greater than zero"
        raise RunnerScenarioError(f"{field} must be {comparison}")
    return parsed


def determine_status(exit_code: int | None, error_message: str | None) -> str:
    if error_message is not None:
        return "error"
    if exit_code is None:
        return "error"
    if exit_code == 0:
        return "pass"
    return "fail"


def build_episode_payload(config: RunnerConfig, result: RunResult) -> dict:
    logs = [str(path) for path in result.logs if path.exists()]
    screenshots = [str(path) for path in result.screenshots if path.exists()]
    metrics: Dict[str, Any] = {
        "duration_seconds": result.runtime_seconds,
        "exit_code": result.exit_code,
    }
    if screenshots:
        metrics["screenshots_captured"] = len(screenshots)

    payload: Dict[str, Any] = {
        "source": "unity-runner",
        "mode": config.run_mode,
        "status": result.status,
        "project": config.project_name,
        "build_id": config.build_id,
        "metrics": metrics,
        "artifacts": {
            "logs": logs,
            "screenshots": screenshots,
        },
        "labels": list(config.episode_labels),
    }
    if config.scenario:
        scenario_payload = _build_scenario_payload(
            config.scenario, result, logs, screenshots
        )
        payload["scenario"] = scenario_payload
        metrics["scenario"] = copy.deepcopy(scenario_payload)
    if result.error:
        payload["error"] = result.error
    return payload


def _write_pending_episode(payload: Dict[str, Any], artifacts_dir: Path | None) -> None:
    if not artifacts_dir:
        LOGGER.warning("Cannot store pending episode; artifacts directory unknown")
        return
    destination = artifacts_dir / "episode_pending.json"
    try:
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        LOGGER.info("Episode payload saved locally at %s", destination)
    except OSError as exc:  # pragma: no cover - filesystem safety
        LOGGER.error("Unable to save pending episode: %s", exc)


def execute_run(
    config: RunnerConfig,
    *,
    artifact_paths: ArtifactPaths | None = None,
    popen_cls=subprocess.Popen,
) -> RunResult:
    artifacts = artifact_paths or create_artifact_paths(config.artifacts_root)
    LOGGER.info("Artifacts stored in %s", artifacts.run_dir)
    recorder = ScreenshotRecorder(
        config.screenshot_interval_seconds,
        artifacts,
        config.screenshot_max_captures,
    )
    recorder.start()

    error_message: str | None = None
    exit_code: int | None = None
    started_at = datetime.now(timezone.utc)
    start = time.monotonic()
    try:
        exit_code = _launch_unity_process(config, artifacts, popen_cls=popen_cls)
    except Exception as exc:  # pragma: no cover - defensive
        error_message = str(exc)
        LOGGER.exception("Unity process failed: %s", exc)
    finally:
        recorder.stop()
    finished_at = datetime.now(timezone.utc)
    runtime = round(time.monotonic() - start, 2)
    status = determine_status(exit_code, error_message)
    return RunResult(
        runtime_seconds=runtime,
        exit_code=exit_code,
        logs=[artifacts.stdout_log, artifacts.stderr_log],
        screenshots=recorder.paths,
        status=status,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        error=error_message,
        artifacts_dir=artifacts.run_dir,
    )


def _launch_unity_process(
    config: RunnerConfig,
    artifacts: ArtifactPaths,
    *,
    popen_cls,
) -> int:
    command: Sequence[str] = [str(config.unity_executable)]
    redacted_key = redact_secret(config.ai_e_api_key)
    LOGGER.info(
        "Starting Unity executable %s for project %s (key %s)",
        config.unity_executable,
        config.project_name,
        redacted_key,
    )
    with (
        open(artifacts.stdout_log, "w", encoding="utf-8", errors="replace") as stdout_f,
        open(artifacts.stderr_log, "w", encoding="utf-8", errors="replace") as stderr_f,
    ):
        process = popen_cls(
            command,
            stdout=stdout_f,
            stderr=stderr_f,
            cwd=str(config.unity_executable.parent),
        )
        try:
            return process.wait(timeout=config.run_duration_seconds)
        except subprocess.TimeoutExpired:
            LOGGER.warning(
                "Run exceeded %s seconds; attempting graceful shutdown",
                config.run_duration_seconds,
            )
            process.terminate()
            try:
                return process.wait(timeout=config.max_shutdown_seconds)
            except subprocess.TimeoutExpired:
                LOGGER.error("Unity process unresponsive; killing")
                process.kill()
                return process.wait()


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(argv)
    apply_cli_overrides(args)
    try:
        config = load_runner_config()
        _prepare_config(config)
    except RunnerScenarioError as exc:
        LOGGER.error("Scenario error: %s", exc)
        return 1
    except RunnerConfigError as exc:
        LOGGER.error("Configuration error: %s", exc)
        return 1

    result = execute_run(config)
    payload = build_episode_payload(config, result)
    if not post_episode(payload, config):
        _write_pending_episode(payload, result.artifacts_dir)
        LOGGER.error("Failed to post Unity episode to AI-E")
        return 1
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
