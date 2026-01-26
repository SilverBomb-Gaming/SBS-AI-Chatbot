"""Tests for controller input logging integration."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from runner.input_capture.controller_logger import (
    BackendControllerState,
    ControllerLogger,
    InputLoggingSummary,
)
from runner.reporting import PlanReportSummary, RunReportRow, render_report


class _FakeBackend:
    def __init__(self, frames: List[Dict[str, BackendControllerState]]):
        self._frames = frames
        self._index = 0

    def initialize(self) -> None:  # pragma: no cover - no setup needed
        return

    def read(self) -> Dict[str, BackendControllerState]:
        if self._index >= len(self._frames):
            return self._frames[-1]
        frame = self._frames[self._index]
        self._index += 1
        return frame

    def shutdown(self) -> None:  # pragma: no cover - no teardown needed
        return


def _make_run_row(**overrides) -> RunReportRow:
    defaults = dict(
        index=1,
        run_id="run-1",
        plan_kind="single",
        scenario_id="scenario-1",
        mode="human",
        status="pass",
        exit_code=0,
        runtime_seconds=10.0,
        episode_id=1,
        episode_post_success=True,
        episode_post_status="HTTP 201",
        episode_post_skipped_reason=None,
        artifacts_dir=Path("/tmp/run-1"),
        pending_episode_path=None,
        episode_payload_path=None,
        episode_response_path=None,
        launch_skipped=False,
        launch_reason=None,
        screenshots=[],
        screenshot_target="unity_window",
        screenshots_captured=0,
        screenshots_requested=0,
        build_id="build-1",
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        logs=[],
        error=None,
        api_error=None,
        events_log=None,
        events_mark_count=0,
        capture_mode="unity_window",
        capture_disabled_reason=None,
        capture_warnings=[],
        input_status="OFF",
        input_status_message="per config",
        input_events_captured=0,
        input_log_path=None,
        input_warnings=[],
        input_state_status="OFF",
        input_state_message="per config",
        input_state_frames=0,
        input_state_log_path=None,
        input_state_effective_hz=0.0,
        input_state_target_hz=0,
        input_state_expected_frames=0,
        input_state_warnings=[],
    )
    defaults.update(overrides)
    return RunReportRow(**defaults)


def test_inputs_off_skips_file_and_reports_off(tmp_path) -> None:
    inputs_log = tmp_path / "controller_events.jsonl"
    summary = InputLoggingSummary.disabled("per config")
    assert not inputs_log.exists()

    row = _make_run_row(
        input_status=summary.status,
        input_status_message=summary.message,
        input_events_captured=summary.events_captured,
        input_log_path=None,
        input_warnings=summary.warnings,
    )
    plan_summary = PlanReportSummary(
        plan_kind="single",
        runs=[row],
        command="python -m runner.run_unity --mode human --inputs off",
        env_summary={},
        metadata={},
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        stop_on_fail=False,
    )
    rendered = render_report(plan_summary)
    assert "Input logging: OFF (per config)" in rendered


def test_controller_logger_writes_jsonl_and_counts_events(tmp_path) -> None:
    device = BackendControllerState(
        device_id="pad-0",
        index=0,
        name="FakePad",
        axes={"LS_X": 0.0, "LS_Y": 0.0},
        buttons={"A": 0},
        hats={"DPAD_X": 0, "DPAD_Y": 0},
    )
    moved = BackendControllerState(
        device_id="pad-0",
        index=0,
        name="FakePad",
        axes={"LS_X": 0.7, "LS_Y": 0.0},
        buttons={"A": 1},
        hats={"DPAD_X": 1, "DPAD_Y": 0},
    )
    released = BackendControllerState(
        device_id="pad-0",
        index=0,
        name="FakePad",
        axes={"LS_X": 0.0, "LS_Y": 0.0},
        buttons={"A": 0},
        hats={"DPAD_X": 0, "DPAD_Y": 0},
    )
    frames = [
        {},
        {"pad-0": device},
        {"pad-0": moved},
        {"pad-0": released},
    ]
    log_path = tmp_path / "controller_events.jsonl"
    logger = ControllerLogger(
        log_path,
        poll_interval_ms=5,
        deadzone=0.1,
        axis_epsilon=0.02,
        backend_factory=lambda: _FakeBackend(frames),
    )
    assert logger.start() is True
    time.sleep(0.05)
    logger.stop()
    summary = logger.summary()
    assert summary.status == "ON"
    assert summary.events_captured >= 4
    assert summary.log_path == log_path
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == summary.events_captured
    parsed_events = [json.loads(line) for line in lines]
    assert any(event["event_type"] == "axis" for event in parsed_events)
    assert any(event["event_type"] == "button" for event in parsed_events)


def test_report_includes_input_summary_fields(tmp_path) -> None:
    log_path = tmp_path / "inputs" / "controller_events.jsonl"
    row = _make_run_row(
        input_status="ON",
        input_status_message="controller logger running",
        input_events_captured=12,
        input_log_path=log_path,
        input_warnings=["no controller detected"],
    )
    summary = PlanReportSummary(
        plan_kind="single",
        runs=[row],
        command="python -m runner.run_unity --mode human",
        env_summary={},
        metadata={},
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        stop_on_fail=False,
    )
    rendered = render_report(summary)
    assert "Input logging: ON (controller logger running); events: 12" in rendered
    assert "log:" in rendered
    assert "Input warnings:" in rendered
