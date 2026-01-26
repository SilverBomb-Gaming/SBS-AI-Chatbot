#!/usr/bin/env python3
"""
Minimal autonomous loop for SF6 using vgamepad + health bar reward.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import vgamepad as vg

from PIL import Image

try:  # Optional dependency for screenshots
    import mss  # type: ignore
    from mss import tools as mss_tools  # type: ignore
except ImportError:  # pragma: no cover - environment specific
    mss = None  # type: ignore
    mss_tools = None  # type: ignore

from runner.health_bar import HealthBarTracker


ACTION_SET = [
    "NEUTRAL",
    "WALK_FWD",
    "WALK_BACK",
    "CROUCH_BLOCK",
    "LP",
    "LK",
    "THROW",
]


@dataclass
class ActionState:
    ls_x: float = 0.0
    ls_y: float = 0.0
    buttons: Optional[List[str]] = None


def _apply_state(gamepad: vg.VX360Gamepad, state: ActionState) -> None:
    if hasattr(gamepad, "left_joystick_float"):
        gamepad.left_joystick_float(state.ls_x, state.ls_y)
    else:
        gamepad.left_joystick(int(state.ls_x * 32767), int(state.ls_y * 32767))

    for name in ("A", "B", "X", "Y", "LB", "RB", "BACK", "START", "LS", "RS"):
        btn = getattr(vg.XUSB_BUTTON, f"XUSB_GAMEPAD_{name}")
        if state.buttons and name in state.buttons:
            gamepad.press_button(btn)
        else:
            gamepad.release_button(btn)

    for name, btn in {
        "up": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
        "down": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
        "left": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
        "right": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    }.items():
        if state.buttons and name in state.buttons:
            gamepad.press_button(btn)
        else:
            gamepad.release_button(btn)

    gamepad.update()


def _action_state(action: str) -> ActionState:
    if action == "WALK_FWD":
        return ActionState(ls_x=0.6)
    if action == "WALK_BACK":
        return ActionState(ls_x=-0.6)
    if action == "CROUCH_BLOCK":
        return ActionState(ls_x=-0.6, ls_y=-0.6)
    if action == "LP":
        return ActionState(buttons=["X"])
    if action == "LK":
        return ActionState(buttons=["A"])
    if action == "THROW":
        return ActionState(buttons=["X", "A"])
    return ActionState()


def _save_screenshot(rgb_bytes: bytes, size: tuple, path: Path) -> None:
    if mss_tools is None:
        return
    mss_tools.to_png(rgb_bytes, size, output=str(path))  # type: ignore[arg-type]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal autonomous agent loop with health-bar reward."
    )
    parser.add_argument("--duration", type=float, default=60.0, help="Run time in seconds")
    parser.add_argument("--decision-hz", type=float, default=12.0, help="Decision rate (Hz)")
    parser.add_argument("--action-seconds", type=float, default=0.1, help="Hold action for this duration")
    parser.add_argument("--macro-hz", type=float, default=60.0, help="Action macro update rate (Hz)")
    parser.add_argument("--epsilon", type=float, default=1.0, help="Random action probability")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--save-screenshots", action="store_true", help="Save decision screenshots")
    parser.add_argument("--run-dir", help="Override output run directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    if mss is None:
        raise SystemExit("mss is required for screenshot capture.")

    decision_dt = 1.0 / max(args.decision_hz, 1e-6)
    macro_dt = 1.0 / max(args.macro_hz, 1e-6)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.run_dir) if args.run_dir else Path("runner_artifacts") / f"{ts}_agent_sf6"
    screenshots_dir = run_dir / "screenshots"
    inputs_dir = run_dir / "inputs"
    run_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    payload_path = run_dir / "episode_payload.jsonl"

    tracker = HealthBarTracker()
    gamepad = vg.VX360Gamepad()
    start = time.perf_counter()
    next_tick = start

    prev_health: Optional[Dict[str, float]] = None
    prev_action: Optional[str] = None
    step = 0

    with mss.mss() as screen:  # type: ignore[attr-defined]
        monitor = screen.monitors[0]
        while True:
            now = time.perf_counter()
            if now - start >= args.duration:
                break

            shot = screen.grab(monitor)
            frame = shot.rgb
            width, height = shot.size

            if args.save_screenshots:
                screenshot_name = f"agent_{ts}_{step:05d}.png"
                screenshot_path = screenshots_dir / screenshot_name
                _save_screenshot(frame, (width, height), screenshot_path)
            else:
                screenshot_path = None

            image = Image.frombytes("RGB", (width, height), frame)
            p1, p2 = tracker.update(image)

            if prev_health is None:
                health = {"p1": p1, "p2": p2, "d_p1": 0.0, "d_p2": 0.0}
            else:
                health = {
                    "p1": p1,
                    "p2": p2,
                    "d_p1": p1 - prev_health["p1"],
                    "d_p2": p2 - prev_health["p2"],
                }

            if prev_health is not None and prev_action is not None:
                reward = (prev_health["p2"] - health["p2"]) - (
                    prev_health["p1"] - health["p1"]
                )
                entry = {
                    "ts_utc": datetime.now(timezone.utc).isoformat(),
                    "t_run_s": now - start,
                    "obs": {"health": prev_health},
                    "action": prev_action,
                    "reward": reward,
                    "next_obs": {"health": health},
                    "screenshot": str(screenshot_path) if screenshot_path else None,
                }
                with payload_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry) + "\n")

            # choose action
            action = (
                random.choice(ACTION_SET) if random.random() < args.epsilon else "NEUTRAL"
            )

            # apply action macro
            state = _action_state(action)
            macro_steps = max(1, int(round(args.action_seconds / macro_dt)))
            for _ in range(macro_steps):
                _apply_state(gamepad, state)
                time.sleep(macro_dt)
            _apply_state(gamepad, ActionState())

            prev_health = health
            prev_action = action
            step += 1

            next_tick += decision_dt
            sleep_s = next_tick - time.perf_counter()
            if sleep_s > 0:
                time.sleep(sleep_s)

    try:
        if hasattr(gamepad, "reset"):
            gamepad.reset()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
