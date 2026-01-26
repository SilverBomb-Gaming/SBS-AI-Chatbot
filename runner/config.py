"""Configuration helpers for the Unity runner."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

LOGGER = logging.getLogger(__name__)
ALLOWED_RUN_MODES = {"freestyle", "instructed", "breaker", "c1", "human"}
DEFAULT_RUN_DURATION = 300
DEFAULT_POSTER_TIMEOUT = 15
DEFAULT_MAX_SHUTDOWN_SECONDS = 15
DEFAULT_ARTIFACTS_DIR = Path.cwd() / "runner_artifacts"
DEFAULT_SCREENSHOT_INTERVAL_SECONDS = 5
DEFAULT_EPISODE_LABELS = ("harness", "option-a")
DEFAULT_SCENARIOS_FILE = Path(__file__).resolve().parent / "scenarios.json"
DEFAULT_SCREENSHOT_TARGET = "unity_window"
ALLOWED_SCREENSHOT_TARGETS = {"unity_window", "desktop"}
ALLOWED_CAPTURE_MODES = {"off", "unity_window", "desktop"}
DEFAULT_CAPTURE_MODE = "unity_window"
ALLOWED_INPUT_MODES = {"off", "controller"}
DEFAULT_INPUT_MODE = "off"
DEFAULT_INPUT_POLL_INTERVAL_MS = 16
DEFAULT_INPUT_DEADZONE = 0.12
DEFAULT_INPUT_AXIS_EPSILON = 0.02
ALLOWED_INPUT_BACKENDS = {"auto", "xinput", "stub"}
DEFAULT_INPUT_BACKEND = "auto"
DEFAULT_TARGET_MODE = "first-non-terminal"
DEFAULT_TARGET_LOCK_SECONDS = 10
DEFAULT_TARGET_IGNORE = [
    "powershell.exe",
    "windowsterminal.exe",
    "cmd.exe",
    "conhost.exe",
    "python.exe",
    "code.exe",
    "devenv.exe",
]
ALLOWED_TARGET_MODES = {"foreground-at-start", "first-non-terminal", "exe"}
BASE_URL_ENV_KEYS = ("AI_E_BASE_URL", "API_BASE_URL", "SERVER_URL")
PLACEHOLDER_BASE_HOSTS = {"example.com", "www.example.com"}


class RunnerConfigError(Exception):
    """Raised when runner configuration is invalid."""


@dataclass
class RunnerConfig:
    unity_executable: Path
    run_duration_seconds: int
    screenshot_interval_seconds: int | None
    ai_e_base_url: str | None
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
    screenshot_target: str = DEFAULT_SCREENSHOT_TARGET
    capture_mode: str = DEFAULT_CAPTURE_MODE
    no_launch: bool = False
    inputs_mode: str = DEFAULT_INPUT_MODE
    input_poll_interval_ms: int = DEFAULT_INPUT_POLL_INTERVAL_MS
    input_deadzone: float = DEFAULT_INPUT_DEADZONE
    input_axis_epsilon: float = DEFAULT_INPUT_AXIS_EPSILON
    input_backend: str = DEFAULT_INPUT_BACKEND
    target_mode: str = DEFAULT_TARGET_MODE
    target_lock_seconds: int = DEFAULT_TARGET_LOCK_SECONDS
    target_ignore: tuple[str, ...] = tuple(DEFAULT_TARGET_IGNORE)
    target_exe: str | None = None

    def episodes_endpoint(self) -> str:
        if not self.ai_e_base_url:
            raise RunnerConfigError("AI_E_BASE_URL is required to post episodes")
        base = self.ai_e_base_url.rstrip("/") + "/"
        return urljoin(base, "/api/episodes")


def load_runner_config(env: Mapping[str, str] | None = None) -> RunnerConfig:
    """Load environment variables into a RunnerConfig."""
    env = env or os.environ

    no_launch_flag = (
        _parse_optional_bool(env.get("RUNNER_NO_LAUNCH"), "RUNNER_NO_LAUNCH") is True
    )
    unity_path = _parse_optional_path(env.get("UNITY_EXE_PATH"))
    if not no_launch_flag:
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
    screenshot_flag = _parse_optional_bool(
        env.get("RUNNER_SCREENSHOTS"), "RUNNER_SCREENSHOTS"
    )

    if runner_interval is not None:
        screenshot_interval = runner_interval
    if runner_limit is not None:
        screenshot_limit = runner_limit
    raw_base_url = _resolve_base_url(env)
    ai_e_base_url = _parse_base_url(raw_base_url)
    if raw_base_url and ai_e_base_url is None:
        LOGGER.warning(
            "API base URL appears to be a placeholder (%s); episode posting disabled",
            raw_base_url,
        )
    if ai_e_base_url:
        api_key = _require_non_empty(env.get("AI_E_API_KEY"), "AI_E_API_KEY")
    else:
        api_key = _optional_string(env.get("AI_E_API_KEY")) or ""
    project = _require_non_empty(env.get("PROJECT_NAME"), "PROJECT_NAME")
    run_mode = _parse_run_mode(env.get("RUN_MODE"))
    build_id = _require_non_empty(env.get("BUILD_ID"), "BUILD_ID")
    scenario_id = _optional_string(env.get("SCENARIO_ID"))
    scenarios_file = _parse_scenarios_file(env.get("SCENARIOS_FILE"))
    episode_labels = _parse_episode_labels(env.get("EPISODE_LABELS"))
    capture_override = _parse_capture_mode(env.get("RUNNER_CAPTURE_MODE"))
    screenshot_target = _parse_screenshot_target(env.get("RUNNER_SCREENSHOT_TARGET"))

    artifacts_root = DEFAULT_ARTIFACTS_DIR

    screenshots_opt_out = screenshot_flag is False
    if screenshot_flag is False:
        screenshot_interval = None
        screenshot_limit = None
    elif screenshot_flag is True:
        screenshot_interval = screenshot_interval or DEFAULT_SCREENSHOT_INTERVAL_SECONDS

    capture_mode = _determine_capture_mode(
        capture_override, screenshot_flag, screenshot_target
    )
    if capture_mode == "off":
        screenshot_interval = None
        screenshot_limit = None

    inputs_mode = _determine_input_mode(env.get("RUNNER_INPUTS"), run_mode)
    poll_override = _parse_optional_positive_int(
        env.get("RUNNER_INPUT_POLL_MS"), "RUNNER_INPUT_POLL_MS"
    )
    input_poll_interval_ms = poll_override or DEFAULT_INPUT_POLL_INTERVAL_MS
    deadzone_override = _parse_optional_float(
        env.get("RUNNER_INPUT_DEADZONE"),
        "RUNNER_INPUT_DEADZONE",
        minimum=0.0,
        maximum=1.0,
    )
    axis_override = _parse_optional_float(
        env.get("RUNNER_INPUT_AXIS_EPSILON"),
        "RUNNER_INPUT_AXIS_EPSILON",
        minimum=0.0,
        maximum=1.0,
    )
    input_deadzone = (
        deadzone_override if deadzone_override is not None else DEFAULT_INPUT_DEADZONE
    )
    input_axis_epsilon = (
        axis_override if axis_override is not None else DEFAULT_INPUT_AXIS_EPSILON
    )
    input_backend = _parse_input_backend(env.get("RUNNER_INPUTS_BACKEND"))
    target_mode = _parse_target_mode(env.get("RUNNER_TARGET_MODE"))
    lock_override = _parse_optional_positive_int(
        env.get("RUNNER_TARGET_LOCK_SECONDS"), "RUNNER_TARGET_LOCK_SECONDS"
    )
    target_lock_seconds = lock_override or DEFAULT_TARGET_LOCK_SECONDS
    target_ignore = _parse_target_ignore(env.get("RUNNER_TARGET_IGNORE"))
    target_exe = _optional_string(env.get("RUNNER_TARGET_EXE"))

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
        screenshot_target=screenshot_target,
        capture_mode=capture_mode,
        no_launch=no_launch_flag,
        inputs_mode=inputs_mode,
        input_poll_interval_ms=input_poll_interval_ms,
        input_deadzone=input_deadzone,
        input_axis_epsilon=input_axis_epsilon,
        input_backend=input_backend,
        target_mode=target_mode,
        target_lock_seconds=target_lock_seconds,
        target_ignore=target_ignore,
        target_exe=target_exe,
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


def _parse_optional_non_negative_int(
    raw_value: str | None, env_name: str
) -> int | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RunnerConfigError(f"{env_name} must be an integer") from exc
    if value < 0:
        raise RunnerConfigError(f"{env_name} must be zero or positive")
    return value


def _parse_optional_bool(raw_value: str | None, env_name: str) -> bool | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RunnerConfigError(f"{env_name} must be a boolean (0/1, true/false)")


def _parse_optional_path(raw_value: str | None) -> Path:
    if not raw_value or not raw_value.strip():
        return Path.cwd()
    return Path(raw_value).expanduser().resolve()


def _resolve_base_url(env: Mapping[str, str]) -> str | None:
    for key in BASE_URL_ENV_KEYS:
        value = env.get(key)
        if value and value.strip():
            return value.strip()
    return None


def _is_placeholder_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    return host in PLACEHOLDER_BASE_HOSTS or host.endswith(".example.com")


def _parse_base_url(raw_value: str | None) -> str | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    base = raw_value.strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"}:
        raise RunnerConfigError("AI_E_BASE_URL must include http or https scheme")
    if not parsed.netloc:
        raise RunnerConfigError("AI_E_BASE_URL must include a hostname")
    if _is_placeholder_base_url(base):
        return None
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


def _parse_screenshot_target(raw_value: str | None) -> str:
    if not raw_value or not raw_value.strip():
        return DEFAULT_SCREENSHOT_TARGET
    candidate = raw_value.strip().lower()
    if candidate not in ALLOWED_SCREENSHOT_TARGETS:
        allowed = ", ".join(sorted(ALLOWED_SCREENSHOT_TARGETS))
        LOGGER.warning(
            "Invalid RUNNER_SCREENSHOT_TARGET '%s'; allowed values: %s. Falling back to %s",
            candidate,
            allowed,
            DEFAULT_SCREENSHOT_TARGET,
        )
        return DEFAULT_SCREENSHOT_TARGET
    return candidate


def _parse_capture_mode(raw_value: str | None) -> str | None:
    if not raw_value or not raw_value.strip():
        return None
    candidate = raw_value.strip().lower()
    if candidate not in ALLOWED_CAPTURE_MODES:
        LOGGER.warning(
            "Invalid RUNNER_CAPTURE_MODE '%s'; allowed values: %s (ignored)",
            candidate,
            ", ".join(sorted(ALLOWED_CAPTURE_MODES)),
        )
        return None
    return candidate


def _determine_capture_mode(
    override: str | None,
    screenshot_flag: bool | None,
    screenshot_target: str,
) -> str:
    if override:
        return override
    if screenshot_flag is False:
        return "off"
    if screenshot_flag is True:
        return "desktop" if screenshot_target == "desktop" else "unity_window"
    if screenshot_target == "desktop":
        return "desktop"
    return DEFAULT_CAPTURE_MODE


def _determine_input_mode(raw_value: str | None, run_mode: str) -> str:
    default = "controller" if run_mode == "human" else DEFAULT_INPUT_MODE
    if not raw_value or not raw_value.strip():
        return default
    candidate = raw_value.strip().lower()
    if candidate not in ALLOWED_INPUT_MODES:
        LOGGER.warning(
            "Invalid RUNNER_INPUTS '%s'; allowed: %s. Falling back to %s",
            candidate,
            ", ".join(sorted(ALLOWED_INPUT_MODES)),
            default,
        )
        return default
    return candidate


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


def _parse_optional_float(
    raw_value: str | None,
    env_name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RunnerConfigError(f"{env_name} must be a number") from exc
    if minimum is not None and value < minimum:
        raise RunnerConfigError(
            f"{env_name} must be greater than or equal to {minimum}"
        )
    if maximum is not None and value > maximum:
        raise RunnerConfigError(f"{env_name} must be less than or equal to {maximum}")
    return value


def _parse_input_backend(raw_value: str | None) -> str:
    if not raw_value or not raw_value.strip():
        return DEFAULT_INPUT_BACKEND
    candidate = raw_value.strip().lower()
    if candidate not in ALLOWED_INPUT_BACKENDS:
        LOGGER.warning(
            "Invalid RUNNER_INPUTS_BACKEND '%s'; allowed: %s (using auto)",
            candidate,
            ", ".join(sorted(ALLOWED_INPUT_BACKENDS)),
        )
        return DEFAULT_INPUT_BACKEND
    return candidate


def _parse_target_mode(raw_value: str | None) -> str:
    if not raw_value or not raw_value.strip():
        return DEFAULT_TARGET_MODE
    candidate = raw_value.strip().lower()
    if candidate not in ALLOWED_TARGET_MODES:
        allowed = ", ".join(sorted(ALLOWED_TARGET_MODES))
        raise RunnerConfigError(f"RUNNER_TARGET_MODE must be one of: {allowed}")
    return candidate


def _parse_target_ignore(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value or not raw_value.strip():
        return tuple(DEFAULT_TARGET_IGNORE)
    parts = [piece.strip().lower() for piece in raw_value.split(",")]
    cleaned = [piece for piece in parts if piece]
    if not cleaned:
        return tuple(DEFAULT_TARGET_IGNORE)
    return tuple(dict.fromkeys(cleaned))
