"""Tests for dense controller state streaming."""
from __future__ import annotations

import json
import time
from pathlib import Path

from runner.input_capture.controller_logger import (
    BackendControllerState,
    ControllerStateStreamLogger,
)


class _StaticBackend:
    def __init__(self) -> None:
        self._state = BackendControllerState(
            device_id="pad-0",
            index=0,
            name="TestPad",
            axes={"LS_X": 0.5, "LS_Y": 0.0, "RS_X": 0.0, "RS_Y": 0.0, "LT": 0.1, "RT": 0.9},
            buttons={"A": 1, "B": 0},
            hats={"DPAD_X": 1, "DPAD_Y": 0},
        )

    def initialize(self) -> None:
        return None

    def read(self) -> dict[str, BackendControllerState]:
        return {self._state.device_id: self._state}

    def shutdown(self) -> None:
        return None


def test_controller_state_stream_writes_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "controller_state_60hz.jsonl"
    logger = ControllerStateStreamLogger(
        log_path,
        hz=20,
        fmt="jsonl",
        raw=True,
        deadzone=0.0,
        backend_factory=_StaticBackend,
        event_logger=None,
    )
    assert logger.start() is True
    time.sleep(0.1)
    logger.stop()
    summary = logger.summary()
    assert summary.status == "ON"
    assert summary.frames > 0
    assert summary.log_path == log_path
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == summary.frames
    sample = json.loads(lines[0])
    assert sample["devices"]
    first = sample["devices"][0]
    assert first["axes"]["LS_X"] == 0.5
    assert first["buttons"]["A"] == 1
    assert first["dpad"]["right"] == 1
