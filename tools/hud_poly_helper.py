#!/usr/bin/env python3
"""Helpers to visualize and normalize SF6 HUD polygon ROIs."""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover - optional dependency
    raise SystemExit("Pillow is required: pip install pillow") from exc

from runner.health_bar import P1_BAR_POLY_NORM, P2_BAR_POLY_NORM

Point = Tuple[float, float]


def _parse_points(raw: str) -> List[Point]:
    raw = raw.strip()
    if not raw:
        raise ValueError("No points provided.")
    if raw[0] in "[(":
        parsed = ast.literal_eval(raw)
        if not isinstance(parsed, (list, tuple)):
            raise ValueError("Expected a list/tuple of (x, y) pairs.")
        points: List[Point] = []
        for pair in parsed:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError("Each point must be a 2-item pair.")
            points.append((float(pair[0]), float(pair[1])))
        return points

    tokens = [t for t in re.split(r"[; ]+", raw) if t]
    points = []
    for token in tokens:
        if "," not in token:
            raise ValueError(f"Invalid point token: '{token}'")
        x_str, y_str = token.split(",", 1)
        points.append((float(x_str), float(y_str)))
    return points


def _normalize(points_px: Sequence[Point], width: int, height: int) -> List[Point]:
    return [
        (round(x / width, 4), round(y / height, 4)) for x, y in points_px
    ]


def _to_pixels(points_norm: Sequence[Point], width: int, height: int) -> List[Tuple[int, int]]:
    return [(int(round(x * width)), int(round(y * height))) for x, y in points_norm]


def _draw_poly(draw: ImageDraw.ImageDraw, points: Sequence[Tuple[int, int]], color: str) -> None:
    if not points:
        return
    draw.line(list(points) + [points[0]], fill=color, width=3)
    for x, y in points:
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), outline=color, width=2)


def _overlay(args: argparse.Namespace) -> int:
    image = Image.open(args.image).convert("RGB")
    width, height = image.size
    p1_norm = _parse_points(args.p1_poly) if args.p1_poly else P1_BAR_POLY_NORM
    p2_norm = _parse_points(args.p2_poly) if args.p2_poly else P2_BAR_POLY_NORM

    y_offset = int(args.y_offset_px or 0)
    p1_px = _to_pixels(p1_norm, width, height)
    p2_px = _to_pixels(p2_norm, width, height)
    if y_offset:
        p1_px = [(x, max(0, min(height, y + y_offset))) for x, y in p1_px]
        p2_px = [(x, max(0, min(height, y + y_offset))) for x, y in p2_px]

    draw = ImageDraw.Draw(image)
    _draw_poly(draw, p1_px, "lime")
    _draw_poly(draw, p2_px, "red")

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    print(f"Wrote overlay: {output}")
    return 0


def _normalize_cmd(args: argparse.Namespace) -> int:
    image = Image.open(args.image)
    width, height = image.size
    points_px = _parse_points(args.points)
    normalized = _normalize(points_px, width, height)
    if args.label:
        print(f"{args.label} = {normalized}")
    else:
        print(normalized)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Overlay or normalize HUD polygon points."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    overlay = sub.add_parser("overlay", help="Draw polygons over a screenshot.")
    overlay.add_argument("--image", required=True, help="Path to the reference image.")
    overlay.add_argument("--out", required=True, help="Output path for the overlay image.")
    overlay.add_argument(
        "--p1-poly",
        default="",
        help="P1 polygon as 'x,y x,y ...' or Python list of tuples (normalized).",
    )
    overlay.add_argument(
        "--p2-poly",
        default="",
        help="P2 polygon as 'x,y x,y ...' or Python list of tuples (normalized).",
    )
    overlay.add_argument(
        "--y-offset-px",
        type=int,
        default=0,
        help="Optional Y offset in pixels applied to both polygons.",
    )
    overlay.set_defaults(func=_overlay)

    normalize = sub.add_parser(
        "normalize", help="Convert pixel points to normalized coordinates."
    )
    normalize.add_argument("--image", required=True, help="Path to the reference image.")
    normalize.add_argument(
        "--points",
        required=True,
        help="Points in pixel space: 'x,y x,y x,y'.",
    )
    normalize.add_argument(
        "--label",
        default="",
        help="Optional label to print before the normalized list.",
    )
    normalize.set_defaults(func=_normalize_cmd)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
