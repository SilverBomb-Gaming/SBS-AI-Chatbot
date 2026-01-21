"""Tests for the Unity runner helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.capture import create_artifact_paths
from runner.config import RunnerConfig
from runner.run_unity import (
    BREAKER_MAX_DURATION_SECONDS,
    BREAKER_SCREENSHOT_INTERVAL_SECONDS,
    RunnerScenarioError,
    RunResult,
    _prepare_config,
    build_episode_payload,
    determine_status,
    execute_run,
    load_scenario_plan,
)


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
    result = RunResult(
        runtime_seconds=123.4,
        exit_code=0,
        logs=[stdout_log],
        screenshots=[screenshot],
        status="pass",
        started_at="2026-01-20T00:00:00Z",
        finished_at="2026-01-20T00:02:03Z",
        error=None,
    )

    payload = build_episode_payload(config, result)

    assert payload["source"] == "unity-runner"
    assert payload["project"] == "Babylon"
    assert payload["metrics"]["duration_seconds"] == 123.4
    assert payload["metrics"]["screenshots_captured"] == 1
    assert payload["artifacts"]["logs"] == [str(stdout_log)]
    assert payload["labels"] == ["harness", "option-a"]
    assert payload["scenario"]["scenario_id"] == "guided"
    assert payload["metrics"]["scenario"]["observed"]["runtime_seconds"] == 123.4


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
