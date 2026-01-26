"""Tests for runner plan parsing and reporting."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from runner.plans import RunPlanError, build_run_plan
from runner.reporting import PlanReportSummary, RunReportRow, write_reports


def test_build_run_plan_queue_parses_scenarios() -> None:
    args = SimpleNamespace(
        plan="queue",
        scenarios="breaker-sprint, guided-tour",
        scenario=None,
        stop_on_fail=True,
        every_minutes=None,
        max_runs=None,
        duration_minutes=None,
    )
    plan = build_run_plan(args)
    assert plan.kind == "queue"
    assert plan.scenarios == ["breaker-sprint", "guided-tour"]
    assert plan.stop_on_fail is True


def test_build_run_plan_single_uses_optional_scenario() -> None:
    args = SimpleNamespace(
        plan="single",
        scenario="guided-tour",
        scenarios=None,
        stop_on_fail=False,
        every_minutes=None,
        max_runs=None,
        duration_minutes=None,
    )
    plan = build_run_plan(args)
    assert plan.kind == "single"
    assert plan.scenarios == ["guided-tour"]


def test_build_run_plan_schedule_requires_interval() -> None:
    args = SimpleNamespace(
        plan="schedule",
        scenario="breaker-sprint",
        scenarios=None,
        stop_on_fail=False,
        every_minutes=None,
        max_runs=None,
        duration_minutes=None,
    )
    with pytest.raises(RunPlanError):
        build_run_plan(args)


def test_write_reports_creates_last_and_archive(tmp_path) -> None:
    run_row = RunReportRow(
        index=1,
        run_id="20260121_000000",
        plan_kind="single",
        scenario_id="breaker-sprint",
        mode="breaker",
        status="pass",
        exit_code=0,
        runtime_seconds=5.2,
        episode_id=42,
        episode_post_success=True,
        episode_post_status="HTTP 201",
        artifacts_dir=tmp_path / "runner_artifacts" / "20260121_000000",
        pending_episode_path=None,
        screenshots=["shot1.png", "shot2.png"],
        screenshot_target="unity_window",
        screenshots_captured=2,
        screenshots_requested=10,
        build_id="build-1",
        started_at="2026-01-21T00:00:00Z",
        finished_at="2026-01-21T00:00:06Z",
        logs=["stdout.log", "stderr.log"],
    )
    summary = PlanReportSummary(
        plan_kind="single",
        runs=[run_row],
        command="python -m runner.run_unity --plan single",
        env_summary={"PROJECT_NAME": "AIE-TestHarness"},
        metadata={"scenario": "breaker-sprint"},
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        stop_on_fail=False,
    )
    last_path, archive_path = write_reports(summary, workspace=tmp_path)

    assert last_path.exists()
    assert archive_path.exists()
    content = last_path.read_text(encoding="utf-8")
    assert "Unity Runner Report" in content
    assert "breaker-sprint" in content
    assert archive_path.read_text(encoding="utf-8") == content
