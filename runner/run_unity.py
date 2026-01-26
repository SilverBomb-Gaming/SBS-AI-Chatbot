"""Unity runner entrypoint for AI-E episodes."""
from __future__ import annotations

import argparse
import copy
import faulthandler
import json
import logging
import os
import shlex
import subprocess
import sys
import textwrap
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Sequence,
)

from runner.capture import ArtifactPaths, ScreenshotRecorder, create_artifact_paths
from runner.config import (
    ALLOWED_CAPTURE_MODES,
    ALLOWED_INPUT_MODES,
    ALLOWED_RUN_MODES,
    ALLOWED_SCREENSHOT_TARGETS,
    DEFAULT_ARTIFACTS_DIR,
    RunnerConfig,
    RunnerConfigError,
    load_runner_config,
    redact_secret,
)
from runner.plans import RunPlan, RunPlanError, build_run_plan
from runner.post_episode import EpisodePostResult, post_episode
from runner.reporting import (
    PlanReportSummary,
    RunReportRow,
    render_report,
    write_reports,
)
from runner.emailer import EmailResult, load_email_config, send_email
from runner.events import EventLogger
from runner.hotkeys import (
    GlobalHotkeyListener,
    HotkeyListener,
    TerminalCommandController,
    open_artifacts_folder,
)
from runner.input_capture.controller_logger import (
    ControllerLogger,
    ControllerStateStreamLogger,
    ControllerStateStreamSummary,
    InputLoggingSummary,
    resolve_backend_factory,
)
from runner.target_detect import (
    LockedTarget,
    TargetInfo,
    detect_foreground_target,
    format_target_message,
    lock_target,
    sanitize_name,
)

LOGGER = logging.getLogger(__name__)
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_BOOTSTRAP_ARTIFACTS: ArtifactPaths | None = None

BREAKER_MAX_DURATION_SECONDS = 90
BREAKER_SCREENSHOT_INTERVAL_SECONDS = 2
BREAKER_MAX_SCREENSHOTS = 20
REPORT_ENV_KEYS = [
    "APP_TIER",
    "PROJECT_NAME",
    "RUN_MODE",
    "AI_E_BASE_URL",
    "UNITY_EXE_PATH",
    "BUILD_ID",
    "RUNNER_SCREENSHOTS",
    "RUNNER_SCREENSHOT_INTERVAL",
    "RUNNER_SCREENSHOT_MAX_CAPTURES",
    "RUNNER_SCREENSHOT_TARGET",
    "RUNNER_CAPTURE_MODE",
]


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
    events_log: Path | None = None
    event_counts: Dict[str, int] | None = None
    capture_mode: str | None = None
    capture_warnings: List[str] | None = None
    capture_disabled_reason: str | None = None
    episode_payload_path: Path | None = None
    episode_response_path: Path | None = None
    launch_skipped: bool = False
    launch_reason: str | None = None
    input_status: str = "OFF"
    input_status_message: str | None = None
    input_events: int = 0
    input_log_path: Path | None = None
    input_warnings: List[str] | None = None
    input_state_status: str = "OFF"
    input_state_message: str | None = None
    input_state_frames: int = 0
    input_state_log_path: Path | None = None
    input_state_warnings: List[str] | None = None
    input_state_effective_hz: float | None = None
    input_state_target_hz: int | None = None
    input_state_expected_frames: int | None = None
    target_hwnd: int | None = None
    target_pid: int | None = None
    target_exe_path: str | None = None
    target_process_name: str | None = None
    target_window_title: str | None = None
    target_change_count: int = 0
    target_label: str | None = None
    target_label_hash: str | None = None


def _slugify(value: str) -> str:
    allowed = [char.lower() if char.isalnum() else "-" for char in value]
    slug = "".join(allowed).strip("-")
    return slug or "run"


