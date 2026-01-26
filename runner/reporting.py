"""Markdown reporting helpers for Unity runner plans."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

LOGGER = logging.getLogger(__name__)


@dataclass
class RunReportRow:
    """Captured metadata about a single Unity execution."""

    index: int
    run_id: str | None
    plan_kind: str
    scenario_id: str | None
    mode: str
    status: str
    exit_code: int | None
    runtime_seconds: float
    episode_id: int | None
    episode_post_success: bool
    episode_post_status: str
    artifacts_dir: Path | None
    pending_episode_path: Path | None
    episode_post_skipped_reason: str | None = None
    episode_payload_path: Path | None = None
    episode_response_path: Path | None = None
    launch_skipped: bool = False
    launch_reason: str | None = None
    screenshots: List[str] = field(default_factory=list)
    screenshot_target: str = "unity_window"
    screenshots_captured: int = 0
    screenshots_requested: int | None = None
    build_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    logs: List[str] = field(default_factory=list)
    error: str | None = None
    api_error: str | None = None
    events_log: Path | None = None
    events_mark_count: int = 0
    capture_mode: str = "off"
    capture_disabled_reason: str | None = None
    capture_warnings: List[str] | None = None
    input_status: str = "OFF"
    input_status_message: str | None = None
    input_events_captured: int = 0
    input_log_path: Path | None = None
    input_warnings: List[str] = field(default_factory=list)
    target_hwnd: int | None = None
    target_pid: int | None = None
    target_exe_path: str | None = None
    target_process_name: str | None = None
    target_window_title: str | None = None

    def pass_fail(self) -> str:
        posted_ok = self.episode_post_success or bool(self.episode_post_skipped_reason)
        return "PASS" if posted_ok and self.status == "pass" else "FAIL"


@dataclass
class PlanReportSummary:
    """Summary for the overall plan run."""

    plan_kind: str
    runs: List[RunReportRow]
    command: str
    env_summary: Dict[str, str]
    metadata: Dict[str, str]
    started_at: datetime
    finished_at: datetime
    stop_on_fail: bool

    def successes(self) -> int:
        return sum(1 for row in self.runs if row.pass_fail() == "PASS")

    def failures(self) -> int:
        return len(self.runs) - self.successes()

    def archive_suffix(self) -> str:
        if not self.runs:
            return "no_runs"
        first = self.runs[0]
        if first.run_id:
            return first.run_id
        return f"plan_{self.plan_kind}"


def write_reports(
    summary: PlanReportSummary,
    workspace: Path | None = None,
    copies: List[Path] | None = None,
) -> Tuple[Path, Path]:
    """Render the latest report and append to the archive."""

    workspace = workspace or Path.cwd()
    if not workspace.exists():  # pragma: no cover - defensive
        workspace.mkdir(parents=True, exist_ok=True)
    report_text = render_report(summary)

    reports_root = workspace / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)
    last_report_path = reports_root / "report_last_run.md"
    last_report_path.write_text(report_text, encoding="utf-8")

    archive_dir = reports_root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    timestamp = summary.finished_at.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_name = f"{timestamp}_{summary.archive_suffix()}.md"
    archive_path = archive_dir / archive_name
    archive_path.write_text(report_text, encoding="utf-8")
    if any(row.mode == "human" for row in summary.runs):
        human_archive_name = f"{timestamp}_report_human.md"
        human_archive_path = archive_dir / human_archive_name
        human_archive_path.write_text(report_text, encoding="utf-8")

    if copies:
        for destination_dir in copies:
            try:
                destination_dir.mkdir(parents=True, exist_ok=True)
                (destination_dir / "report_last_run.md").write_text(
                    report_text, encoding="utf-8"
                )
            except OSError as exc:  # pragma: no cover - filesystem safety
                LOGGER.warning(
                    "Unable to copy report into %s: %s", destination_dir, exc
                )

    return last_report_path, archive_path


def render_report(summary: PlanReportSummary) -> str:
    lines: List[str] = []
    finished_dt = summary.finished_at.astimezone(timezone.utc)
    lines.append(f"# Unity Runner Report — {finished_dt:%Y-%m-%d %H:%M:%S %Z}")
    lines.append("")
    lines.append(f"- Plan: **{summary.plan_kind}**")
    lines.append(
        f"- Runs executed: **{len(summary.runs)}** (PASS {summary.successes()} / FAIL {summary.failures()})"
    )
    lines.append(f"- Stop on fail: {summary.stop_on_fail}")
    email_status = summary.metadata.get("email")
    other_metadata = {
        key: value for key, value in summary.metadata.items() if key != "email"
    }
    if other_metadata:
        metadata_str = ", ".join(f"{k}={v}" for k, v in other_metadata.items())
        lines.append(f"- Plan metadata: {metadata_str}")
    if email_status:
        lines.append(f"- Email: {email_status}")
    lines.append(f"- Command: `{summary.command}`")
    if summary.env_summary:
        lines.append("- Environment summary:")
        for key, value in summary.env_summary.items():
            lines.append(f"  - {key}={value}")
    lines.append("")

    if summary.runs:
        lines.append(
            "| # | Scenario | Mode | Status | Exit | Duration (s) | Episode | Screenshots | Marks | Target EXE | Window Title |"
        )
        lines.append(
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"
        )
        for row in summary.runs:
            episode_cell = _format_episode_cell(row)
            screenshot_cell = _format_screenshot_cell(row)
            target_exe = row.target_process_name or _short_exe(row.target_exe_path)
            target_title = row.target_window_title or "-"
            lines.append(
                "| {index} | {scenario} | {mode} | {status} | {exit} | {duration:.2f} | {episode} | {shots} | {marks} | {exe} | {title} |".format(
                    index=row.index,
                    scenario=row.scenario_id or "(none)",
                    mode=row.mode,
                    status=row.pass_fail(),
                    exit=row.exit_code if row.exit_code is not None else "-",
                    duration=row.runtime_seconds,
                    episode=episode_cell,
                    shots=screenshot_cell,
                    marks=row.events_mark_count,
                    exe=target_exe or "-",
                    title=target_title or "-",
                )
            )
        lines.append("")

    for row in summary.runs:
        title = row.scenario_id or f"run-{row.index}"
        lines.append(f"## Run {row.index} — {title}")
        lines.append(f"- Result: **{row.pass_fail()}** (Unity status: {row.status})")
        lines.append(f"- Started: {row.started_at}")
        lines.append(f"- Finished: {row.finished_at}")
        lines.append(f"- Build: {row.build_id}")
        lines.append(f"- Mode: {row.mode}")
        lines.append(
            f"- Exit code: {row.exit_code if row.exit_code is not None else 'n/a'}"
        )
        lines.append(f"- Duration: {row.runtime_seconds:.2f}s")
        lines.append(f"- Screenshot target: {row.screenshot_target}")
        lines.append(f"- Capture mode: {row.capture_mode}")
        lines.extend(_format_target_lines(row))
        if row.launch_skipped:
            reason = row.launch_reason or "observe-only"
            lines.append(f"- Launch: SKIPPED ({reason})")
        if row.capture_disabled_reason:
            lines.append(f"- Capture disabled reason: {row.capture_disabled_reason}")
        if row.capture_warnings:
            lines.append("- Capture warnings:")
            for warning in row.capture_warnings:
                lines.append(f"  - {warning}")
        lines.extend(_format_input_logging_lines(row))
        lines.append(_format_run_screenshots(row))
        lines.append(f"- Marks logged: {row.events_mark_count}")
        if row.events_log:
            lines.append(f"- Events log: {row.events_log}")
        if row.artifacts_dir:
            lines.append(f"- Artifacts: {row.artifacts_dir}")
        if row.logs:
            lines.append("- Logs:")
            for log_path in row.logs:
                lines.append(f"  - {log_path}")
        if row.episode_payload_path:
            lines.append(f"- Episode payload: {row.episode_payload_path}")
        if row.episode_response_path:
            lines.append(f"- Episode response: {row.episode_response_path}")
        if row.episode_post_skipped_reason:
            lines.append("- Episode POST: skipped")
            lines.append(f"- Episode POST skipped: {row.episode_post_skipped_reason}")
        elif row.episode_post_success:
            lines.append(f"- Episode POST: success ({row.episode_post_status})")
        else:
            lines.append(f"- Episode POST: failed ({row.episode_post_status})")
        if row.episode_id is not None:
            lines.append(f"- Episode ID: {row.episode_id}")
        if row.pending_episode_path:
            lines.append(f"- Pending payload: {row.pending_episode_path}")
        if row.error:
            lines.append(f"- Runner error: {row.error}")
        if row.api_error:
            lines.append(f"- API error: {row.api_error}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _format_episode_cell(row: RunReportRow) -> str:
    if row.episode_post_success:
        if row.episode_id is not None:
            return f"id {row.episode_id}"
        return row.episode_post_status
    if row.pending_episode_path:
        return "pending"
    if row.episode_post_skipped_reason:
        return "skipped"
    return row.episode_post_status or "failed"


def _format_screenshot_cell(row: RunReportRow) -> str:
    if row.screenshots_captured == 0:
        return "0"
    return f"{row.screenshots_captured} ({row.screenshot_target})"


def _format_run_screenshots(row: RunReportRow) -> str:
    if not row.screenshots:
        return "- Screenshots: none captured"
    first_five = row.screenshots[:5]
    listing = ", ".join(first_five)
    extra = row.screenshots_captured - len(first_five)
    if extra > 0:
        listing = f"{listing}, ... (+{extra} more)"
    return f"- Screenshots ({row.screenshots_captured} total): {listing}"


def _format_input_logging_lines(row: RunReportRow) -> List[str]:
    status_line = f"- Input logging: {row.input_status}"
    if row.input_status_message:
        status_line += f" ({row.input_status_message})"
    status_line += f"; events: {row.input_events_captured}"
    if row.input_log_path:
        status_line += f", log: {row.input_log_path}"
    lines = [status_line]
    if row.input_warnings:
        lines.append("- Input warnings:")
        for warning in row.input_warnings:
            lines.append(f"  - {warning}")
    return lines


def _format_target_lines(row: RunReportRow) -> List[str]:
    if (
        row.target_hwnd is None
        and row.target_pid is None
        and not row.target_exe_path
        and not row.target_window_title
    ):
        return []
    lines = ["- Target App:"]
    if row.target_exe_path:
        lines.append(f"  - Exe: {row.target_exe_path}")
    elif row.target_process_name:
        lines.append(f"  - Exe: {row.target_process_name}")
    if row.target_pid is not None:
        lines.append(f"  - PID: {row.target_pid}")
    if row.target_hwnd is not None:
        lines.append(f"  - HWND: {row.target_hwnd}")
    if row.target_window_title:
        lines.append(f"  - Window title: {row.target_window_title}")
    return lines


def _short_exe(path_value: str | None) -> str | None:
    if not path_value:
        return None
    return Path(path_value).name or None
