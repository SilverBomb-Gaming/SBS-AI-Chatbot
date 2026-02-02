from __future__ import annotations

from pathlib import Path

import pytest

from core.non_regression import (
    WindowCaptureError,
    validate_window_capture_requirements,
    verify_hud_debug_outputs,
)


def test_validate_window_capture_requires_hwnd_and_window_mode() -> None:
    with pytest.raises(WindowCaptureError):
        validate_window_capture_requirements("desktop", None)
    with pytest.raises(WindowCaptureError):
        validate_window_capture_requirements("window", None)
    validate_window_capture_requirements("window", 1234)


def test_verify_hud_debug_outputs(tmp_path: Path) -> None:
    status = verify_hud_debug_outputs(tmp_path, enabled=True)
    assert not status.ok
    for step in (0, 2, 4):
        target = tmp_path / f"hud_ep000_step{step:05d}.png"
        target.write_bytes(b"fake")
    status = verify_hud_debug_outputs(tmp_path, enabled=True)
    assert status.ok
