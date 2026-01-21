"""Configuration helpers for the Unity runner."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

LOGGER = logging.getLogger(__name__)
ALLOWED_RUN_MODES = {"freestyle", "instructed", "breaker", "c1"}
DEFAULT_RUN_DURATION = 300
DEFAULT_POSTER_TIMEOUT = 15
DEFAULT_MAX_SHUTDOWN_SECONDS = 15
DEFAULT_ARTIFACTS_DIR = Path.cwd() / "runner_artifacts"
DEFAULT_SCREENSHOT_INTERVAL_SECONDS = 5
DEFAULT_EPISODE_LABELS = ("harness", "option-a")
DEFAULT_SCENARIOS_FILE = Path(__file__).resolve().parent / "scenarios.json"


class RunnerConfigError(Exception):
    """Raised when runner configuration is invalid."""


@dataclass
class RunnerConfig:
    unity_executable: Path
    run_duration_seconds: int
    screenshot_interval_seconds: int | None
    ai_e_base_url: str
    ai_e_api_key: str
    project_name: str
    run_mode: str
    build_id: str
    artifacts_root: Path
    max_shutdown_seconds: int = DEFAULT_MAX_SHUTDOWN_SECONDS
    poster_timeout_seconds: int = DEFAULT_POSTER_TIMEOUT
    episode_labels: tuple[str, ...] = DEFAULT_EPISODE_LABELS
    scenario_id: str | None = None
    scenario: dict[str, Any] | None = None
    scenario_overrides: dict[str, Any] | None = None
    scenarios_file: Path = DEFAULT_SCENARIOS_FILE
    screenshot_max_captures: int | None = None
    screenshots_opt_out: bool = False

    def episodes_endpoint(self) -> str:
        base = self.ai_e_base_url.rstrip("/") + "/"
        return urljoin(base, "api/episodes")


def load_runner_config(env: Mapping[str, str] | None = None) -> RunnerConfig:
    """Load environment variables into a RunnerConfig."""
    env = env or os.environ

    unity_path = _require_path(env.get("UNITY_EXE_PATH"), "UNITY_EXE_PATH")
    run_duration = _parse_positive_int(
        env.get("RUN_DURATION_SECONDS"), DEFAULT_RUN_DURATION, "RUN_DURATION_SECONDS"
    )
    screenshot_interval = _parse_optional_positive_int(
        env.get("SCREENSHOT_INTERVAL_SECONDS"), "SCREENSHOT_INTERVAL_SECONDS"
    )
    screenshot_limit = _parse_optional_non_negative_int(
        env.get("SCREENSHOT_MAX_CAPTURES"), "SCREENSHOT_MAX_CAPTURES"
    )
    runner_interval = _parse_optional_positive_int(
        env.get("RUNNER_SCREENSHOT_INTERVAL"), "RUNNER_SCREENSHOT_INTERVAL"
    )
    runner_limit = _parse_optional_non_negative_int(
        env.get("RUNNER_SCREENSHOT_MAX_CAPTURES"), "RUNNER_SCREENSHOT_MAX_CAPTURES"
    )
    screenshot_flag = _parse_optional_bool(env.get("RUNNER_SCREENSHOTS"))

    if runner_interval is not None:
        screenshot_interval = runner_interval
    if runner_limit is not None:
        screenshot_limit = runner_limit
    ai_e_base_url = _parse_base_url(env.get("AI_E_BASE_URL"))
    api_key = _require_non_empty(env.get("AI_E_API_KEY"), "AI_E_API_KEY")
    project = _require_non_empty(env.get("PROJECT_NAME"), "PROJECT_NAME")
    run_mode = _parse_run_mode(env.get("RUN_MODE"))
    build_id = _require_non_empty(env.get("BUILD_ID"), "BUILD_ID")
    scenario_id = _optional_string(env.get("SCENARIO_ID"))
    scenarios_file = _parse_scenarios_file(env.get("SCENARIOS_FILE"))
    episode_labels = _parse_episode_labels(env.get("EPISODE_LABELS"))

    artifacts_root = DEFAULT_ARTIFACTS_DIR

    screenshots_opt_out = screenshot_flag is False
    if screenshot_flag is False:
        screenshot_interval = None
        screenshot_limit = None
    elif screenshot_flag is True:
        screenshot_interval = screenshot_interval or DEFAULT_SCREENSHOT_INTERVAL_SECONDS

    return RunnerConfig(
        unity_executable=unity_path,
        run_duration_seconds=run_duration,
        screenshot_interval_seconds=screenshot_interval,
        ai_e_base_url=ai_e_base_url,
        ai_e_api_key=api_key,
        project_name=project,
        run_mode=run_mode,
        build_id=build_id,
        artifacts_root=artifacts_root,
        scenario_id=scenario_id,
        scenarios_file=scenarios_file,
        screenshot_max_captures=screenshot_limit,
        screenshots_opt_out=screenshots_opt_out,
        episode_labels=episode_labels,
    )


def redact_secret(value: str, visible: int = 4) -> str:
    """Redact sensitive values for logging."""
    if not value:
        return ""
    cleaned = value.strip()
    if len(cleaned) <= visible:
        return "*" * len(cleaned)
    hidden = "*" * (len(cleaned) - visible)
    return f"{hidden}{cleaned[-visible:]}"


def _require_path(raw_value: str | None, env_name: str) -> Path:
    path_value = _require_non_empty(raw_value, env_name)
    candidate = Path(path_value).expanduser().resolve()
    if not candidate.exists():
        raise RunnerConfigError(f"{env_name} path does not exist: {candidate}")
    if not candidate.is_file():
        raise RunnerConfigError(f"{env_name} must point to a file: {candidate}")
    return candidate


def _parse_positive_int(raw_value: str | None, default: int, env_name: str) -> int:
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RunnerConfigError(f"{env_name} must be an integer") from exc
    if value <= 0:
        raise RunnerConfigError(f"{env_name} must be greater than zero")
    return value


def _parse_optional_positive_int(raw_value: str | None, env_name: str) -> int | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RunnerConfigError(f"{env_name} must be an integer") from exc
    if value <= 0:
        LOGGER.warning("%s must be positive; screenshots disabled", env_name)
        return None
    return value


def _parse_optional_non_negative_int(raw_value: str | None, env_name: str) -> int | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RunnerConfigError(f"{env_name} must be an integer") from exc
    if value < 0:
        raise RunnerConfigError(f"{env_name} must be zero or positive")
    return value


def _parse_optional_bool(raw_value: str | None) -> bool | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RunnerConfigError("RUNNER_SCREENSHOTS must be a boolean (0/1, true/false)")


def _parse_base_url(raw_value: str | None) -> str:
    base = _require_non_empty(raw_value, "AI_E_BASE_URL").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"}:
        raise RunnerConfigError("AI_E_BASE_URL must include http or https scheme")
    if not parsed.netloc:
        raise RunnerConfigError("AI_E_BASE_URL must include a hostname")
    return base


def _require_non_empty(raw_value: str | None, env_name: str) -> str:
    if not raw_value or not raw_value.strip():
        raise RunnerConfigError(f"{env_name} is required")
    return raw_value.strip()


def _optional_string(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    value = raw_value.strip()
    return value or None


def _parse_run_mode(raw_value: str | None) -> str:
    value = _require_non_empty(raw_value, "RUN_MODE").strip().lower()
    if value not in ALLOWED_RUN_MODES:
        allowed = ", ".join(sorted(ALLOWED_RUN_MODES))
        raise RunnerConfigError(f"RUN_MODE must be one of: {allowed}")
    return value


def _parse_scenarios_file(raw_value: str | None) -> Path:
    if not raw_value or not raw_value.strip():
        return DEFAULT_SCENARIOS_FILE
    candidate = Path(raw_value).expanduser().resolve()
    if not candidate.exists():
        raise RunnerConfigError(f"SCENARIOS_FILE path does not exist: {candidate}")
    if not candidate.is_file():
        raise RunnerConfigError(f"SCENARIOS_FILE must point to a file: {candidate}")
    return candidate


def _parse_episode_labels(raw_value: str | None) -> tuple[str, ...]:
    if raw_value is None or raw_value.strip() == "":
        return DEFAULT_EPISODE_LABELS
    labels = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not labels:
        return DEFAULT_EPISODE_LABELS
    unique: list[str] = []
    for label in labels:
        if label not in unique:
            unique.append(label)
    return tuple(unique)
