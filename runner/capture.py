"""Artifact helpers for the Unity runner."""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from runner.events import EventLogger


def _find_window_rect(_target_pid: int) -> Optional[Tuple[int, int, int, int]]:
    return None


if sys.platform == "win32":  # pragma: no cover - Windows-only helper
    import ctypes.wintypes as wintypes

    def _find_window_rect(target_pid: int) -> Optional[Tuple[int, int, int, int]]:
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        result: List[Tuple[int, int, int, int]] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != target_pid:
                return True
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                result.append((rect.left, rect.top, rect.right, rect.bottom))
                return False
            return True

        user32.EnumWindows(_enum_proc, 0)
        return result[0] if result else None


LOGGER = logging.getLogger(__name__)
UNITY_WINDOW_WAIT_TIMEOUT_SECONDS = 12
UNITY_WINDOW_WAIT_WARNING = "Unity window not found; waiting"
UNITY_WINDOW_DISABLED_WARNING = (
    "Unity window capture unavailable; screenshots disabled for this run."
)

try:  # Optional dependency for screenshot capture
    import mss  # type: ignore
    from mss import tools as mss_tools  # type: ignore
except ImportError:  # pragma: no cover - handled at runtime
    mss = None  # type: ignore
    mss_tools = None  # type: ignore


@dataclass
class ArtifactPaths:
    """Resolved directories and files for a single run."""

    run_id: str
    run_dir: Path
    logs_dir: Path
    screenshots_dir: Path
    events_dir: Path
    inputs_dir: Path
    stdout_log: Path
    stderr_log: Path
    events_log: Path
    inputs_log: Path

    def update_run_id(self, new_run_id: str) -> None:
        if not new_run_id or new_run_id == self.run_id:
            return
        target_dir = self.run_dir.parent / new_run_id
        try:
            self.run_dir.rename(target_dir)
        except OSError as exc:  # pragma: no cover - filesystem safety
            LOGGER.warning("Unable to rename artifacts dir to %s: %s", target_dir, exc)
            return
        self.run_id = new_run_id
        self.run_dir = target_dir
        self.logs_dir = target_dir / "logs"
        self.screenshots_dir = target_dir / "screenshots"
        self.events_dir = target_dir / "events"
        self.inputs_dir = target_dir / "inputs"
        self.stdout_log = self.logs_dir / "stdout.log"
        self.stderr_log = self.logs_dir / "stderr.log"
        self.events_log = self.events_dir / "events.log"
        self.inputs_log = self.inputs_dir / "controller_events.jsonl"

    def dense_input_path(self, hz: int, extension: str = "jsonl") -> Path:
        cleaned_ext = extension.lstrip(".") or "jsonl"
        safe_hz = max(1, hz)
        filename = f"controller_state_{safe_hz}hz.{cleaned_ext}"
        return self.inputs_dir / filename


def create_artifact_paths(root: Path, run_id: str | None = None) -> ArtifactPaths:
    """Prepare directories for capturing logs and screenshots."""
    resolved_root = root.resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    run_identifier = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = resolved_root / run_identifier
    logs_dir = run_dir / "logs"
    screenshots_dir = run_dir / "screenshots"
    events_dir = run_dir / "events"
    inputs_dir = run_dir / "inputs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    events_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    return ArtifactPaths(
        run_id=run_identifier,
        run_dir=run_dir,
        logs_dir=logs_dir,
        screenshots_dir=screenshots_dir,
        events_dir=events_dir,
        inputs_dir=inputs_dir,
        stdout_log=logs_dir / "stdout.log",
        stderr_log=logs_dir / "stderr.log",
        events_log=events_dir / "events.log",
        inputs_log=inputs_dir / "controller_events.jsonl",
    )


