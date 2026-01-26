"""Tests for the Unity runner helpers."""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from runner.capture import create_artifact_paths
from runner.config import RunnerConfig, load_runner_config
from runner.post_episode import EpisodePostResult
from runner.reporting import PlanReportSummary, RunReportRow
import runner.run_unity as run_unity
import runner.hotkeys as hotkeys
from runner.run_unity import (
    BREAKER_MAX_DURATION_SECONDS,
    BREAKER_SCREENSHOT_INTERVAL_SECONDS,
    RunnerScenarioError,
    RunResult,
    _dispatch_report_email,
    _prepare_config,
    build_episode_payload,
    determine_status,
    execute_run,
    load_scenario_plan,
)


class _FakeStdin(io.StringIO):
    def isatty(self) -> bool:
        return True


def _make_config(tmp_path: Path, **overrides) -> RunnerConfig:
    exe = tmp_path / "Unity.exe"
    exe.write_text("echo test")
    artifacts_root = tmp_path / "artifacts"
    config = RunnerConfig(
        unity_executable=exe,
        run_duration_seconds=5,
        screenshot_interval_seconds=None,
        ai_e_base_url="http://localhost:8000",
        ai_e_api_key="test-api-key",
        project_name="Babylon",
        run_mode="freestyle",
        build_id="build-001",
        artifacts_root=artifacts_root,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _env_vars(tmp_path: Path) -> dict[str, str]:
    exe = tmp_path / "Unity.exe"
    exe.write_text("echo test")
    return {
        "UNITY_EXE_PATH": str(exe),
        "RUN_DURATION_SECONDS": "5",
        "AI_E_BASE_URL": "http://localhost:8000",
        "AI_E_API_KEY": "key",
        "PROJECT_NAME": "demo",
        "RUN_MODE": "freestyle",
        "BUILD_ID": "build-123",
    }


def test_determine_status_mapping() -> None:
    assert determine_status(0, None) == "pass"
    assert determine_status(3, None) == "fail"
    assert determine_status(None, None) == "error"
    assert determine_status(0, "boom") == "error"


def test_build_episode_payload_includes_artifacts(tmp_path) -> None:
    config = _make_config(tmp_path)
    config.scenario = {
        "scenario_id": "guided",
        "scenario_name": "Guided",
        "scenario_steps": ["boot"],
        "expected": {"no_crash": True},
    }
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text("ok")
    screenshot = tmp_path / "shot.png"
    screenshot.write_text("binary")
    events_log = tmp_path / "events.log"
    events_log.write_text("mark\n")
    result = RunResult(
        runtime_seconds=123.4,
        exit_code=0,
        logs=[stdout_log],
        screenshots=[screenshot],
        status="pass",
        started_at="2026-01-20T00:00:00Z",
        finished_at="2026-01-20T00:02:03Z",
        error=None,
        events_log=events_log,
        event_counts={"mark": 2},
        capture_mode="unity_window",
    )

    payload = build_episode_payload(config, result)

    assert payload["source"] == "unity-runner"
    assert payload["project"] == "Babylon"
    assert payload["metrics"]["duration_seconds"] == 123.4
    assert payload["metrics"]["screenshots_captured"] == 1
    assert payload["metrics"]["capture_mode"] == "unity_window"
    assert payload["metrics"]["events_mark_count"] == 2
    assert payload["artifacts"]["logs"] == [str(stdout_log)]
    assert payload["artifacts"]["events"] == [str(events_log)]
    assert payload["labels"] == ["harness", "option-a"]
    assert payload["scenario"]["scenario_id"] == "guided"
    assert payload["metrics"]["scenario"]["observed"]["runtime_seconds"] == 123.4


def test_runner_human_mode_payload(tmp_path) -> None:
    config = _make_config(tmp_path, run_mode="human")
    stdout_log = tmp_path / "stdout.log"
    stdout_log.write_text("ok")
    result = RunResult(
        runtime_seconds=10.0,
        exit_code=0,
        logs=[stdout_log],
        screenshots=[],
        status="pass",
        started_at="2026-01-20T00:00:00Z",
        finished_at="2026-01-20T00:00:10Z",
        event_counts={"mark": 1},
        capture_mode="off",
    )

    payload = build_episode_payload(config, result)

    assert payload["mode"] == "human"
    assert payload["metrics"]["capture_mode"] == "off"
    assert payload["metrics"]["events_mark_count"] == 1
    assert payload["scenario"]["type"] == "human_observed"
    assert "human" in payload["labels"]


def test_execute_run_collects_logs(tmp_path) -> None:
    config = _make_config(tmp_path)
    artifacts = create_artifact_paths(config.artifacts_root, run_id="test-run")

    class FakeProcess:
        def __init__(self, *_args, **kwargs):
            stdout_file = kwargs["stdout"]
            stderr_file = kwargs["stderr"]
            stdout_file.write("unity stdout\n")
            stderr_file.write("unity stderr\n")
            self._returncode = 0

        def wait(self, timeout=None):  # noqa: D401 - simple proxy
            return self._returncode

        def terminate(self) -> None:  # pragma: no cover - not used
            self._returncode = 0

        def kill(self) -> None:  # pragma: no cover - not used
            self._returncode = 0

    result = execute_run(config, artifact_paths=artifacts, popen_cls=FakeProcess)

    assert result.exit_code == 0
    assert result.status == "pass"
    assert result.started_at
    assert result.finished_at
    assert artifacts.stdout_log.read_text() == "unity stdout\n"
    assert artifacts.stderr_log.read_text() == "unity stderr\n"
    assert result.logs == [artifacts.stdout_log, artifacts.stderr_log]
    assert result.screenshots == []


def test_load_scenario_plan(tmp_path) -> None:
    scenarios = [
        {
            "scenario_id": "guided",
            "scenario_name": "Guided",
            "scenario_steps": ["boot"],
            "expected": {"ok": True},
            "runner": {"duration_seconds": 45, "labels": ["smoke"]},
        }
    ]
    file_path = tmp_path / "scenarios.json"
    file_path.write_text(json.dumps(scenarios))

    plan = load_scenario_plan(file_path, "guided")

    assert plan.scenario["scenario_id"] == "guided"
    assert plan.overrides["duration_seconds"] == 45
    assert plan.overrides["labels"] == ["smoke"]


def test_prepare_config_requires_scenario_for_instructed(tmp_path) -> None:
    config = _make_config(tmp_path, run_mode="instructed")
    with pytest.raises(RunnerScenarioError):
        _prepare_config(config)


def test_prepare_config_applies_breaker_overrides(tmp_path) -> None:
    file_path = tmp_path / "scenarios.json"
    scenarios = [
        {
            "scenario_id": "breaker-smoke",
            "scenario_name": "Breaker",
            "scenario_steps": ["boot"],
            "expected": {"ok": False},
            "runner": {
                "duration_seconds": 30,
                "screenshot_interval_seconds": 1,
                "max_screenshots": 5,
                "labels": ["breaker", "stress"],
            },
        }
    ]
    file_path.write_text(json.dumps(scenarios))
    config = _make_config(
        tmp_path,
        run_mode="breaker",
        scenario_id="breaker-smoke",
        scenarios_file=file_path,
    )

    _prepare_config(config)

    assert "breaker" in config.episode_labels
    assert config.run_duration_seconds <= BREAKER_MAX_DURATION_SECONDS
    assert config.screenshot_interval_seconds <= BREAKER_SCREENSHOT_INTERVAL_SECONDS
    assert config.screenshot_max_captures == 5


def test_load_runner_config_defaults_screenshot_target(tmp_path) -> None:
    env = _env_vars(tmp_path)
    config = load_runner_config(env)
    assert config.screenshot_target == "unity_window"


def test_load_runner_config_accepts_desktop_target(tmp_path) -> None:
    env = _env_vars(tmp_path)
    env["RUNNER_SCREENSHOT_TARGET"] = "desktop"
    config = load_runner_config(env)
    assert config.screenshot_target == "desktop"


def test_load_runner_config_falls_back_for_invalid_target(tmp_path) -> None:
    env = _env_vars(tmp_path)
    env["RUNNER_SCREENSHOT_TARGET"] = "unknown"
    config = load_runner_config(env)
    assert config.screenshot_target == "unity_window"


def test_generate_run_identifier_uses_timezone_utc(tmp_path, monkeypatch) -> None:
    config = _make_config(tmp_path)
    seen: list[object] = []

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            seen.append(tz)

            class FakeStamp:
                def strftime(self, _fmt):
                    return "20260101_000000"

            return FakeStamp()

    monkeypatch.setattr(run_unity, "datetime", FakeDateTime)
    value = run_unity._generate_run_identifier(config)
    assert seen == [timezone.utc]
    assert value.startswith("20260101_000000")


def test_load_runner_config_accepts_api_base_url_env(tmp_path) -> None:
    env = _env_vars(tmp_path)
    env.pop("AI_E_BASE_URL", None)
    env["API_BASE_URL"] = "http://localhost:8000"
    config = load_runner_config(env)
    assert config.ai_e_base_url == "http://localhost:8000"


def test_load_runner_config_skips_placeholder_base_url(tmp_path) -> None:
    env = _env_vars(tmp_path)
    env["AI_E_BASE_URL"] = "https://example.com"
    config = load_runner_config(env)
    assert config.ai_e_base_url is None


def test_execute_single_run_writes_pending_when_post_skipped(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    env = _env_vars(tmp_path)
    env.pop("AI_E_BASE_URL", None)
    env.pop("AI_E_API_KEY", None)
    artifacts_dir = tmp_path / "artifacts" / "run-1"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    result = RunResult(
        runtime_seconds=1.0,
        exit_code=0,
        logs=[],
        screenshots=[],
        status="pass",
        started_at="2026-01-20T00:00:00Z",
        finished_at="2026-01-20T00:00:01Z",
        artifacts_dir=artifacts_dir,
        events_log=None,
        event_counts={},
        capture_mode="off",
    )

    def fake_execute_run(_config, **_kwargs):
        return result

    def fake_post_episode(_payload, _config):
        return EpisodePostResult(
            success=False,
            skipped=True,
            skip_reason="API base URL not configured",
        )

    monkeypatch.setattr(run_unity, "execute_run", fake_execute_run)
    monkeypatch.setattr(run_unity, "post_episode", fake_post_episode)

    record, success = run_unity._execute_single_run(env, "single", None, 1)

    assert success is False
    assert record.pending_episode_path is not None
    assert record.pending_episode_path.exists()


def test_episode_skip_does_not_log_error(monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.chdir(tmp_path)
    env = _env_vars(tmp_path)
    env.pop("AI_E_BASE_URL", None)
    env.pop("AI_E_API_KEY", None)
    artifacts_dir = tmp_path / "artifacts" / "run-1"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    result = RunResult(
        runtime_seconds=1.0,
        exit_code=0,
        logs=[],
        screenshots=[],
        status="pass",
        started_at="2026-01-20T00:00:00Z",
        finished_at="2026-01-20T00:00:01Z",
        artifacts_dir=artifacts_dir,
        events_log=None,
        event_counts={},
        capture_mode="off",
    )

    def fake_execute_run(_config, **_kwargs):
        return result

    def fake_post_episode(_payload, _config):
        return EpisodePostResult(
            success=False,
            skipped=True,
            skip_reason="API base URL not configured",
        )

    monkeypatch.setattr(run_unity, "execute_run", fake_execute_run)
    monkeypatch.setattr(run_unity, "post_episode", fake_post_episode)

    with caplog.at_level(logging.INFO):
        run_unity._execute_single_run(env, "single", None, 1)

    assert "Failed to post Unity episode to AI-E" not in caplog.text


def test_execute_single_run_reports_config_error(monkeypatch, tmp_path, caplog) -> None:
    monkeypatch.chdir(tmp_path)
    env = {
        "RUN_MODE": "human",
        "BUILD_ID": "build-001",
        "RUNNER_NO_LAUNCH": "1",
        "RUNNER_CAPTURE_MODE": "off",
    }

    with caplog.at_level(logging.ERROR):
        record, success = run_unity._execute_single_run(env, "single", None, 1)

    assert success is False
    assert record.artifacts_dir is not None
    stderr_path = record.artifacts_dir / "logs" / "stderr.log"
    assert stderr_path.exists()
    assert "Configuration error" in stderr_path.read_text(encoding="utf-8")
    assert "Configuration error" in caplog.text


def test_human_no_launch_stays_active_until_stop(monkeypatch, tmp_path) -> None:
    config = _make_config(tmp_path, run_mode="human")
    config.no_launch = True
    config.capture_mode = "off"
    config.screenshot_interval_seconds = None
    popen = Mock()

    monkeypatch.setattr(run_unity, "_start_hotkeys", lambda *args, **kwargs: None)
    monkeypatch.setattr(hotkeys.sys, "stdin", _FakeStdin("\n"))

    result = run_unity.execute_run(config, popen_cls=popen)

    assert popen.call_count == 0
    assert result.exit_code == 0
    assert result.launch_skipped is True


def test_terminal_commands_log_events(monkeypatch, tmp_path) -> None:
    config = _make_config(tmp_path, run_mode="human")
    config.no_launch = True
    config.capture_mode = "desktop"
    config.screenshot_interval_seconds = None
    popen = Mock()

    shot_path = tmp_path / "shot.png"
    monkeypatch.setattr(run_unity, "_start_hotkeys", lambda *args, **kwargs: None)
    monkeypatch.setattr(hotkeys.sys, "stdin", _FakeStdin("m\ns\n\n"))
    monkeypatch.setattr(
        run_unity.ScreenshotRecorder,
        "capture_now",
        lambda _self, label="manual": shot_path,
    )

    result = run_unity.execute_run(config, popen_cls=popen)

    assert result.event_counts and result.event_counts.get("mark") == 1
    events_text = result.events_log.read_text(encoding="utf-8")
    assert "manual_screenshot" in events_text


def test_email_skipped_when_not_configured(monkeypatch, tmp_path) -> None:
    report_path = tmp_path / "reports" / "report_last_run.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("report body", encoding="utf-8")
    now = datetime.now(timezone.utc)
    row = RunReportRow(
        index=1,
        run_id="human_run",
        plan_kind="single",
        scenario_id=None,
        mode="human",
        status="pass",
        exit_code=0,
        runtime_seconds=5.0,
        episode_id=1,
        episode_post_success=True,
        episode_post_status="HTTP 201",
        artifacts_dir=tmp_path,
        pending_episode_path=None,
        episode_payload_path=None,
        episode_response_path=None,
        screenshots=[],
        screenshot_target="unity_window",
        screenshots_captured=0,
        screenshots_requested=0,
        build_id="build-1",
        started_at=now.isoformat(),
        finished_at=now.isoformat(),
        logs=[],
        events_log=None,
        events_mark_count=0,
        capture_mode="off",
        capture_disabled_reason=None,
        capture_warnings=[],
    )
    summary = PlanReportSummary(
        plan_kind="single",
        runs=[row],
        command="python -m runner.run_unity --mode human",
        env_summary={},
        metadata={},
        started_at=now,
        finished_at=now,
        stop_on_fail=False,
    )
    monkeypatch.setenv("EMAIL_ENABLED", "0")
    status = _dispatch_report_email(summary, report_path, [tmp_path], "Demo")
    assert status == "SKIPPED (not configured)"