def _generate_run_identifier(config: RunnerConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    project_slug = _slugify(config.project_name)
    build_slug = _slugify(config.build_id)
    base = f"{timestamp}_{config.run_mode}_{project_slug}_{build_slug}"
    return f"{base}_pending-target"


def _apply_target_label_to_run_id(
    run_id: str, lock: LockedTarget | None
) -> str:
    if not lock:
        return run_id
    suffix = lock.label_token
    base = run_id
    if base.endswith("_pending-target"):
        base = base[: -len("_pending-target")]
    return f"{base}_{suffix}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute a Unity build and report episodes."
    )
    parser.add_argument(
        "--mode", choices=sorted(ALLOWED_RUN_MODES), help="Override RUN_MODE"
    )
    parser.add_argument(
        "--plan",
        choices=["single", "queue", "schedule"],
        default="single",
        help="Run plan: single (default), queue, or schedule",
    )
    parser.add_argument("--scenario", help="Scenario identifier to execute")
    parser.add_argument(
        "--scenarios",
        help="Comma-separated list of scenarios for --plan queue",
    )
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
    parser.add_argument(
        "--screenshot-target",
        choices=sorted(ALLOWED_SCREENSHOT_TARGETS),
        help="Capture desktop or Unity window only",
    )
    parser.add_argument(
        "--capture",
        choices=sorted(ALLOWED_CAPTURE_MODES),
        help="Capture mode: off, unity_window, or desktop",
    )
    parser.add_argument(
        "--inputs",
        choices=sorted(ALLOWED_INPUT_MODES),
        help="Input logging mode: off or controller",
    )
    parser.add_argument(
        "--input-poll-interval-ms",
        type=int,
        help="Polling interval for controller input logging (ms)",
    )
    parser.add_argument(
        "--input-deadzone",
        type=float,
        help="Deadzone threshold for analog sticks/triggers (0-1)",
    )
    parser.add_argument(
        "--input-axis-epsilon",
        type=float,
        help="Minimum change before axis events are logged (0-1)",
    )
    parser.add_argument(
        "--input-state-hz",
        type=int,
        help="Dense controller state sampling rate in Hz (0 disables)",
    )
    parser.add_argument(
        "--input-state-format",
        help="Dense controller state output format (jsonl)",
    )
    parser.add_argument(
        "--input-state-raw",
        type=int,
        choices=[0, 1],
        help="Set to 1 to log raw values without deadzones (default)",
    )
    parser.add_argument(
        "--every-minutes",
        type=int,
        help="Schedule interval in minutes for --plan schedule",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        help="Maximum runs for --plan schedule",
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        help="Stop scheduled plan after N minutes",
    )
    parser.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="Stop executing additional runs once a failure is observed",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Observe only (human mode) without launching Unity",
    )
    parser.add_argument(
        "--target-mode",
        choices=["foreground-at-start", "first-non-terminal", "exe"],
        help="Target selection strategy for foreground app detection",
    )
    parser.add_argument(
        "--target-lock-seconds",
        type=int,
        help="Seconds to wait for target selection during lock window",
    )
    parser.add_argument(
        "--target-poll-ms",
        type=int,
        help="Polling interval (ms) while acquiring a target",
    )
    parser.add_argument(
        "--target-ignore",
        help="Comma-separated exe names to ignore during target selection",
    )
    parser.add_argument(
        "--target-exe",
        help="EXE name or full path to lock onto when --target-mode=exe",
    )
    parser.add_argument(
        "--target-exe-path",
        help="Explicit executable path to lock onto when --target-mode=exe",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose runner logging and faulthandler",
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
    if getattr(args, "screenshot_target", None):
        env["RUNNER_SCREENSHOT_TARGET"] = args.screenshot_target
    if getattr(args, "capture", None):
        env["RUNNER_CAPTURE_MODE"] = args.capture
    if getattr(args, "inputs", None):
        env["RUNNER_INPUTS"] = args.inputs
    if getattr(args, "input_poll_interval_ms", None) is not None:
        env["RUNNER_INPUT_POLL_MS"] = str(args.input_poll_interval_ms)
    if getattr(args, "input_deadzone", None) is not None:
        env["RUNNER_INPUT_DEADZONE"] = str(args.input_deadzone)
    if getattr(args, "input_axis_epsilon", None) is not None:
        env["RUNNER_INPUT_AXIS_EPSILON"] = str(args.input_axis_epsilon)
    if getattr(args, "input_state_hz", None) is not None:
        env["RUNNER_INPUT_STATE_HZ"] = str(args.input_state_hz)
    if getattr(args, "input_state_format", None):
        env["RUNNER_INPUT_STATE_FORMAT"] = args.input_state_format
    if getattr(args, "input_state_raw", None) is not None:
        env["RUNNER_INPUT_STATE_RAW"] = str(args.input_state_raw)
    if getattr(args, "no_launch", None):
        env["RUNNER_NO_LAUNCH"] = "1"
    if getattr(args, "target_mode", None):
        env["RUNNER_TARGET_MODE"] = args.target_mode
    if getattr(args, "target_lock_seconds", None) is not None:
        env["RUNNER_TARGET_LOCK_SECONDS"] = str(args.target_lock_seconds)
    if getattr(args, "target_poll_ms", None) is not None:
        env["RUNNER_TARGET_POLL_MS"] = str(args.target_poll_ms)
    if getattr(args, "target_ignore", None):
        env["RUNNER_TARGET_IGNORE"] = args.target_ignore
    if getattr(args, "target_exe", None):
        env["RUNNER_TARGET_EXE"] = args.target_exe
    if getattr(args, "target_exe_path", None):
        env["RUNNER_TARGET_EXE_PATH"] = args.target_exe_path
    if getattr(args, "debug", None):
        env["RUNNER_DEBUG"] = "1"


def _debug_enabled(args: argparse.Namespace | None, env: Mapping[str, str]) -> bool:
    if args and getattr(args, "debug", False):
        return True
    raw = env.get("RUNNER_DEBUG", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _configure_logging(debug: bool, stderr_log: Path | None = None) -> None:
    level = logging.DEBUG if debug else logging.INFO
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    if stderr_log:
        file_handler = logging.FileHandler(stderr_log, encoding="utf-8")
        file_handler.setLevel(logging.ERROR)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handlers.append(file_handler)
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=handlers)


def _generate_preflight_identifier(env: Mapping[str, str]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_mode = _slugify(env.get("RUN_MODE", "unknown"))
    project = _slugify(env.get("PROJECT_NAME", "unknown"))
    build = _slugify(env.get("BUILD_ID", "unknown"))
    base = f"{timestamp}_{run_mode}_{project}_{build}"
    return f"{base}_pending-target"


def _prepare_artifacts(env: Mapping[str, str]) -> ArtifactPaths | None:
    run_id = _generate_preflight_identifier(env)
    try:
        artifacts = create_artifact_paths(DEFAULT_ARTIFACTS_DIR, run_id)
    except OSError as exc:
        LOGGER.error("Unable to create artifacts directory: %s", exc)
        return None
    _initialize_artifact_logs(artifacts)
    return artifacts


def _initialize_artifact_logs(artifacts: ArtifactPaths) -> None:
    for path in (artifacts.stdout_log, artifacts.stderr_log):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        except OSError as exc:
            LOGGER.warning("Unable to prepare log file %s: %s", path, exc)


@contextmanager
def _attach_error_log(path: Path | None) -> Iterator[None]:
    if not path:
        yield
        return
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.ERROR)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)
        handler.close()


def _write_failure_details(
    message: str,
    *,
    artifacts: ArtifactPaths | None,
    exc: BaseException | None = None,
) -> None:
    if not artifacts:
        return
    try:
        with artifacts.stderr_log.open(
            "a", encoding="utf-8", errors="replace"
        ) as handle:
            handle.write(message.rstrip() + "\n")
            if exc:
                traceback.print_exception(
                    type(exc), exc, exc.__traceback__, file=handle
                )
    except OSError as log_exc:
        LOGGER.warning(
            "Unable to write runner stderr log %s: %s", artifacts.stderr_log, log_exc
        )


