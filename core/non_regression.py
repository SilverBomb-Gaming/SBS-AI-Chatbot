"""Reusable guardrails for non-regression checks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

REQUIRED_HUD_DEBUG_STEPS: List[int] = [0, 2, 4]


class WindowCaptureError(RuntimeError):
    """Raised when window capture preconditions are not satisfied."""


def validate_window_capture_requirements(capture_mode: str, hwnd: int | None) -> None:
    if capture_mode != "window":
        raise WindowCaptureError("WINDOW CAPTURE REQUIRED: only --capture-mode window is supported.")
    if not hwnd:
        raise WindowCaptureError(
            "WINDOW CAPTURE FAILED: no target HWND. Ensure SF6 is visible and not minimized."
        )


def expected_hud_debug_paths(hud_dir: Path, episode_idx: int = 0) -> List[Path]:
    return [hud_dir / f"hud_ep{episode_idx:03d}_step{step:05d}.png" for step in REQUIRED_HUD_DEBUG_STEPS]


@dataclass(frozen=True)
class DebugArtifactStatus:
    enabled: bool
    existing: List[Path]
    missing: List[Path]

    @property
    def ok(self) -> bool:
        return self.enabled and not self.missing


def verify_hud_debug_outputs(hud_dir: Path, enabled: bool, episode_idx: int = 0) -> DebugArtifactStatus:
    if not enabled:
        return DebugArtifactStatus(enabled=False, existing=[], missing=expected_hud_debug_paths(hud_dir, episode_idx))
    expected = expected_hud_debug_paths(hud_dir, episode_idx)
    existing = [path for path in expected if path.exists()]
    missing = [path for path in expected if not path.exists()]
    return DebugArtifactStatus(enabled=True, existing=existing, missing=missing)


def summarize_non_regression(
    *,
    capture_mode: str,
    target_metadata: Path | None,
    hud_dir: Path,
    debug_hud_enabled: bool,
) -> Dict[str, str]:
    status: Dict[str, str] = {}
    status["capture_mode_window_only"] = "pass" if capture_mode == "window" else "fail"
    hwnd_ok = False
    if target_metadata and target_metadata.exists():
        try:
            import json

            data = json.loads(target_metadata.read_text(encoding="utf-8"))
            hwnd_ok = bool(data.get("window_title")) and bool(data.get("exe_path"))
        except Exception:
            hwnd_ok = False
    status["target_hwnd_locked"] = "pass" if hwnd_ok else "fail"
    hud_status = verify_hud_debug_outputs(hud_dir, debug_hud_enabled)
    if not debug_hud_enabled:
        status["debug_artifacts"] = "not-enabled"
    else:
        status["debug_artifacts"] = "pass" if hud_status.ok else "fail"
    return status
