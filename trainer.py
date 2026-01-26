#!/usr/bin/env python3
"""Closed-loop trainer: observe -> decide -> act -> reward -> learn."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, Optional, Tuple

import vgamepad as vg

try:  # Optional dependency for screenshot capture
    import mss  # type: ignore
    from mss import tools as mss_tools  # type: ignore
except ImportError:  # pragma: no cover - environment specific
    mss = None  # type: ignore
    mss_tools = None  # type: ignore

from agent.action_set import ACTIONS, Action, action_names, apply_action, get_action, release_all
from agent.q_learner import QLearner
from agent.reward import DEFAULT_IDLE_PENALTY, net_advantage
from agent.state import make_state
from reporting.training_report import generate_report
from runner.target_detect import lock_target
from runner.capture import _find_window_rect  # type: ignore

if os.name == "nt":  # pragma: no cover - Windows-only helpers
    import ctypes
    import ctypes.wintypes as wintypes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Closed-loop trainer for SF6.")
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--episode-seconds", type=float, default=60.0)
    parser.add_argument("--decision-hz", type=float, default=10.0)
    parser.add_argument("--action-hold-ticks", type=int, default=6)
    parser.add_argument("--policy-path", default="policies/q_table.json")
    parser.add_argument("--report-path", default="")
    parser.add_argument("--target-exe", default="StreetFighter6.exe")
    parser.add_argument("--target-lock-seconds", type=int, default=10)
    parser.add_argument("--target-poll-ms", type=int, default=100)
    parser.add_argument("--capture-mode", choices=["desktop", "window"], default="desktop")
    parser.add_argument("--screenshot-dir", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-vision", action="store_true")
    parser.add_argument("--debug-buttons", action="store_true")
    parser.add_argument(
        "--force-action",
        help=(
            "Force a single button each tick (bypasses policy). "
            "Examples: DPAD_RIGHT, DPAD_LEFT, DPAD_UP, DPAD_DOWN, A, B, X, Y, "
            "START, BACK, LB, RB, LTHUMB, RTHUMB"
        ),
    )
    parser.add_argument(
        "--keep-controller-alive-seconds",
        type=float,
        default=0.0,
        help="Create a virtual controller, pulse A once, then sleep for N seconds before exit.",
    )
    parser.add_argument(
        "--reward-mode",
        choices=["delta", "vision", "both"],
        default="both",
        help="Reward source: screen delta, vision health, or both.",
    )
    parser.add_argument("--delta-threshold", type=float, default=0.02)
    parser.add_argument("--delta-reward", type=float, default=0.01)
    parser.add_argument("--delta-window", type=int, default=1)
    parser.add_argument("--deal-weight", type=float, default=1.0)
    parser.add_argument("--take-weight", type=float, default=1.2)
    parser.add_argument("--debug-hud", action="store_true")
    parser.add_argument("--hud-p1-roi", default="")
    parser.add_argument("--hud-p2-roi", default="")
    parser.add_argument("--hud-p1-poly", default="")
    parser.add_argument("--hud-p2-poly", default="")
    parser.add_argument("--hud-roi-mode", choices=["poly", "rect"], default="poly")
    parser.add_argument("--hud-y-offset-px", type=int, default=0)
    parser.add_argument("--hud-y-offset-norm", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--idle-penalty", type=float, default=DEFAULT_IDLE_PENALTY)
    return parser.parse_args()


def _capture_region(target_pid: Optional[int], capture_mode: str) -> dict:
    if capture_mode == "window" and target_pid is not None:
        rect = _find_window_rect(target_pid)
        if rect:
            left, top, right, bottom = rect
            width = max(0, right - left)
            height = max(0, bottom - top)
            if width > 0 and height > 0:
                return {"left": left, "top": top, "width": width, "height": height}
    return {}


def _save_screenshot(rgb_bytes: bytes, size: tuple, path: Path) -> None:
    if mss_tools is None:
        return
    mss_tools.to_png(rgb_bytes, size, output=str(path))  # type: ignore[arg-type]


def _enable_dpi_awareness() -> str:
    if os.name != "nt":
        return "non-windows"
    try:
        user32 = ctypes.windll.user32
        set_ctx = getattr(user32, "SetProcessDpiAwarenessContext", None)
        if set_ctx:
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)  # type: ignore[arg-type]
            if set_ctx(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                return "per-monitor-v2"
        set_aware = getattr(user32, "SetProcessDPIAware", None)
        if set_aware and set_aware():
            return "system-aware"
    except Exception:
        return "failed"
    return "unknown"


def _get_client_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    if os.name != "nt" or not hwnd:
        return None
    try:
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        point = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
            return None
        left = point.x
        top = point.y
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        return (left, top, left + width, top + height)
    except Exception:
        return None


def _capture_region_for_target(hwnd: Optional[int], capture_mode: str) -> Tuple[dict, dict]:
    window_rect = _find_window_rect(hwnd) if hwnd and capture_mode == "window" else None
    client_rect = _get_client_rect(hwnd) if hwnd and capture_mode == "window" else None
    if capture_mode == "window" and client_rect:
        left, top, right, bottom = client_rect
        region = {
            "left": left,
            "top": top,
            "width": max(0, right - left),
            "height": max(0, bottom - top),
        }
        return region, {"window_rect": window_rect, "client_rect": client_rect}
    if capture_mode == "window" and window_rect:
        left, top, right, bottom = window_rect
        region = {
            "left": left,
            "top": top,
            "width": max(0, right - left),
            "height": max(0, bottom - top),
        }
        return region, {"window_rect": window_rect, "client_rect": client_rect}
    return {}, {"window_rect": window_rect, "client_rect": client_rect}


def _parse_roi(raw: str, fallback: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    if not raw:
        return fallback
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        return fallback
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return fallback


def _parse_poly(raw: str, fallback: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not raw:
        return fallback
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 8:
        return fallback
    try:
        values = [float(p) for p in parts]
    except ValueError:
        return fallback
    return [(values[i], values[i + 1]) for i in range(0, 8, 2)]


def _apply_y_offset(
    roi_px: Tuple[int, int, int, int],
    *,
    frame_h: int,
    offset_px: int,
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = roi_px
    y1 = max(0, min(frame_h, y1 + offset_px))
    y2 = max(0, min(frame_h, y2 + offset_px))
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def _downsample_gray_bytes(frame: bytes, size: Tuple[int, int], target: Tuple[int, int]) -> bytes:
    from PIL import Image  # type: ignore

    image = Image.frombytes("RGB", size, frame)
    gray = image.convert("L").resize(target)
    return gray.tobytes()


def _screen_delta(prev_bytes: bytes, curr_bytes: bytes) -> float:
    if not prev_bytes or not curr_bytes or len(prev_bytes) != len(curr_bytes):
        return 0.0
    total = 0
    for a, b in zip(prev_bytes, curr_bytes):
        total += abs(a - b)
    return total / (255.0 * len(curr_bytes))


def _frame_hash(gray_bytes: bytes) -> str:
    return hashlib.md5(gray_bytes).hexdigest()[:12]


def _resolve_force_button(name: str | None) -> vg.XUSB_BUTTON | None:
    if not name:
        return None
    key = name.strip().upper()
    mapping = {
        "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
        "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT",
        "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP",
        "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
        "A": "XUSB_GAMEPAD_A",
        "B": "XUSB_GAMEPAD_B",
        "X": "XUSB_GAMEPAD_X",
        "Y": "XUSB_GAMEPAD_Y",
        "START": "XUSB_GAMEPAD_START",
        "BACK": "XUSB_GAMEPAD_BACK",
        "LB": "XUSB_GAMEPAD_LEFT_SHOULDER",
        "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
        "LTHUMB": "XUSB_GAMEPAD_LEFT_THUMB",
        "RTHUMB": "XUSB_GAMEPAD_RIGHT_THUMB",
    }
    attr = mapping.get(key)
    if not attr:
        return None
    return getattr(vg.XUSB_BUTTON, attr, None)


def main() -> int:
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    if mss is None:
        raise SystemExit("mss is required for screenshot capture.")

    dpi_status = _enable_dpi_awareness()

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_root = Path("training_runs") / run_ts
    screenshots_dir = (
        Path(args.screenshot_dir)
        if args.screenshot_dir
        else run_root / "screenshots"
    )
    run_root.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    hud_debug_dir = run_root / "hud_debug"
    if args.debug_hud:
        hud_debug_dir.mkdir(parents=True, exist_ok=True)
    transitions_path = run_root / "transitions.jsonl"
    summaries_path = run_root / "episode_summaries.json"

    policy_path = Path(args.policy_path)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    learner = QLearner.load(policy_path)

    if args.debug_buttons:
        button_names = [name for name in dir(vg.XUSB_BUTTON) if name.startswith("XUSB_GAMEPAD_")]
        print("Available XUSB_BUTTON enums:")
        for name in sorted(button_names):
            print(f"- {name}")

    gamepad = vg.VX360Gamepad()
    if args.keep_controller_alive_seconds > 0:
        try:
            gamepad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
            gamepad.update()
            time.sleep(0.1)
            gamepad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
            gamepad.update()
            time.sleep(args.keep_controller_alive_seconds)
        finally:
            release_all(gamepad)
            time.sleep(0.25)
            release_all(gamepad)
        return 0

    force_button = _resolve_force_button(args.force_action)
    if args.force_action and force_button is None:
        raise SystemExit(f"Unknown --force-action '{args.force_action}'.")

    lock = lock_target(
        mode="exe",
        lock_seconds=args.target_lock_seconds,
        poll_ms=args.target_poll_ms,
        ignore_processes=None,
        explicit_exe=args.target_exe,
        explicit_exe_path=None,
        logger=None,
    )
    if not lock:
        raise SystemExit(f"Target lock failed for {args.target_exe}.")
    target_pid = lock.info.pid if lock.info else None
    target_hwnd = lock.info.hwnd if lock.info else None

    metadata_dir = run_root / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "target_process.json").write_text(
        json.dumps(
            {
                "exe_path": lock.info.exe_path if lock.info else None,
                "window_title": lock.info.window_title if lock.info else None,
                "label": lock.label,
                "label_hash": lock.hash_suffix,
                "locked_at_utc": lock.locked_at.isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    tracker = None
    p1_roi_norm: Tuple[float, float, float, float] | None = None
    p2_roi_norm: Tuple[float, float, float, float] | None = None
    p1_poly_norm: list[tuple[float, float]] | None = None
    p2_poly_norm: list[tuple[float, float]] | None = None
    roi_mode = args.hud_roi_mode
    if not args.no_vision:
        try:
            from runner.health_bar import HealthBarTracker
            from runner.health_bar import (
                P1_HEALTH_N,
                P2_HEALTH_N,
                P1_BAR_POLY_NORM,
                P2_BAR_POLY_NORM,
                estimate_health_poly,
                norm_poly_to_px,
            )

            p1_roi_norm = _parse_roi(args.hud_p1_roi, P1_HEALTH_N)
            p2_roi_norm = _parse_roi(args.hud_p2_roi, P2_HEALTH_N)
            p1_poly_norm = _parse_poly(args.hud_p1_poly, P1_BAR_POLY_NORM)
            p2_poly_norm = _parse_poly(args.hud_p2_poly, P2_BAR_POLY_NORM)
            tracker = HealthBarTracker(
                p1_roi=p1_roi_norm,
                p2_roi=p2_roi_norm,
            )
        except Exception as exc:
            raise SystemExit(f"Health bar extraction unavailable: {exc}")
    legal_actions = action_names()
    episode_summaries = []
    stop_requested = False

    def _handle_stop(_signum=None, _frame=None) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    try:
        with mss.mss() as screen:  # type: ignore[attr-defined]
            monitor = screen.monitors[0]
            diagnostics_printed = False
            roi_diag_px = None
            roi_diag_mode = roi_mode
            roi_diag_offset_px = None
            for episode_idx in range(args.episodes):
                if stop_requested:
                    break
                episode_start = time.perf_counter()
                episode_end = episode_start + args.episode_seconds
                prev_health = None
                prev_action = "NEUTRAL"
                total_reward = 0.0
                step_idx = 0
                hold_remaining = 0
                current_action = get_action("NEUTRAL")
                action_started = True
                episode_health_start = None
                episode_health_end = None
                prev_gray = b""
                delta_window: Deque[float] = deque(maxlen=max(1, args.delta_window))
                avg_screen_delta = 0.0
                delta_gt_count = 0
                frame_hash_prev = ""
                same_state_streak = 0
                last_debug = time.perf_counter()

                while time.perf_counter() < episode_end:
                    if stop_requested:
                        break
                    now = time.perf_counter()
                    t_run = now - episode_start
                    capture_region, rect_info = _capture_region_for_target(
                        target_hwnd, args.capture_mode
                    )
                    shot = screen.grab(capture_region or monitor)
                    width, height = shot.size
                    frame = shot.rgb

                    if not diagnostics_printed:
                        diagnostics_printed = True
                        print(f"CAPTURE_MODE={args.capture_mode}")
                        print(f"DPI_AWARE={dpi_status}")
                        print(
                            f"MONITOR_SIZE={monitor.get('width')}x{monitor.get('height')}"
                        )
                        if target_hwnd:
                            print(f"TARGET_HWND={target_hwnd}")
                        if rect_info.get("window_rect"):
                            print(f"WINDOW_RECT={rect_info['window_rect']}")
                        if rect_info.get("client_rect"):
                            print(f"CLIENT_RECT={rect_info['client_rect']}")
                        print(f"FRAME_SIZE={width}x{height}")
                        if tracker is not None:
                            offset_px = args.hud_y_offset_px
                            if args.hud_y_offset_norm is not None:
                                offset_px = int(args.hud_y_offset_norm * height)
                            print(f"HUD_Y_OFFSET_PX={offset_px}")
                            roi_diag_offset_px = offset_px
                            print(f"ROI_MODE={roi_mode}")
                            if roi_mode == "rect" and p1_roi_norm and p2_roi_norm:
                                p1_px = (
                                    int(p1_roi_norm[0] * width),
                                    int(p1_roi_norm[1] * height),
                                    int(p1_roi_norm[2] * width),
                                    int(p1_roi_norm[3] * height),
                                )
                                p2_px = (
                                    int(p2_roi_norm[0] * width),
                                    int(p2_roi_norm[1] * height),
                                    int(p2_roi_norm[2] * width),
                                    int(p2_roi_norm[3] * height),
                                )
                                print(f"P1_ROI_PX_PRE={p1_px}")
                                print(f"P2_ROI_PX_PRE={p2_px}")
                                p1_post = _apply_y_offset(p1_px, frame_h=height, offset_px=offset_px)
                                p2_post = _apply_y_offset(p2_px, frame_h=height, offset_px=offset_px)
                                print(f"P1_ROI_PX_POST={p1_post}")
                                print(f"P2_ROI_PX_POST={p2_post}")
                                roi_diag_px = {"p1": p1_post, "p2": p2_post}
                            elif roi_mode == "poly" and p1_poly_norm and p2_poly_norm:
                                p1_px = norm_poly_to_px(p1_poly_norm, width, height)
                                p2_px = norm_poly_to_px(p2_poly_norm, width, height)
                                if offset_px:
                                    p1_px[:, 1] = p1_px[:, 1] + offset_px
                                    p2_px[:, 1] = p2_px[:, 1] + offset_px
                                p1_px[:, 1] = p1_px[:, 1].clip(0, height)
                                p2_px[:, 1] = p2_px[:, 1].clip(0, height)
                                p1_list = [tuple(int(v) for v in pt) for pt in p1_px.tolist()]
                                p2_list = [tuple(int(v) for v in pt) for pt in p2_px.tolist()]
                                print(f"P1_POLY_PX={p1_list}")
                                print(f"P2_POLY_PX={p2_list}")
                                roi_diag_px = {"p1": p1_list, "p2": p2_list}

                    screenshot_path = screenshots_dir / f"ep{episode_idx:03d}_step{step_idx:05d}.png"
                    _save_screenshot(frame, (width, height), screenshot_path)

                    gray_small = _downsample_gray_bytes(frame, (width, height), (64, 36))
                    delta = _screen_delta(prev_gray, gray_small)
                    delta_window.append(delta)
                    avg_delta = sum(delta_window) / len(delta_window)
                    avg_screen_delta += avg_delta
                    if avg_delta > args.delta_threshold:
                        delta_gt_count += 1
                    prev_gray = gray_small
                    frame_hash = _frame_hash(gray_small)
                    if frame_hash == frame_hash_prev:
                        same_state_streak += 1
                    else:
                        same_state_streak = 0
                        frame_hash_prev = frame_hash

                    my_hp = 1.0
                    enemy_hp = 1.0
                    if tracker is not None:
                        from PIL import Image  # type: ignore
                        from PIL import ImageDraw  # type: ignore

                        image = Image.frombytes("RGB", (width, height), frame)
                        offset_px = args.hud_y_offset_px
                        if args.hud_y_offset_norm is not None:
                            offset_px = int(args.hud_y_offset_norm * height)
                        if roi_mode == "poly" and p1_poly_norm and p2_poly_norm:
                            my_hp = estimate_health_poly(
                                image,
                                p1_poly_norm,
                                y_offset_px=offset_px,
                            )
                            enemy_hp = estimate_health_poly(
                                image,
                                p2_poly_norm,
                                y_offset_px=offset_px,
                            )
                        else:
                            if args.hud_y_offset_px or args.hud_y_offset_norm is not None:
                                shifted = image.transform(
                                    image.size,
                                    Image.AFFINE,
                                    (1, 0, 0, 0, 1, -offset_px),
                                )
                                my_hp, enemy_hp = tracker.update(shifted)
                            else:
                                my_hp, enemy_hp = tracker.update(image)
                        offset_px = args.hud_y_offset_px
                        if args.hud_y_offset_norm is not None:
                            offset_px = int(args.hud_y_offset_norm * height)
                        if args.debug_hud:
                            should_save = step_idx in {1, 3} or (time.perf_counter() - last_debug) >= 1.0
                        else:
                            should_save = False
                        if should_save:
                            draw = ImageDraw.Draw(image)
                            if roi_mode == "poly" and p1_poly_norm and p2_poly_norm:
                                p1_px = norm_poly_to_px(p1_poly_norm, width, height)
                                p2_px = norm_poly_to_px(p2_poly_norm, width, height)
                                if offset_px:
                                    p1_px[:, 1] = p1_px[:, 1] + offset_px
                                    p2_px[:, 1] = p2_px[:, 1] + offset_px
                                p1_px[:, 1] = p1_px[:, 1].clip(0, height)
                                p2_px[:, 1] = p2_px[:, 1].clip(0, height)
                                p1_pts = [tuple(int(v) for v in pt) for pt in p1_px.tolist()]
                                p2_pts = [tuple(int(v) for v in pt) for pt in p2_px.tolist()]
                                if p1_pts:
                                    draw.line(p1_pts + [p1_pts[0]], fill="red", width=2)
                                if p2_pts:
                                    draw.line(p2_pts + [p2_pts[0]], fill="red", width=2)
                            else:
                                p1 = tracker.p1_roi
                                p2 = tracker.p2_roi
                                p1_px = (
                                    int(p1[0] * width),
                                    int(p1[1] * height),
                                    int(p1[2] * width),
                                    int(p1[3] * height),
                                )
                                p2_px = (
                                    int(p2[0] * width),
                                    int(p2[1] * height),
                                    int(p2[2] * width),
                                    int(p2[3] * height),
                                )
                                p1_px = _apply_y_offset(p1_px, frame_h=height, offset_px=offset_px)
                                p2_px = _apply_y_offset(p2_px, frame_h=height, offset_px=offset_px)
                                draw.rectangle(p1_px, outline="red", width=2)
                                draw.rectangle(p2_px, outline="red", width=2)
                            hud_path = hud_debug_dir / f"hud_ep{episode_idx:03d}_step{step_idx:05d}.png"
                            image.save(hud_path)
                            print(f"HUD p1={my_hp:.3f} p2={enemy_hp:.3f} step={step_idx}")
                            print(f"WROTE_HUD_DEBUG={hud_path}")
                            last_debug = time.perf_counter()

                    if episode_health_start is None:
                        episode_health_start = (my_hp, enemy_hp)

                    reward = 0.0
                    delta_enemy = 0.0
                    delta_me = 0.0
                    vision_reward = 0.0
                    delta_reward = 0.0
                    if args.reward_mode in {"delta", "both"}:
                        if avg_delta > args.delta_threshold:
                            delta_reward = args.delta_reward
                        else:
                            delta_reward = -args.idle_penalty
                    if prev_health is not None and tracker is not None and args.reward_mode in {"vision", "both"}:
                        delta_enemy = max(0.0, prev_health["enemy"] - enemy_hp)
                        delta_me = max(0.0, prev_health["me"] - my_hp)
                        vision_reward = (args.deal_weight * delta_enemy) - (
                            args.take_weight * delta_me
                        )
                        if delta_enemy <= 0 and delta_me <= 0:
                            vision_reward -= args.idle_penalty
                    if args.reward_mode == "delta":
                        reward = delta_reward
                    elif args.reward_mode == "vision":
                        reward = vision_reward
                    else:
                        reward = delta_reward + vision_reward
                    reward = max(-0.05, min(0.05, reward))

                    state = make_state(my_hp, enemy_hp, t_run, prev_action, args.episode_seconds)

                    if force_button is not None:
                        action_name = args.force_action.strip().upper()
                        if not args.dry_run:
                            gamepad.press_button(button=force_button)
                            gamepad.update()
                            time.sleep(0.1)
                            gamepad.release_button(button=force_button)
                            gamepad.update()
                        if step_idx % max(1, int(args.decision_hz)) == 0:
                            print(f"FORCE_ACTION={action_name} step={step_idx}")
                    else:
                        if hold_remaining <= 0:
                            action_name = learner.select_action(state, legal_actions)
                            current_action = get_action(action_name)
                            hold_remaining = args.action_hold_ticks
                            action_started = True
                        else:
                            action_name = current_action.name
                            action_started = False

                        if not args.dry_run:
                            if current_action.tap and action_started:
                                apply_action(gamepad, current_action)
                                release_all(gamepad)
                            elif current_action.tap:
                                release_all(gamepad)
                            else:
                                apply_action(gamepad, current_action)

                    next_state = make_state(my_hp, enemy_hp, t_run, action_name, args.episode_seconds)
                    if force_button is None:
                        learner.update(state, action_name, reward, next_state, legal_actions)

                    record = {
                        "ts_utc": datetime.now(timezone.utc).isoformat(),
                        "episode_idx": episode_idx,
                        "step_idx": step_idx,
                        "t_run_s": t_run,
                        "screenshot_path": str(screenshot_path),
                        "my_hp": my_hp,
                        "enemy_hp": enemy_hp,
                        "reward": reward,
                        "delta_enemy": delta_enemy,
                        "delta_me": delta_me,
                        "screen_delta": avg_delta,
                        "reward_delta_component": delta_reward,
                        "reward_vision_component": vision_reward,
                        "delta_threshold": args.delta_threshold,
                        "frame_hash": frame_hash,
                        "same_state_streak": same_state_streak,
                        "state": state,
                        "action": action_name,
                        "epsilon": learner.epsilon,
                        "time_bucket": json.loads(state)["time"],
                    }
                    with transitions_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record) + "\n")

                    if prev_health is not None:
                        total_reward += reward

                    prev_health = {"me": my_hp, "enemy": enemy_hp}
                    prev_action = action_name
                    step_idx += 1
                    hold_remaining -= 1

                    sleep_s = max(0.0, (1.0 / args.decision_hz) - (time.perf_counter() - now))
                    if sleep_s > 0:
                        time.sleep(sleep_s)

                if episode_health_start is None:
                    episode_health_start = (1.0, 1.0)
                episode_health_end = prev_health or {"me": 1.0, "enemy": 1.0}
                avg_screen_delta = avg_screen_delta / max(1, step_idx)
                advantage = net_advantage(
                    enemy_start=episode_health_start[1],
                    enemy_end=episode_health_end["enemy"],
                    me_start=episode_health_start[0],
                    me_end=episode_health_end["me"],
                )
                summary = {
                    "episode_idx": episode_idx,
                    "total_reward": total_reward,
                    "net_advantage": advantage,
                    "steps": step_idx,
                    "p1_start": episode_health_start[0],
                    "p2_start": episode_health_start[1],
                    "p1_end": episode_health_end["me"],
                    "p2_end": episode_health_end["enemy"],
                    "avg_screen_delta": avg_screen_delta,
                    "pct_delta_gt_threshold": (delta_gt_count / max(1, step_idx)) * 100.0,
                }
                episode_summaries.append(summary)
                payload = {"episodes": episode_summaries}
                if roi_diag_mode:
                    payload["roi_mode"] = roi_diag_mode
                if roi_diag_px is not None:
                    payload["roi_px"] = roi_diag_px
                if roi_diag_offset_px is not None:
                    payload["hud_y_offset_px"] = roi_diag_offset_px
                summaries_path.write_text(
                    json.dumps(payload, indent=2),
                    encoding="utf-8",
                )
                learner.save(policy_path)
    finally:
        try:
            release_all(gamepad)
            if not args.dry_run:
                time.sleep(0.25)
                release_all(gamepad)
        except Exception:
            pass

    report_path = (
        Path(args.report_path)
        if args.report_path
        else Path("reports") / f"training_report_{run_ts}.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    generate_report(
        transitions_path=transitions_path,
        summaries_path=summaries_path,
        output_path=report_path,
    )
    print(f"RUN_DIR={run_root.resolve()}")
    print(f"WROTE_POLICY={policy_path.resolve()}")
    print(f"WROTE_REPORT={report_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