def _write_target_metadata(artifacts: ArtifactPaths, target: LockedTarget | None) -> None:
    metadata_dir = artifacts.run_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {}
    if target:
        payload = {
            "hwnd": target.info.hwnd,
            "pid": target.info.pid,
            "exe_path": target.info.exe_path,
            "process_name": target.info.process_name,
            "window_title": target.info.window_title,
            "locked_at_utc": target.locked_at.isoformat(),
            "target_mode": target.mode,
            "lock_seconds": target.lock_seconds,
            "target_poll_ms": target.poll_ms,
            "label": target.label,
            "label_hash": target.hash_suffix,
        }
    destination = metadata_dir / "target_process.json"
    try:
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem safety
        LOGGER.warning("Unable to write target metadata: %s", exc)


class _TargetWatcher:
    def __init__(
        self,
        event_logger: EventLogger,
        artifacts: ArtifactPaths,
        *,
        interval_seconds: float = 0.5,
    ) -> None:
        self._event_logger = event_logger
        self._artifacts = artifacts
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: TargetInfo | None = None
        self._change_count = 0

    def start(self, initial: TargetInfo | None) -> None:
        self._last = initial
        self._thread = threading.Thread(
            target=self._loop, name="runner-target-watch", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    @property
    def change_count(self) -> int:
        return self._change_count

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            current = detect_foreground_target()
            if _target_changed(self._last, current):
                self._last = current
                self._change_count += 1
                self._log_target_event("target_changed", current)
            if self._stop_event.wait(self._interval_seconds):
                return

    def _log_target_event(self, event: str, target: TargetInfo | None) -> None:
        message = format_target_message(target)
        self._event_logger.log(event, message)


def _target_changed(previous: TargetInfo | None, current: TargetInfo | None) -> bool:
    if previous is None and current is None:
        return False
    if previous is None or current is None:
        return True
    return (
        previous.hwnd != current.hwnd
        or previous.pid != current.pid
        or previous.exe_path != current.exe_path
        or previous.window_title != current.window_title
    )


def ensure_capture_mode_selection(env: MutableMapping[str, str]) -> None:
    run_mode = env.get("RUN_MODE", "").strip().lower()
    if run_mode != "human":
        return
    if env.get("RUNNER_CAPTURE_MODE"):
        return
    choice_map = {
        "1": "off",
        "2": "unity_window",
        "3": "desktop",
    }
    if not sys.stdin or not sys.stdin.isatty():
        LOGGER.info(
            "Capture selection prompt skipped (non-interactive). Defaulting to unity_window"
        )
        env["RUNNER_CAPTURE_MODE"] = "unity_window"
        env.setdefault("RUNNER_SCREENSHOTS", "1")
        env["RUNNER_SCREENSHOT_TARGET"] = "unity_window"
        return
    print(
        "".join(
            [
                "Select capture mode before starting the human-observed run:\n",
                "  1) OFF (no screenshots)\n",
                "  2) UNITY WINDOW ONLY (default)\n",
                "  3) FULL DESKTOP\n",
            ]
        )
    )
    while True:
        response = input("Capture selection [default 2]: ").strip() or "2"
        if response in choice_map:
            capture_mode = choice_map[response]
            break
        print("Please enter 1, 2, or 3.")
    env["RUNNER_CAPTURE_MODE"] = capture_mode
    if capture_mode == "off":
        env["RUNNER_SCREENSHOTS"] = "0"
    else:
        env["RUNNER_SCREENSHOTS"] = "1"
        env["RUNNER_SCREENSHOT_TARGET"] = (
            "desktop" if capture_mode == "desktop" else "unity_window"
        )
    LOGGER.info("Capture mode selected: %s", capture_mode)


def _prepare_config(config: RunnerConfig) -> None:
    plan: ScenarioPlan | None = None
    if config.scenario_id:
        plan = load_scenario_plan(config.scenarios_file, config.scenario_id)
    if config.no_launch and config.run_mode != "human":
        raise RunnerScenarioError("--no-launch is only supported in human mode")
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

    if config.run_mode == "human":
        config.episode_labels = _merge_labels(
            config.episode_labels, ("human", "observed", "option-b")
        )
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


def _apply_plan_labels(
    config: RunnerConfig, plan_kind: str, scenario_label: str | None
) -> None:
    config.episode_labels = _merge_labels(
        config.episode_labels, ("option-b", f"plan:{plan_kind}")
    )
    if scenario_label:
        config.episode_labels = _merge_labels(
            config.episode_labels, (f"scenario:{scenario_label}",)
        )


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
    events_log = (
        str(result.events_log)
        if result.events_log and result.events_log.exists()
        else None
    )
    mark_count = (result.event_counts or {}).get("mark", 0)
    capture_mode = result.capture_mode or config.capture_mode
    metrics: Dict[str, Any] = {
        "duration_seconds": result.runtime_seconds,
        "exit_code": result.exit_code,
        "screenshots_captured": len(screenshots),
        "screenshots_target": config.screenshot_target,
        "screenshots_requested": config.screenshot_max_captures
        if config.screenshot_max_captures is not None
        else 0,
        "capture_mode": capture_mode,
        "events_mark_count": mark_count,
    }
    if result.launch_skipped:
        metrics["launch"] = "skipped"
        metrics["observe_only"] = True
    if result.capture_disabled_reason:
        metrics["capture_disabled_reason"] = result.capture_disabled_reason
    if result.capture_warnings:
        metrics["capture_warnings"] = result.capture_warnings
    metrics["input_logging"] = {
        "status": result.input_status,
        "message": result.input_status_message,
        "events_captured": result.input_events,
    }
    if result.input_log_path:
        metrics["input_logging"]["log_path"] = str(result.input_log_path)
    if result.input_warnings:
        metrics["input_logging"]["warnings"] = list(result.input_warnings)
    metrics["input_state_stream"] = {
        "status": result.input_state_status,
        "message": result.input_state_message,
        "frames": result.input_state_frames,
        "target_hz": result.input_state_target_hz,
        "effective_hz": result.input_state_effective_hz,
        "expected_frames": result.input_state_expected_frames,
    }
    if result.input_state_log_path:
        metrics["input_state_stream"]["log_path"] = str(result.input_state_log_path)
    if result.input_state_warnings:
        metrics["input_state_stream"]["warnings"] = list(result.input_state_warnings)

    target_payload: Dict[str, Any] = {}
    if result.target_pid is not None:
        target_payload["pid"] = result.target_pid
    if result.target_hwnd is not None:
        target_payload["hwnd"] = result.target_hwnd
    if result.target_exe_path:
        target_payload["exe_path"] = result.target_exe_path
    if result.target_process_name:
        target_payload["process_name"] = result.target_process_name
    if result.target_window_title:
        target_payload["window_title"] = result.target_window_title
    if result.target_label:
        target_payload["label"] = result.target_label
    if result.target_label_hash:
        target_payload["label_hash"] = result.target_label_hash

    payload: Dict[str, Any] = {
        "source": "unity-runner",
        "mode": config.run_mode,
        "status": result.status,
        "project": config.project_name,
        "build_id": config.build_id,
        "metrics": metrics,
        "target": target_payload,
        "artifacts": {
            "logs": logs,
            "screenshots": screenshots,
            "events": [events_log] if events_log else [],
        },
        "labels": list(config.episode_labels),
    }
    if config.run_mode == "human" and "human" not in payload["labels"]:
        payload["labels"].append("human")
    if config.scenario:
        scenario_payload = _build_scenario_payload(
            config.scenario, result, logs, screenshots
        )
        payload["scenario"] = scenario_payload
        metrics["scenario"] = copy.deepcopy(scenario_payload)
    elif config.run_mode == "human":
        payload["scenario"] = {"type": "human_observed", "notes": ""}
    if result.error:
        payload["error"] = result.error
    return payload


def _write_pending_episode(
    payload: Dict[str, Any], artifacts_dir: Path | None
) -> Path | None:
    if not artifacts_dir:
        LOGGER.warning("Cannot store pending episode; artifacts directory unknown")
        return None
    destination = artifacts_dir / "episode_pending.json"
    try:
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        LOGGER.info("Episode payload saved locally at %s", destination)
        return destination
    except OSError as exc:  # pragma: no cover - filesystem safety
        LOGGER.error("Unable to save pending episode: %s", exc)
    return None


def _write_episode_payload_file(
    payload: Dict[str, Any], artifacts_dir: Path | None
) -> Path | None:
    if not artifacts_dir:
        return None
    destination = artifacts_dir / "episode_payload.json"
    try:
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return destination
    except OSError as exc:  # pragma: no cover - filesystem safety
        LOGGER.warning("Unable to write episode payload file: %s", exc)
    return None


def _write_episode_response_file(
    post_result: EpisodePostResult, artifacts_dir: Path | None
) -> Path | None:
    if not artifacts_dir or not post_result.response:
        return None
    destination = artifacts_dir / "episode_response.json"
    try:
        destination.write_text(
            json.dumps(post_result.response, indent=2), encoding="utf-8"
        )
        return destination
    except OSError as exc:  # pragma: no cover - filesystem safety
        LOGGER.warning("Unable to write episode response file: %s", exc)
    return None


def execute_run(
    config: RunnerConfig,
    *,
    artifact_paths: ArtifactPaths | None = None,
    popen_cls=subprocess.Popen,
) -> RunResult:
    run_identifier = (
        artifact_paths.run_id if artifact_paths else _generate_run_identifier(config)
    )
    artifacts = artifact_paths or create_artifact_paths(
        config.artifacts_root, run_identifier
    )
    LOGGER.info("Artifacts stored in %s", artifacts.run_dir)
    event_logger = EventLogger(artifacts.events_log)
    lock_result = lock_target(
        mode=config.target_mode,
        lock_seconds=config.target_lock_seconds,
        poll_ms=config.target_poll_ms,
        ignore_processes=config.target_ignore,
        explicit_exe=config.target_exe,
        explicit_exe_path=config.target_exe_path,
        logger=event_logger.log,
    )
    canonical_target = lock_result.info if lock_result else None
    finalized_run_id = _apply_target_label_to_run_id(artifacts.run_id, lock_result)
    if finalized_run_id != artifacts.run_id:
        artifacts.update_run_id(finalized_run_id)
        event_logger.log_path = artifacts.events_log
    _write_target_metadata(artifacts, lock_result)
    target_watcher = _TargetWatcher(event_logger, artifacts)
    target_watcher.start(canonical_target)
    prefix = "screenshot"
    if lock_result:
        prefix = f"{lock_result.label}_screenshot"
    elif canonical_target and canonical_target.process_name:
        prefix = f"{sanitize_name(canonical_target.process_name)}_screenshot"
    recorder = ScreenshotRecorder(
        config.screenshot_interval_seconds,
        artifacts,
        config.screenshot_max_captures,
        capture_mode=config.capture_mode,
        event_logger=event_logger,
        filename_prefix=prefix,
    )
    input_logger: ControllerLogger | None = None
    input_summary = InputLoggingSummary.disabled("per config")
    if config.inputs_mode != "off" and config.run_mode == "human":
        input_logger = ControllerLogger(
            artifacts.inputs_log,
            poll_interval_ms=config.input_poll_interval_ms,
            deadzone=config.input_deadzone,
            axis_epsilon=config.input_axis_epsilon,
            event_logger=event_logger,
            backend_factory=resolve_backend_factory(config.input_backend),
        )
        if input_logger.start():
            input_summary = input_logger.summary()
        else:
            input_summary = input_logger.summary()
            input_logger = None
    elif config.inputs_mode != "off" and config.run_mode != "human":
        input_summary = InputLoggingSummary.disabled("non-human mode")

    state_logger: ControllerStateStreamLogger | None = None
    state_summary = ControllerStateStreamSummary.disabled("per config")
    if config.input_state_hz > 0 and config.run_mode == "human":
        dense_path = artifacts.dense_input_path(
            config.input_state_hz, config.input_state_format
        )
        state_logger = ControllerStateStreamLogger(
            dense_path,
            hz=config.input_state_hz,
            fmt=config.input_state_format,
            raw=config.input_state_raw,
            deadzone=config.input_deadzone,
            event_logger=event_logger,
            backend_factory=resolve_backend_factory(config.input_backend),
        )
        if state_logger.start():
            state_summary = state_logger.summary()
        else:
            state_summary = state_logger.summary()
            state_logger = None
    elif config.input_state_hz > 0 and config.run_mode != "human":
        state_summary = ControllerStateStreamSummary.disabled("non-human mode")

    hotkeys: HotkeyListener | None = None
    terminal_commands: TerminalCommandController | None = None
    stop_event = threading.Event()
    launch_skipped = False
    launch_reason: str | None = None

    def _on_process_started(process: subprocess.Popen) -> None:
        nonlocal hotkeys, terminal_commands
        pid = getattr(process, "pid", None)
        if pid is not None:
            recorder.attach_unity_pid(pid)
        else:
            LOGGER.debug("Process object missing pid; window capture disabled")
        recorder.start()
        if config.run_mode == "human":

            def _stop_from_hotkey() -> None:
                event_logger.log("manual_stop", "global hotkey stop")
                if process.poll() is None:
                    try:
                        process.terminate()
                    except Exception as exc:  # pragma: no cover - defensive
                        LOGGER.warning("Unable to terminate Unity: %s", exc)

            hotkeys = _start_hotkeys(
                event_logger, recorder, artifacts, on_stop=_stop_from_hotkey
            )
            on_mark, on_open, on_manual_shot = _build_run_actions(
                event_logger, recorder, artifacts, source="terminal"
            )

            def _stop_from_terminal() -> None:
                event_logger.log("manual_stop", "ENTER pressed; terminating Unity")
                if process.poll() is None:
                    try:
                        process.terminate()
                    except Exception as exc:  # pragma: no cover - defensive
                        LOGGER.warning("Unable to terminate Unity: %s", exc)

            terminal_commands = TerminalCommandController(
                on_mark=on_mark,
                on_open_artifacts=on_open,
                on_manual_screenshot=on_manual_shot,
                on_stop=_stop_from_terminal,
            )
            terminal_commands.start()

    error_message: str | None = None
    exit_code: int | None = None
    started_at = datetime.now(timezone.utc)
    start = time.monotonic()
    try:
        if config.no_launch:
            launch_skipped = True
            launch_reason = "observe-only"
            LOGGER.info("Launch skipped (observe-only)")
            artifacts.stdout_log.write_text("", encoding="utf-8")
            artifacts.stderr_log.write_text("", encoding="utf-8")
            recorder.start()
            if config.run_mode == "human":

                def _stop_observe_only() -> None:
                    event_logger.log(
                        "manual_stop", "ENTER pressed; ending observe-only"
                    )
                    stop_event.set()

                hotkeys = _start_hotkeys(
                    event_logger, recorder, artifacts, on_stop=_stop_observe_only
                )
                on_mark, on_open, on_manual_shot = _build_run_actions(
                    event_logger, recorder, artifacts, source="terminal"
                )

                terminal_commands = TerminalCommandController(
                    on_mark=on_mark,
                    on_open_artifacts=on_open,
                    on_manual_screenshot=on_manual_shot,
                    on_stop=_stop_observe_only,
                )
                terminal_commands.start()
            stop_event.wait(timeout=config.run_duration_seconds)
            exit_code = 0
        else:
            exit_code = _launch_unity_process(
                config,
                artifacts,
                popen_cls=popen_cls,
                on_process_started=_on_process_started,
            )
    except Exception as exc:  # pragma: no cover - defensive
        error_message = str(exc)
        LOGGER.exception("Unity process failed: %s", exc)
    finally:
        target_watcher.stop()
        recorder.stop()
        if hotkeys:
            hotkeys.stop()
        if terminal_commands:
            terminal_commands.stop()
        if input_logger:
            input_logger.stop()
            input_summary = input_logger.summary()
        if state_logger:
            state_logger.stop()
            state_summary = state_logger.summary()
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
        events_log=artifacts.events_log,
        event_counts=event_logger.counts(),
        capture_mode=recorder.effective_mode,
        capture_warnings=recorder.warnings,
        capture_disabled_reason=recorder.disabled_reason,
        launch_skipped=launch_skipped,
        launch_reason=launch_reason,
        input_status=input_summary.status,
        input_status_message=input_summary.message,
        input_events=input_summary.events_captured,
        input_log_path=input_summary.log_path,
        input_warnings=input_summary.warnings,
        input_state_status=state_summary.status,
        input_state_message=state_summary.message,
        input_state_frames=state_summary.frames,
        input_state_log_path=state_summary.log_path,
        input_state_warnings=state_summary.warnings,
        input_state_effective_hz=state_summary.effective_hz,
        input_state_target_hz=state_summary.target_hz,
        input_state_expected_frames=state_summary.expected_frames,
        target_hwnd=canonical_target.hwnd if canonical_target else None,
        target_pid=canonical_target.pid if canonical_target else None,
        target_exe_path=canonical_target.exe_path if canonical_target else None,
        target_process_name=canonical_target.process_name if canonical_target else None,
        target_window_title=canonical_target.window_title if canonical_target else None,
        target_change_count=target_watcher.change_count,
        target_label=lock_result.label if lock_result else None,
        target_label_hash=lock_result.hash_suffix if lock_result else None,
    )