@dataclass
class ScreenshotRecorder:
    """Capture periodic or manual screenshots for artifact collection."""

    interval_seconds: int | None
    artifacts: ArtifactPaths
    max_captures: int | None = None
    capture_mode: str = "unity_window"
    event_logger: EventLogger | None = None
    filename_prefix: str = "screenshot"
    _captures: List[Path] = field(default_factory=list, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _capture_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _effective_mode: str = field(default="unity_window", init=False)
    _disabled_reason: str | None = field(default=None, init=False)
    _unity_pid: int | None = field(default=None, init=False)
    _warnings: List[str] = field(default_factory=list, init=False)
    _prepared: bool = field(default=False, init=False)
    _window_wait_started: float | None = field(default=None, init=False)

    def start(self) -> None:
        if not self._prepare_capture_environment():
            return
        if not self.interval_seconds:
            LOGGER.info("Screenshot cadence disabled; manual capture only")
            return
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="unity-runner-screenshots",
            daemon=True,
        )
        self._thread.start()

    def attach_unity_pid(self, pid: int) -> None:
        self._unity_pid = pid

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    @property
    def paths(self) -> List[Path]:
        return list(self._captures)

    @property
    def effective_mode(self) -> str:
        return self._effective_mode

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    @property
    def warnings(self) -> List[str]:
        return list(self._warnings)

    def capture_now(self, label: str = "manual") -> Path | None:
        if not self._prepared:
            if not self._prepare_capture_environment():
                return None
        if self._disabled_reason:
            LOGGER.info(
                "Manual screenshot skipped (capture disabled: %s)",
                self._disabled_reason,
            )
            return None
        if self._capture_limit_reached():
            LOGGER.info("Manual screenshot skipped (max captures reached)")
            return None
        return self._capture_with_context(manual=True, label=label)

    def _prepare_capture_environment(self) -> bool:
        if self._prepared:
            return not bool(self._disabled_reason)
        self._prepared = True
        if self.capture_mode == "off":
            self._effective_mode = "off"
            self._disabled_reason = "mode-off"
            return False
        if self.max_captures is not None and self.max_captures <= 0:
            self._effective_mode = "off"
            self._disabled_reason = "max-captures"
            LOGGER.info("Screenshot capture disabled (max captures set to 0)")
            return False
        if sys.platform != "win32":
            self._effective_mode = "off"
            self._disabled_reason = f"platform:{sys.platform}"
            LOGGER.info(
                "Screenshot capture skipped (platform %s not supported)",
                sys.platform,
            )
            self._log_event("capture_warning", self._disabled_reason)
            return False
        if os.environ.get("CI"):
            self._effective_mode = "off"
            self._disabled_reason = "ci-environment"
            LOGGER.info("Screenshot capture skipped (CI environment detected)")
            self._log_event("capture_warning", self._disabled_reason)
            return False
        if mss is None or mss_tools is None:  # pragma: no cover - environment specific
            self._effective_mode = "off"
            self._disabled_reason = "mss-missing"
            LOGGER.warning(
                "mss library not available; screenshots disabled for this run"
            )
            self._log_event("capture_warning", self._disabled_reason)
            return False
        self._effective_mode = self.capture_mode
        return True

    def _capture_loop(self) -> None:
        assert self.interval_seconds is not None
        try:
            with mss.mss() as screen:  # type: ignore[attr-defined]
                while not self._stop_event.is_set():
                    if self._disabled_reason:
                        break
                    if self._capture_limit_reached():
                        LOGGER.info(
                            "Screenshot capture limit of %s reached; stopping",
                            self.max_captures,
                        )
                        break
                    self._capture_once(screen)
                    if self._disabled_reason:
                        break
                    if self._stop_event.wait(self.interval_seconds):
                        break
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.exception("Screenshot capture failed: %s", exc)

    def _capture_with_context(self, *, manual: bool, label: str) -> Path | None:
        assert mss is not None  # guarded in _prepare_capture_environment
        assert mss_tools is not None
        with self._capture_lock:
            try:
                with mss.mss() as screen:  # type: ignore[attr-defined]
                    return self._capture_once(screen, manual=manual, label=label)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Unable to capture screenshot: %s", exc)
                return None

    def _capture_once(
        self,
        screen: "mss.mss",  # type: ignore[name-defined]
        *,
        manual: bool = False,
        label: str = "auto",
    ) -> Path | None:
        monitor = self._select_monitor(screen)
        if monitor is None:
            return None
        filename = (
            f"{self.filename_prefix}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.png"
        )
        output_path = self.artifacts.screenshots_dir / filename
        try:
            shot = screen.grab(monitor)
            mss_tools.to_png(shot.rgb, shot.size, output=str(output_path))  # type: ignore[attr-defined]
            self._captures.append(output_path)
            event_type = "manual_screenshot" if manual else "screenshot_auto"
            self._log_event(event_type, f"{label}:{output_path}")
            LOGGER.debug("Captured screenshot %s", output_path)
            return output_path
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Unable to capture screenshot: %s", exc)
            return None

    def _select_monitor(self, screen: "mss.mss") -> Optional[dict]:  # type: ignore[name-defined]
        if self._disabled_reason:
            return None
        if self.capture_mode == "desktop":
            return screen.monitors[0]
        if self.capture_mode == "unity_window":
            if not self._unity_pid:
                self._track_missing_window()
                return None
            rect = _find_window_rect(self._unity_pid)
            if rect is None:
                self._track_missing_window()
                return None
            left, top, right, bottom = rect
            width = max(0, right - left)
            height = max(0, bottom - top)
            if width == 0 or height == 0:
                warning = "Unity window rect invalid"
                if not self._warnings or self._warnings[-1] != warning:
                    self._warnings.append(warning)
                    LOGGER.warning(warning)
                return None
            return {"left": left, "top": top, "width": width, "height": height}
        return screen.monitors[0]

    def _track_missing_window(self) -> None:
        if self._window_wait_started is None:
            self._window_wait_started = time.monotonic()
        warning = UNITY_WINDOW_WAIT_WARNING
        if not self._warnings or self._warnings[-1] != warning:
            self._warnings.append(warning)
            LOGGER.debug(warning)
        elapsed = time.monotonic() - self._window_wait_started
        if elapsed < UNITY_WINDOW_WAIT_TIMEOUT_SECONDS:
            return
        if self._disabled_reason:
            return
        self._disabled_reason = "unity-window-missing"
        if UNITY_WINDOW_DISABLED_WARNING not in self._warnings:
            self._warnings.append(UNITY_WINDOW_DISABLED_WARNING)
        LOGGER.warning(UNITY_WINDOW_DISABLED_WARNING)
        self._log_event("capture_warning", UNITY_WINDOW_DISABLED_WARNING)

    def _capture_limit_reached(self) -> bool:
        return (
            self.max_captures is not None and len(self._captures) >= self.max_captures
        )

    def _log_event(self, event_type: str, message: str | None = None) -> None:
        if self.event_logger:
            self.event_logger.log(event_type, message)


if sys.platform == "win32":  # pragma: no cover - Windows-only helper
    import ctypes.wintypes as wintypes

    def _find_window_rect(target_pid: int) -> Optional[Tuple[int, int, int, int]]:
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        result: List[Tuple[int, int, int, int]] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != target_pid:
                return True
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                result.append((rect.left, rect.top, rect.right, rect.bottom))
                return False
            return True

        user32.EnumWindows(_enum_proc, 0)
        return result[0] if result else None
