#!/usr/bin/env python3
"""
Replay a dense controller_state_XXhz.jsonl stream into a virtual Xbox 360 controller
using vgamepad (ViGEm).

Supports multiple vgamepad API variants by feature-detecting joystick/trigger methods.

Example:
  python .\tools\replay_controller_state.py --jsonl "<path>/controller_state_60hz.jsonl" --hz 60 --duration 60
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Dict, Iterable, Optional, Tuple

import vgamepad as vg


# -----------------------------
# Value scaling helpers
# -----------------------------
def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _stick_float_to_int16(v: float) -> int:
    """
    Convert float in [-1, 1] to signed int16 range [-32768, 32767].
    """
    v = _clamp(v, -1.0, 1.0)
    # map -1 -> -32768, +1 -> +32767
    if v <= -1.0:
        return -32768
    if v >= 1.0:
        return 32767
    return int(round(v * 32767))


def _trigger_float_to_uint8(v: float) -> int:
    """
    Convert float in [0, 1] to uint8 range [0, 255].
    """
    v = _clamp(v, 0.0, 1.0)
    return int(round(v * 255))


# -----------------------------
# Mapping helpers
# -----------------------------
_BUTTON_MAP = {
    "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "BACK": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "LS": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    "RS": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
}

_DPAD_MAP = {
    "up": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "down": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    "left": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    "right": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
}


def apply_frame(gamepad: vg.VX360Gamepad, device: Dict[str, Any]) -> None:
    """
    Apply one device frame to the virtual controller.
    Expected keys:
      - axes: LS_X, LS_Y, RS_X, RS_Y in [-1,1], LT/RT in [0,1]
      - buttons: mapping of button name -> 0/1
      - dpad: up/down/left/right -> 0/1
    """
    axes: Dict[str, Any] = device.get("axes", {}) or {}
    buttons: Dict[str, Any] = device.get("buttons", {}) or {}
    dpad: Dict[str, Any] = device.get("dpad", {}) or {}

    lsx = float(axes.get("LS_X", 0.0))
    lsy = float(axes.get("LS_Y", 0.0))
    rsx = float(axes.get("RS_X", 0.0))
    rsy = float(axes.get("RS_Y", 0.0))
    lt = float(axes.get("LT", 0.0))
    rt = float(axes.get("RT", 0.0))

    # --- Joysticks: support multiple vgamepad API variants ---
    # Variant A: left_joystick_float(x, y) and right_joystick_float(x, y)
    if hasattr(gamepad, "left_joystick_float") and hasattr(gamepad, "right_joystick_float"):
        # Many builds take positional args only.
        gamepad.left_joystick_float(lsx, lsy)
        gamepad.right_joystick_float(rsx, rsy)

    # Variant B: left_joystick(x, y) expecting int16, and right_joystick(x, y)
    elif hasattr(gamepad, "left_joystick") and hasattr(gamepad, "right_joystick"):
        gamepad.left_joystick(_stick_float_to_int16(lsx), _stick_float_to_int16(lsy))
        gamepad.right_joystick(_stick_float_to_int16(rsx), _stick_float_to_int16(rsy))

    else:
        raise RuntimeError("Unsupported vgamepad joystick API: no recognized joystick methods found.")

    # --- Triggers: support float or uint8 variants ---
    if hasattr(gamepad, "left_trigger_float") and hasattr(gamepad, "right_trigger_float"):
        gamepad.left_trigger_float(_clamp(lt, 0.0, 1.0))
        gamepad.right_trigger_float(_clamp(rt, 0.0, 1.0))
    elif hasattr(gamepad, "left_trigger") and hasattr(gamepad, "right_trigger"):
        gamepad.left_trigger(_trigger_float_to_uint8(lt))
        gamepad.right_trigger(_trigger_float_to_uint8(rt))
    else:
        raise RuntimeError("Unsupported vgamepad trigger API: no recognized trigger methods found.")

    # --- Buttons ---
    for name, btn_enum in _BUTTON_MAP.items():
        pressed = int(buttons.get(name, 0)) == 1
        if pressed:
            gamepad.press_button(btn_enum)
        else:
            gamepad.release_button(btn_enum)

    # --- D-pad ---
    for name, btn_enum in _DPAD_MAP.items():
        pressed = int(dpad.get(name, 0)) == 1
        if pressed:
            gamepad.press_button(btn_enum)
        else:
            gamepad.release_button(btn_enum)

    # Commit update to driver
    gamepad.update()


def iter_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    """
    Yield JSON objects line-by-line from a JSONL file.
    """
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _latest_run_jsonl(base_dir: str = "runner_artifacts") -> Optional[str]:
    if not os.path.isdir(base_dir):
        return None
    runs = [
        os.path.join(base_dir, name)
        for name in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, name))
    ]
    if not runs:
        return None
    runs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    candidate = os.path.join(runs[0], "inputs", "controller_state_60hz.jsonl")
    return candidate


def _neutral_device() -> Dict[str, Any]:
    return {
        "axes": {"LS_X": 0.0, "LS_Y": 0.0, "RS_X": 0.0, "RS_Y": 0.0, "LT": 0.0, "RT": 0.0},
        "buttons": {name: 0 for name in _BUTTON_MAP.keys()},
        "dpad": {name: 0 for name in _DPAD_MAP.keys()},
    }


def _smoke_state(cycle_time: float, last_punch_index: Optional[int]) -> Tuple[Dict[str, Any], Optional[int]]:
    segments = [
        ("idle", 1.0),
        ("walk_right", 2.0),
        ("neutral", 0.5),
        ("punch", 2.0),
        ("crouch", 1.0),
        ("block", 1.5),
    ]
    total = sum(duration for _, duration in segments)
    t = cycle_time % total

    state = _neutral_device()
    for name, duration in segments:
        if t <= duration:
            segment_time = t
            break
        t -= duration
    else:
        name = "idle"
        segment_time = 0.0

    if name == "walk_right":
        state["axes"]["LS_X"] = 0.6
    elif name == "punch":
        punch_index = int(segment_time / 0.5)
        if punch_index != last_punch_index and segment_time < 2.0:
            state["buttons"]["X"] = 1
            last_punch_index = punch_index
    elif name == "crouch":
        state["axes"]["LS_Y"] = -0.6
    elif name == "block":
        state["axes"]["LS_X"] = -0.6

    return state, last_punch_index


def run_replay(args: argparse.Namespace, gamepad: vg.VX360Gamepad) -> int:
    jsonl_path = os.path.abspath(args.jsonl)
    if not os.path.exists(jsonl_path):
        raise SystemExit(f"JSONL not found: {jsonl_path}")

    hz = float(args.hz)
    if hz <= 0:
        raise SystemExit("--hz must be > 0")
    dt = 1.0 / hz

    duration = float(args.duration)
    start_seconds = float(args.start_seconds)

    t0 = time.perf_counter()
    last_stats = t0
    frames = 0
    slept_total = 0.0

    for obj in iter_jsonl(jsonl_path):
        # Skip until start_seconds
        t_run_s = float(obj.get("t_run_s", 0.0))
        if t_run_s < start_seconds:
            continue

        now = time.perf_counter()
        elapsed = now - t0

        if duration > 0 and elapsed >= duration:
            break

        devices = obj.get("devices") or []
        if not devices:
            continue

        # Apply first device
        apply_frame(gamepad, devices[0])
        frames += 1

        # Cadence control (best-effort)
        target_next = t0 + frames * dt
        after = time.perf_counter()
        sleep_s = target_next - after
        if sleep_s > 0:
            time.sleep(sleep_s)
            slept_total += sleep_s

        # Periodic stats
        now2 = time.perf_counter()
        if (now2 - last_stats) >= float(args.stats_every):
            real_elapsed = now2 - t0
            actual_hz = frames / real_elapsed if real_elapsed > 0 else 0.0
            print(
                f"[replay] frames={frames} elapsed={real_elapsed:.2f}s "
                f"actual_hz={actual_hz:.2f} slept={slept_total:.2f}s"
            )
            last_stats = now2

    return 0


def run_smoke(args: argparse.Namespace, gamepad: vg.VX360Gamepad) -> int:
    hz = float(args.hz)
    if hz <= 0:
        raise SystemExit("--hz must be > 0")
    dt = 1.0 / hz

    duration = float(args.duration)
    if duration <= 0:
        raise SystemExit("--duration must be > 0 in smoke mode")

    t0 = time.perf_counter()
    last_stats = t0
    frames = 0
    slept_total = 0.0
    last_punch_index: Optional[int] = None

    while True:
        now = time.perf_counter()
        elapsed = now - t0
        if elapsed >= duration:
            break

        device, last_punch_index = _smoke_state(elapsed, last_punch_index)
        apply_frame(gamepad, device)
        frames += 1

        target_next = t0 + frames * dt
        after = time.perf_counter()
        sleep_s = target_next - after
        if sleep_s > 0:
            time.sleep(sleep_s)
            slept_total += sleep_s

        now2 = time.perf_counter()
        if (now2 - last_stats) >= float(args.stats_every):
            real_elapsed = now2 - t0
            actual_hz = frames / real_elapsed if real_elapsed > 0 else 0.0
            print(
                f"[smoke] frames={frames} elapsed={real_elapsed:.2f}s "
                f"actual_hz={actual_hz:.2f} slept={slept_total:.2f}s"
            )
            last_stats = now2

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay dense controller state JSONL into a virtual Xbox controller.")
    parser.add_argument(
        "--mode",
        choices=("replay", "smoke"),
        default="replay",
        help="replay = use JSONL input, smoke = deterministic autonomous loop",
    )
    parser.add_argument("--jsonl", help="Path to controller_state_XXhz.jsonl")
    parser.add_argument("--hz", type=float, default=60.0, help="Replay frequency (default: 60)")
    parser.add_argument("--duration", type=float, default=60.0, help="Duration seconds (0 = play entire file)")
    parser.add_argument("--start-seconds", type=float, default=0.0, help="Skip frames where t_run_s < start-seconds")
    parser.add_argument("--stats-every", type=float, default=2.0, help="Print stats every N seconds")
    args = parser.parse_args()

    gamepad = vg.VX360Gamepad()

    try:
        if args.mode == "smoke":
            return run_smoke(args, gamepad)
        if not args.jsonl:
            args.jsonl = _latest_run_jsonl()
            if not args.jsonl:
                raise SystemExit(
                    "No --jsonl provided and no runner_artifacts found.\n"
                    "Resolve a run and pass --jsonl explicitly."
                )
        if not os.path.exists(os.path.abspath(args.jsonl)):
            resolved = os.path.abspath(args.jsonl)
            snippet = (
                '$run = (Get-ChildItem .\\runner_artifacts -Directory | '
                'Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName\n'
                'Test-Path "$run\\inputs\\controller_state_60hz.jsonl"\n'
                'python .\\tools\\replay_controller_state.py --jsonl '
                '"$run\\inputs\\controller_state_60hz.jsonl" --hz 60 --duration 60'
            )
            raise SystemExit(
                f"JSONL not found: {resolved}\n"
                "PowerShell example:\n"
                f"{snippet}"
            )
        return run_replay(args, gamepad)
    finally:
        # Release everything on exit so we don't “stick” inputs
        try:
            # Best-effort neutral reset
            if hasattr(gamepad, "reset"):
                gamepad.reset()
            else:
                # Manual neutral: zero sticks/triggers & release buttons
                if hasattr(gamepad, "left_joystick_float") and hasattr(gamepad, "right_joystick_float"):
                    gamepad.left_joystick_float(0.0, 0.0)
                    gamepad.right_joystick_float(0.0, 0.0)
                elif hasattr(gamepad, "left_joystick") and hasattr(gamepad, "right_joystick"):
                    gamepad.left_joystick(0, 0)
                    gamepad.right_joystick(0, 0)

                if hasattr(gamepad, "left_trigger_float") and hasattr(gamepad, "right_trigger_float"):
                    gamepad.left_trigger_float(0.0)
                    gamepad.right_trigger_float(0.0)
                elif hasattr(gamepad, "left_trigger") and hasattr(gamepad, "right_trigger"):
                    gamepad.left_trigger(0)
                    gamepad.right_trigger(0)

                for btn in _BUTTON_MAP.values():
                    gamepad.release_button(btn)
                for btn in _DPAD_MAP.values():
                    gamepad.release_button(btn)
                gamepad.update()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
