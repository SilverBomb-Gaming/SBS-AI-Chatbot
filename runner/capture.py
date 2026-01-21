"""Artifact helpers for the Unity runner."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List

LOGGER = logging.getLogger(__name__)

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
    stdout_log: Path
    stderr_log: Path


def create_artifact_paths(root: Path, run_id: str | None = None) -> ArtifactPaths:
    """Prepare directories for capturing logs and screenshots."""
    resolved_root = root.resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    run_identifier = run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = resolved_root / run_identifier
    logs_dir = run_dir / "logs"
    screenshots_dir = run_dir / "screenshots"
    logs_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    return ArtifactPaths(
        run_id=run_identifier,
        run_dir=run_dir,
        logs_dir=logs_dir,
        screenshots_dir=screenshots_dir,
        stdout_log=logs_dir / "stdout.log",
        stderr_log=logs_dir / "stderr.log",
    )


@dataclass
class ScreenshotRecorder:
    """Capture periodic screenshots for artifact collection."""

    interval_seconds: int | None
    artifacts: ArtifactPaths
    max_captures: int | None = None
    _captures: List[Path] = field(default_factory=list, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)

    def start(self) -> None:
        if not self.interval_seconds:
            LOGGER.info("Screenshot capture disabled (no interval configured)")
            return
        if self.max_captures is not None and self.max_captures <= 0:
            LOGGER.info("Screenshot capture disabled (max captures set to 0)")
            return
        if mss is None or mss_tools is None:  # pragma: no cover - environment specific
            LOGGER.warning(
                "mss library not available; screenshots will be skipped for this run"
            )
            return
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="unity-runner-screenshots",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    @property
    def paths(self) -> List[Path]:
        return list(self._captures)

    def _capture_loop(self) -> None:
        assert self.interval_seconds is not None
        try:
            with mss.mss() as screen:  # type: ignore[attr-defined]
                while not self._stop_event.is_set():
                    if self.max_captures is not None and len(self._captures) >= self.max_captures:
                        LOGGER.info(
                            "Screenshot capture limit of %s reached; stopping",
                            self.max_captures,
                        )
                        break
                    path = self._capture_once(screen)
                    if path:
                        self._captures.append(path)
                    if self._stop_event.wait(self.interval_seconds):
                        break
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.exception("Screenshot capture failed: %s", exc)

    def _capture_once(self, screen: "mss.mss") -> Path | None:  # type: ignore[name-defined]
        filename = f"screenshot_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.png"
        output_path = self.artifacts.screenshots_dir / filename
        try:
            monitor = screen.monitors[0]
            shot = screen.grab(monitor)
            mss_tools.to_png(shot.rgb, shot.size, output=str(output_path))  # type: ignore[attr-defined]
            LOGGER.debug("Captured screenshot %s", output_path)
            return output_path
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Unable to capture screenshot: %s", exc)
            return None
