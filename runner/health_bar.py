"""Health bar extraction helpers for SF6 screenshots."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

try:  # Optional dependency
    from PIL import Image
except ImportError:  # pragma: no cover - environment specific
    Image = None  # type: ignore[assignment]

try:  # Optional dependency
    import numpy as np
except ImportError:  # pragma: no cover - environment specific
    np = None  # type: ignore[assignment]

P1_HEALTH_N = (0.078, 0.014, 0.479, 0.051)
P2_HEALTH_N = (0.521, 0.014, 0.922, 0.051)

DEFAULT_S_MIN = 80
DEFAULT_V_MIN = 120
DEFAULT_EMA_ALPHA = 0.2
HEALTH_LOG_FILENAME = "health_observations.jsonl"

_FILENAME_TS = re.compile(r"(\d{8}_\d{6}_\d{6})")


def _to_pil(image: Any, *, color_order: str = "RGB") -> "Image.Image":
    if Image is None:
        raise RuntimeError("Pillow is required for health bar extraction.")
    if isinstance(image, Image.Image):
        return image
    if np is not None and isinstance(image, np.ndarray):
        arr = image
        if arr.ndim != 3 or arr.shape[2] < 3:
            raise ValueError("Expected an HxWx3 image array.")
        arr = arr[:, :, :3]
        if color_order.upper() == "BGR":
            arr = arr[:, :, ::-1]
        arr = arr.astype("uint8", copy=False)
        return Image.fromarray(arr, mode="RGB")
    raise TypeError("Unsupported image type; expected PIL.Image or numpy ndarray.")


def _crop_roi(image: "Image.Image", roi_n: Tuple[float, float, float, float]) -> "Image.Image":
    width, height = image.size
    x1 = max(0, min(width, int(round(roi_n[0] * width))))
    y1 = max(0, min(height, int(round(roi_n[1] * height))))
    x2 = max(0, min(width, int(round(roi_n[2] * width))))
    y2 = max(0, min(height, int(round(roi_n[3] * height))))
    if x2 <= x1 or y2 <= y1:
        return image.crop((0, 0, 1, 1))
    return image.crop((x1, y1, x2, y2))


def _filled_ratio(
    image: "Image.Image", *, s_min: int = DEFAULT_S_MIN, v_min: int = DEFAULT_V_MIN
) -> float:
    hsv = image.convert("HSV")
    pixels = list(hsv.getdata())
    if not pixels:
        return 0.0
    filled = sum(1 for _, s, v in pixels if s >= s_min and v >= v_min)
    return filled / float(len(pixels))


def extract_health(
    frame: Any,
    *,
    p1_roi: Tuple[float, float, float, float] = P1_HEALTH_N,
    p2_roi: Tuple[float, float, float, float] = P2_HEALTH_N,
    s_min: int = DEFAULT_S_MIN,
    v_min: int = DEFAULT_V_MIN,
    color_order: str = "RGB",
) -> Tuple[float, float]:
    image = _to_pil(frame, color_order=color_order)
    p1 = _filled_ratio(_crop_roi(image, p1_roi), s_min=s_min, v_min=v_min)
    p2 = _filled_ratio(_crop_roi(image, p2_roi), s_min=s_min, v_min=v_min)
    return p1, p2


@dataclass
class HealthBarTracker:
    ema_alpha: float = DEFAULT_EMA_ALPHA
    s_min: int = DEFAULT_S_MIN
    v_min: int = DEFAULT_V_MIN
    color_order: str = "RGB"
    _last_p1: Optional[float] = None
    _last_p2: Optional[float] = None

    def update(self, frame: Any) -> Tuple[float, float]:
        raw_p1, raw_p2 = extract_health(
            frame, s_min=self.s_min, v_min=self.v_min, color_order=self.color_order
        )
        if self._last_p1 is None or self._last_p2 is None:
            self._last_p1 = raw_p1
            self._last_p2 = raw_p2
            return raw_p1, raw_p2
        alpha = self.ema_alpha
        self._last_p1 = alpha * raw_p1 + (1.0 - alpha) * self._last_p1
        self._last_p2 = alpha * raw_p2 + (1.0 - alpha) * self._last_p2
        return self._last_p1, self._last_p2


def _parse_timestamp_from_path(path: Path) -> datetime:
    match = _FILENAME_TS.search(path.name)
    if not match:
        return datetime.now(timezone.utc)
    try:
        return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S_%f").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return datetime.now(timezone.utc)


class HealthObservationWriter:
    def __init__(
        self,
        log_path: Path,
        *,
        ema_alpha: float = DEFAULT_EMA_ALPHA,
        s_min: int = DEFAULT_S_MIN,
        v_min: int = DEFAULT_V_MIN,
        color_order: str = "RGB",
    ) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._tracker = HealthBarTracker(
            ema_alpha=ema_alpha, s_min=s_min, v_min=v_min, color_order=color_order
        )
        self._prev_p1: Optional[float] = None
        self._prev_p2: Optional[float] = None
        self._start_time: Optional[datetime] = None

    def record_from_path(self, screenshot_path: Path) -> Optional[Dict[str, Any]]:
        if Image is None:
            raise RuntimeError("Pillow is required for health bar extraction.")
        ts = _parse_timestamp_from_path(screenshot_path)
        if self._start_time is None:
            self._start_time = ts
        t_run_s = (ts - self._start_time).total_seconds()

        with Image.open(screenshot_path) as image:
            p1, p2 = self._tracker.update(image)

        if self._prev_p1 is None or self._prev_p2 is None:
            d_p1 = 0.0
            d_p2 = 0.0
            reward = 0.0
        else:
            d_p1 = p1 - self._prev_p1
            d_p2 = p2 - self._prev_p2
            reward = (self._prev_p2 - p2) - (self._prev_p1 - p1)

        self._prev_p1 = p1
        self._prev_p2 = p2

        payload = {
            "ts_utc": ts.isoformat(),
            "t_run_s": t_run_s,
            "obs": {"health": {"p1": p1, "p2": p2, "d_p1": d_p1, "d_p2": d_p2}},
            "reward": reward,
            "screenshot": str(screenshot_path),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
        return payload


def read_health_log(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    observations = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                observations.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return observations
