"""Filesystem contracts for training runs and human feedback artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict

HUMAN_FEEDBACK_README = """# Human Feedback Folder

This directory is reserved for **operator supplied annotations**. Files copied out of
`training_runs/<run_id>` should be placed under `reference/` **without editing**.
Any edited/annotated versions should be stored under `edited/`.

- `notes/notes.json` records structured feedback entries.
- Do **not** edit files inside `training_runs/`; copy them here first.
- Keep descriptions specific (HUD alignment, polygon offsets, etc.).
"""


@dataclass(frozen=True)
class TrainingRunPaths:
    run_dir: Path
    screenshots_dir: Path
    hud_debug_dir: Path
    logs_dir: Path
    events_dir: Path
    inputs_dir: Path
    metadata_dir: Path
    metrics_path: Path
    manifest_path: Path
    run_log_path: Path
    human_feedback_dir: Path
    human_feedback_overlays_dir: Path
    human_feedback_roi_dir: Path
    human_feedback_notes_dir: Path


@dataclass(frozen=True)
class HumanFeedbackPaths:
    root_dir: Path
    run_id: str
    run_dir: Path
    reference_dir: Path
    edited_dir: Path
    notes_dir: Path
    notes_path: Path
    readme_path: Path


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_training_run_contract(run_dir: Path) -> TrainingRunPaths:
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = run_dir / "screenshots"
    hud_debug_dir = run_dir / "hud_debug"
    logs_dir = run_dir / "logs"
    events_dir = run_dir / "events"
    inputs_dir = run_dir / "inputs"
    metadata_dir = run_dir / "metadata"
    human_feedback_dir = run_dir / "human_feedback"
    overlays_dir = human_feedback_dir / "overlays_fixed"
    roi_dir = human_feedback_dir / "roi_samples"
    notes_dir = human_feedback_dir / "notes"
    for directory in (
        screenshots_dir,
        hud_debug_dir,
        logs_dir,
        events_dir,
        inputs_dir,
        metadata_dir,
        human_feedback_dir,
        overlays_dir,
        roi_dir,
        notes_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        metrics_path.write_text(
            json.dumps(
                {
                    "status": "pending",
                    "created_at": _timestamp(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps(
                {
                    "run_id": run_dir.name,
                    "status": "pending",
                    "created_at": _timestamp(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    run_log_path = run_dir / "run.log"
    if not run_log_path.exists():
        run_log_path.touch()
    return TrainingRunPaths(
        run_dir=run_dir,
        screenshots_dir=screenshots_dir,
        hud_debug_dir=hud_debug_dir,
        logs_dir=logs_dir,
        events_dir=events_dir,
        inputs_dir=inputs_dir,
        metadata_dir=metadata_dir,
        metrics_path=metrics_path,
        manifest_path=manifest_path,
        run_log_path=run_log_path,
        human_feedback_dir=human_feedback_dir,
        human_feedback_overlays_dir=overlays_dir,
        human_feedback_roi_dir=roi_dir,
        human_feedback_notes_dir=notes_dir,
    )


def ensure_human_feedback_root(root_dir: Path) -> None:
    root = root_dir.resolve()
    (root / "from_training").mkdir(parents=True, exist_ok=True)
    (root / "manual" / "ad_hoc").mkdir(parents=True, exist_ok=True)


def prepare_human_feedback_paths(root_dir: Path, run_id: str) -> HumanFeedbackPaths:
    ensure_human_feedback_root(root_dir)
    run_dir = (root_dir / "from_training" / run_id).resolve()
    reference_dir = run_dir / "reference"
    edited_dir = run_dir / "edited"
    notes_dir = run_dir / "notes"
    for directory in (run_dir, reference_dir, edited_dir, notes_dir):
        directory.mkdir(parents=True, exist_ok=True)
    readme_path = run_dir / "README.md"
    if not readme_path.exists():
        readme_path.write_text(HUMAN_FEEDBACK_README.strip() + "\n", encoding="utf-8")
    notes_path = notes_dir / "notes.json"
    if not notes_path.exists():
        notes_path.write_text("[]\n", encoding="utf-8")
    return HumanFeedbackPaths(
        root_dir=root_dir.resolve(),
        run_id=run_id,
        run_dir=run_dir,
        reference_dir=reference_dir,
        edited_dir=edited_dir,
        notes_dir=notes_dir,
        notes_path=notes_path,
        readme_path=readme_path,
    )


def record_feedback_note(paths: HumanFeedbackPaths, note: Dict[str, Any]) -> Path:
    existing: list[Dict[str, Any]] = []
    if paths.notes_path.exists():
        try:
            existing = json.loads(paths.notes_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []
    note["recorded_at"] = _timestamp()
    existing.append(note)
    paths.notes_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return paths.notes_path
