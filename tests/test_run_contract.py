from __future__ import annotations

import json
from pathlib import Path

from core.run_contract import ensure_training_run_contract, prepare_human_feedback_paths, record_feedback_note


def test_ensure_training_run_contract(tmp_path: Path) -> None:
    run_dir = tmp_path / "training_runs" / "20260129_000000"
    paths = ensure_training_run_contract(run_dir)
    assert paths.run_dir.exists()
    assert paths.hud_debug_dir.exists()
    assert paths.screenshots_dir.exists()
    assert paths.human_feedback_dir.exists()
    assert paths.human_feedback_overlays_dir.exists()
    assert paths.human_feedback_roi_dir.exists()
    assert paths.human_feedback_notes_dir.exists()
    assert paths.metrics_path.exists()
    data = json.loads(paths.metrics_path.read_text(encoding="utf-8"))
    assert data["status"] == "pending"


def test_prepare_human_feedback_paths(tmp_path: Path) -> None:
    base = tmp_path / "human_feedback"
    paths = prepare_human_feedback_paths(base, "20260129_000000")
    assert paths.reference_dir.exists()
    assert paths.edited_dir.exists()
    assert paths.notes_path.exists()
    note_path = record_feedback_note(
        paths,
        {
            "run_id": "20260129_000000",
            "source_file": "hud_ep000_step00000.png",
            "issue": "offset",
            "suggested_fix": "shift up",
            "confidence": 0.9,
            "tool": "Paint",
        },
    )
    notes = json.loads(note_path.read_text(encoding="utf-8"))
    assert len(notes) == 1
    assert notes[0]["issue"] == "offset"
