"""Tests for Unity screenshot capture behavior."""
from __future__ import annotations

from pathlib import Path

from runner.capture import (
    UNITY_WINDOW_DISABLED_WARNING,
    UNITY_WINDOW_WAIT_TIMEOUT_SECONDS,
    create_artifact_paths,
    ScreenshotRecorder,
)
import runner.capture as capture_module


class DummyScreen:
    def __init__(self) -> None:
        self.monitors = [{"left": 0, "top": 0, "width": 1, "height": 1}]


def test_unity_window_missing_disables_after_timeout(tmp_path, monkeypatch) -> None:
    artifacts = create_artifact_paths(Path(tmp_path), run_id="run-1")
    recorder = ScreenshotRecorder(
        interval_seconds=1,
        artifacts=artifacts,
        max_captures=1,
        capture_mode="unity_window",
    )
    recorder.attach_unity_pid(123)

    def fake_find_window(_pid):
        return None

    times = iter([0.0, 0.0, UNITY_WINDOW_WAIT_TIMEOUT_SECONDS + 1.0])

    def fake_monotonic():
        try:
            return next(times)
        except StopIteration:
            return UNITY_WINDOW_WAIT_TIMEOUT_SECONDS + 1.0

    monkeypatch.setattr(capture_module, "_find_window_rect", fake_find_window)
    monkeypatch.setattr(capture_module.time, "monotonic", fake_monotonic)

    assert recorder._select_monitor(DummyScreen()) is None
    assert recorder.disabled_reason is None

    assert recorder._select_monitor(DummyScreen()) is None
    assert recorder.disabled_reason == "unity-window-missing"
    assert recorder.capture_mode == "unity_window"
    assert UNITY_WINDOW_DISABLED_WARNING in recorder.warnings