def _launch_unity_process(
    config: RunnerConfig,
    artifacts: ArtifactPaths,
    *,
    popen_cls,
    on_process_started: Callable[[subprocess.Popen], None] | None = None,
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
        if on_process_started:
            on_process_started(process)
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


def _format_command(argv: Sequence[str] | None) -> str:
    parts = ["python -m runner.run_unity"]
    cli = argv if argv is not None else sys.argv[1:]
    if cli:
        parts.append(" ".join(shlex.quote(arg) for arg in cli))
    return "".join(parts)


def _collect_env_summary(env: Mapping[str, str]) -> Dict[str, str]:
    summary: Dict[str, str] = {}
    for key in REPORT_ENV_KEYS:
        value = env.get(key)
        if value:
            summary[key] = value
    return summary


def _plan_metadata(plan: RunPlan) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    if plan.scenarios:
        if plan.kind == "queue":
            metadata["scenarios"] = ",".join(plan.scenarios)
        else:
            metadata["scenario"] = plan.scenarios[0]
    if plan.kind == "schedule":
        if plan.every_minutes:
            metadata["every_minutes"] = str(plan.every_minutes)
        if plan.max_runs:
            metadata["max_runs"] = str(plan.max_runs)
        if plan.duration_minutes:
            metadata["duration_minutes"] = str(plan.duration_minutes)
    return metadata


def _execute_plan(
    plan: RunPlan,
    base_env: Mapping[str, str],
    command: str,
    env_summary: Dict[str, str],
    metadata: Dict[str, str],
) -> PlanReportSummary:
    started_at = datetime.now(timezone.utc)
    runs: List[RunReportRow] = []
    stop_reason: str | None = None
    run_counter = 0

    def _record_run(scenario_override: str | None) -> bool:
        nonlocal run_counter
        run_counter += 1
        record, success = _execute_single_run(
            base_env, plan.kind, scenario_override, run_counter
        )
        runs.append(record)
        return success

    if plan.kind == "single":
        scenario = plan.scenarios[0] if plan.scenarios else None
        success = _record_run(scenario)
        if plan.stop_on_fail and not success:
            stop_reason = "stop-on-fail"
    elif plan.kind == "queue":
        for scenario in plan.scenarios:
            success = _record_run(scenario)
            if plan.stop_on_fail and not success:
                stop_reason = "stop-on-fail"
                break
    else:  # schedule
        scenario = plan.scenarios[0] if plan.scenarios else None
        interval_seconds = (plan.every_minutes or 0) * 60
        schedule_started = time.monotonic()
        while True:
            success = _record_run(scenario)
            if plan.stop_on_fail and not success:
                stop_reason = "stop-on-fail"
                break
            if plan.max_runs and run_counter >= plan.max_runs:
                stop_reason = "max-runs"
                break
            if plan.duration_minutes:
                elapsed_minutes = (time.monotonic() - schedule_started) / 60
                if elapsed_minutes >= plan.duration_minutes:
                    stop_reason = "duration-elapsed"
                    break
            if not plan.every_minutes:
                break
            LOGGER.info(
                "Waiting %s minute(s) before next scheduled run",
                plan.every_minutes,
            )
            time.sleep(interval_seconds)

    finished_at = datetime.now(timezone.utc)
    rendered_metadata = dict(metadata)
    if stop_reason:
        rendered_metadata["stop_reason"] = stop_reason
    return PlanReportSummary(
        plan_kind=plan.kind,
        runs=runs,
        command=command,
        env_summary=env_summary,
        metadata=rendered_metadata,
        started_at=started_at,
        finished_at=finished_at,
        stop_on_fail=plan.stop_on_fail,
    )


def _execute_single_run(
    base_env: Mapping[str, str],
    plan_kind: str,
    scenario_override: str | None,
    run_index: int,
) -> tuple[RunReportRow, bool]:
    overrides: Dict[str, str | None] = {}
    if scenario_override is not None:
        overrides["SCENARIO_ID"] = scenario_override
    artifacts = _prepare_artifacts(base_env)
    debug = _debug_enabled(None, base_env)
    if not logging.getLogger().handlers:
        _configure_logging(debug)
    if debug:
        LOGGER.debug(
            "Preflight artifacts ready for run %s: %s",
            run_index,
            artifacts.run_dir if artifacts else "unavailable",
        )
    with _attach_error_log(artifacts.stderr_log if artifacts else None):
        try:
            config = _load_prepared_config(base_env, overrides)
        except RunnerScenarioError as exc:
            message = f"Scenario error: {exc}"
            LOGGER.error(message)
            if debug:
                LOGGER.debug("Scenario error details", exc_info=True)
            _write_failure_details(message, artifacts=artifacts, exc=exc)
            return (
                _build_failed_run_record(
                    base_env,
                    plan_kind,
                    scenario_override,
                    run_index,
                    message,
                    artifacts=artifacts,
                ),
                False,
            )
        except RunnerConfigError as exc:
            message = f"Configuration error: {exc}"
            LOGGER.error(message)
            if debug:
                LOGGER.debug("Configuration error details", exc_info=True)
            _write_failure_details(message, artifacts=artifacts, exc=exc)
            return (
                _build_failed_run_record(
                    base_env,
                    plan_kind,
                    scenario_override,
                    run_index,
                    message,
                    artifacts=artifacts,
                ),
                False,
            )

    scenario_label = _scenario_label_from_config(config, scenario_override)
    _apply_plan_labels(config, plan_kind, scenario_label)
    if debug:
        LOGGER.debug(
            "Prepared config for run %s (mode=%s, scenario=%s)",
            run_index,
            config.run_mode,
            scenario_label or "none",
        )

    result = execute_run(config, artifact_paths=artifacts)
    payload = build_episode_payload(config, result)
    result.episode_payload_path = _write_episode_payload_file(
        payload, result.artifacts_dir
    )
    post_result = post_episode(payload, config)
    if post_result.success:
        result.episode_response_path = _write_episode_response_file(
            post_result, result.artifacts_dir
        )
    pending_path = None
    if not post_result.success:
        pending_path = _write_pending_episode(payload, result.artifacts_dir)
        if post_result.skipped:
            LOGGER.info("Episode POST skipped: %s", post_result.skip_reason)
        else:
            LOGGER.error("Failed to post Unity episode to AI-E")
    record = _build_run_record(
        run_index,
        plan_kind,
        scenario_label,
        config,
        result,
        post_result,
        pending_path,
    )
    success = (post_result.success or post_result.skipped) and result.status == "pass"
    return record, success


def _build_run_actions(
    event_logger: EventLogger,
    recorder: ScreenshotRecorder,
    artifacts: ArtifactPaths,
    *,
    source: str,
) -> tuple[Callable[[], None], Callable[[], None], Callable[[], None]]:
    def _mark() -> None:
        event_logger.log("mark", f"{source} mark")
        LOGGER.info("MARK recorded (%s total)", event_logger.count("mark"))

    def _open() -> None:
        event_logger.log("open_artifacts", str(artifacts.run_dir))
        open_artifacts_folder(artifacts.run_dir)

    def _manual_shot() -> None:
        path = recorder.capture_now(label=source)
        if path:
            event_logger.log("manual_screenshot", f"{source} screenshot")
            LOGGER.info("Manual screenshot saved at %s", path)
        else:
            LOGGER.info("Manual screenshot skipped (capture unavailable)")

    return _mark, _open, _manual_shot


def _start_hotkeys(
    event_logger: EventLogger,
    recorder: ScreenshotRecorder,
    artifacts: ArtifactPaths,
    *,
    on_stop: Callable[[], None] | None = None,
) -> object:
    on_mark, on_open, on_manual_shot = _build_run_actions(
        event_logger, recorder, artifacts, source="hotkey"
    )
    console_listener = HotkeyListener(
        on_mark=on_mark,
        on_open_artifacts=on_open,
        on_manual_screenshot=on_manual_shot,
    )
    global_listener = GlobalHotkeyListener(
        on_mark=on_mark,
        on_open_artifacts=on_open,
        on_manual_screenshot=on_manual_shot,
        on_stop=on_stop,
    )
    console_listener.start()
    global_listener.start()

    class _HotkeyBundle:
        def stop(self) -> None:
            console_listener.stop()
            global_listener.stop()

    return _HotkeyBundle()


def _dispatch_report_email(
    summary: PlanReportSummary,
    report_path: Path,
    run_dirs: List[Path],
    project_name: str,
) -> str:
    if not any(row.mode == "human" for row in summary.runs):
        return "SKIPPED (non-human run)"
    config = load_email_config(os.environ)
    if not config:
        return "SKIPPED (not configured)"
    subject = "AI-E Human Run Report — {project} — {timestamp}".format(
        project=project_name or "unknown",
        timestamp=summary.finished_at.astimezone(timezone.utc).strftime(
            "%Y-%m-%d %H:%M %Z"
        ),
    )
    artifacts_block = (
        "\n".join(f"- {path}" for path in run_dirs)
        if run_dirs
        else "- (no artifacts recorded)"
    )
    excerpt = _report_excerpt(report_path)
    body = textwrap.dedent(
        f"""
        Project: {project_name or 'unknown'}
        Runs: PASS {summary.successes()} / FAIL {summary.failures()} / TOTAL {len(summary.runs)}

        Artifacts:
        {artifacts_block}

        Latest report excerpt:
        {excerpt}
        """
    ).strip()
    email_result: EmailResult = send_email(
        config,
        subject=subject,
        body=body,
        attachment=report_path,
    )
    if email_result.success:
        LOGGER.info("Summary email sent to %s", config.to_address)
        return "SENT"
    if email_result.attempted:
        LOGGER.warning("Summary email failed: %s", email_result.message)
        return f"FAILED ({email_result.message})"
    return email_result.message


def _report_excerpt(report_path: Path, tail_lines: int = 10) -> str:
    if not report_path.exists():
        return "(report file missing)"
    lines = report_path.read_text(encoding="utf-8").splitlines()
    snippet = lines[-tail_lines:] if lines else []
    return "\n".join(snippet) if snippet else "(report file empty)"


def _rewrite_reports(
    summary: PlanReportSummary,
    last_report_path: Path,
    archive_path: Path,
    run_dirs: List[Path],
) -> None:
    report_text = render_report(summary)
    for path in (last_report_path, archive_path):
        try:
            path.write_text(report_text, encoding="utf-8")
        except OSError as exc:  # pragma: no cover - filesystem safety
            LOGGER.warning("Unable to update report file %s: %s", path, exc)
    for dir_path in run_dirs:
        destination = dir_path / "report_last_run.md"
        try:
            destination.write_text(report_text, encoding="utf-8")
        except OSError as exc:  # pragma: no cover - filesystem safety
            LOGGER.warning("Unable to update run report copy %s: %s", destination, exc)


def _load_prepared_config(
    base_env: Mapping[str, str], overrides: Mapping[str, str | None]
) -> RunnerConfig:
    merged_env = dict(base_env)
    for key, value in overrides.items():
        if value is None:
            merged_env.pop(key, None)
        else:
            merged_env[key] = value
    config = load_runner_config(merged_env)
    _prepare_config(config)
    return config


def _build_run_record(
    run_index: int,
    plan_kind: str,
    scenario_label: str | None,
    config: RunnerConfig,
    result: RunResult,
    post_result: EpisodePostResult,
    pending_path: Path | None,
) -> RunReportRow:
    run_id = result.artifacts_dir.name if result.artifacts_dir else None
    log_paths = [str(path) for path in result.logs if path.exists()]
    screenshot_paths = [str(path) for path in result.screenshots if path.exists()]
    return RunReportRow(
        index=run_index,
        run_id=run_id,
        plan_kind=plan_kind,
        scenario_id=scenario_label,
        mode=config.run_mode,
        status=result.status,
        exit_code=result.exit_code,
        runtime_seconds=result.runtime_seconds,
        episode_id=post_result.episode_id,
        episode_post_success=post_result.success,
        episode_post_status=_format_post_status(post_result),
        episode_post_skipped_reason=post_result.skip_reason,
        artifacts_dir=result.artifacts_dir,
        pending_episode_path=pending_path,
        episode_payload_path=result.episode_payload_path,
        episode_response_path=result.episode_response_path,
        launch_skipped=result.launch_skipped,
        launch_reason=result.launch_reason,
        screenshots=screenshot_paths,
        screenshot_target=config.screenshot_target,
        screenshots_captured=len(screenshot_paths),
        screenshots_requested=config.screenshot_max_captures,
        build_id=config.build_id,
        started_at=result.started_at,
        finished_at=result.finished_at,
        logs=log_paths,
        error=result.error,
        api_error=post_result.error,
        events_log=result.events_log,
        events_mark_count=(result.event_counts or {}).get("mark", 0),
        capture_mode=result.capture_mode or config.capture_mode,
        capture_disabled_reason=result.capture_disabled_reason,
        capture_warnings=result.capture_warnings or [],
        input_status=result.input_status,
        input_status_message=result.input_status_message,
        input_events_captured=result.input_events,
        input_log_path=result.input_log_path,
        input_warnings=result.input_warnings or [],
        input_state_status=result.input_state_status,
        input_state_message=result.input_state_message,
        input_state_frames=result.input_state_frames,
        input_state_log_path=result.input_state_log_path,
        input_state_effective_hz=result.input_state_effective_hz or 0.0,
        input_state_target_hz=result.input_state_target_hz or 0,
        input_state_expected_frames=result.input_state_expected_frames or 0,
        input_state_warnings=result.input_state_warnings or [],
        target_hwnd=result.target_hwnd,
        target_pid=result.target_pid,
        target_exe_path=result.target_exe_path,
        target_process_name=result.target_process_name,
        target_window_title=result.target_window_title,
        target_change_count=result.target_change_count,
        target_label=result.target_label,
        target_label_hash=result.target_label_hash,
    )


def _build_failed_run_record(
    base_env: Mapping[str, str],
    plan_kind: str,
    scenario_label: str | None,
    run_index: int,
    error_message: str,
    *,
    artifacts: ArtifactPaths | None = None,
) -> RunReportRow:
    timestamp = datetime.now(timezone.utc).isoformat()
    logs: List[str] = []
    artifacts_dir = None
    if artifacts:
        artifacts_dir = artifacts.run_dir
        logs = [
            str(path)
            for path in (artifacts.stdout_log, artifacts.stderr_log)
            if path.exists()
        ]
    return RunReportRow(
        index=run_index,
        run_id=None,
        plan_kind=plan_kind,
        scenario_id=scenario_label,
        mode=base_env.get("RUN_MODE", "freestyle"),
        status="error",
        exit_code=None,
        runtime_seconds=0.0,
        episode_id=None,
        episode_post_success=False,
        episode_post_status="not-posted",
        episode_post_skipped_reason=None,
        artifacts_dir=artifacts_dir,
        pending_episode_path=None,
        episode_payload_path=None,
        episode_response_path=None,
        launch_skipped=False,
        launch_reason=None,
        screenshots=[],
        screenshot_target=base_env.get("RUNNER_SCREENSHOT_TARGET", "unity_window"),
        screenshots_captured=0,
        screenshots_requested=None,
        build_id=base_env.get("BUILD_ID", "unknown"),
        started_at=timestamp,
        finished_at=timestamp,
        logs=logs,
        error=error_message,
        api_error=error_message,
        events_log=None,
        events_mark_count=0,
        capture_mode=base_env.get("RUNNER_CAPTURE_MODE", "off"),
        capture_disabled_reason="not-started",
        capture_warnings=[],
        input_status="OFF",
        input_status_message="not-started",
        input_events_captured=0,
        input_log_path=None,
        input_warnings=[],
        input_state_status="OFF",
        input_state_message="not-started",
        input_state_frames=0,
        input_state_log_path=None,
        input_state_effective_hz=0.0,
        input_state_target_hz=0,
        input_state_expected_frames=0,
        input_state_warnings=[],
    )


def _format_post_status(result: EpisodePostResult) -> str:
    if result.skipped:
        return "skipped"
    if result.status_code:
        return f"HTTP {result.status_code}"
    if result.success:
        return "posted"
    if result.error:
        return result.error
    return "failed"


def _scenario_label_from_config(
    config: RunnerConfig, scenario_override: str | None
) -> str | None:
    if scenario_override:
        return scenario_override
    if config.scenario and config.scenario.get("scenario_id"):
        return str(config.scenario["scenario_id"])
    return config.scenario_id


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    apply_cli_overrides(args)
    debug = _debug_enabled(args, os.environ)
    _configure_logging(debug)
    global _BOOTSTRAP_ARTIFACTS
    _BOOTSTRAP_ARTIFACTS = _prepare_artifacts(os.environ)
    if debug:
        LOGGER.debug("Parsed args and applied CLI overrides")
        LOGGER.debug(
            "Bootstrap artifacts: %s",
            _BOOTSTRAP_ARTIFACTS.run_dir if _BOOTSTRAP_ARTIFACTS else "unavailable",
        )
        faulthandler.enable()
    with _attach_error_log(
        _BOOTSTRAP_ARTIFACTS.stderr_log if _BOOTSTRAP_ARTIFACTS else None
    ):
        ensure_capture_mode_selection(os.environ)
        try:
            plan = build_run_plan(args)
        except RunPlanError as exc:
            message = f"Invalid run plan: {exc}"
            LOGGER.error(message)
            _write_failure_details(
                message,
                artifacts=_BOOTSTRAP_ARTIFACTS,
                exc=exc,
            )
            return 1
        if debug:
            LOGGER.debug("Run plan ready: %s", plan.kind)

        base_env = dict(os.environ)
        command = _format_command(argv)
        env_summary = _collect_env_summary(base_env)
        metadata = _plan_metadata(plan)
        summary = _execute_plan(plan, base_env, command, env_summary, metadata)
        run_dirs = [row.artifacts_dir for row in summary.runs if row.artifacts_dir]
        last_report_path, archive_path = write_reports(summary, copies=run_dirs)
        project_name = env_summary.get("PROJECT_NAME", "unknown")
        email_status = _dispatch_report_email(
            summary, last_report_path, run_dirs, project_name
        )
        summary.metadata["email"] = email_status
        _rewrite_reports(summary, last_report_path, archive_path, run_dirs)
        return 0 if summary.failures() == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover - last-resort logging
        print(f"Runner crashed: {exc}", file=sys.stderr)
        traceback.print_exc()
        _write_failure_details(
            f"Runner crashed: {exc}",
            artifacts=_BOOTSTRAP_ARTIFACTS,
            exc=exc,
        )
        sys.exit(1)
