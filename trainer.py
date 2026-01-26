#!/usr/bin/env python3
"""Closed-loop trainer: observe -> decide -> act -> reward -> learn."""
from __future__ import annotations

import argparse
import json
import random
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import vgamepad as vg

try:  # Optional dependency for screenshot capture
    import mss  # type: ignore
    from mss import tools as mss_tools  # type: ignore
except ImportError:  # pragma: no cover - environment specific
    mss = None  # type: ignore
    mss_tools = None  # type: ignore

from agent.action_set import ACTIONS, Action, action_names, apply_action, get_action, release_all
from agent.q_learner import QLearner
from agent.reward import DEFAULT_IDLE_PENALTY, compute_reward, net_advantage
from agent.state import make_state
from reporting.training_report import generate_report
from runner.target_detect import lock_target
from runner.capture import _find_window_rect  # type: ignore


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

    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_root = Path("training_runs") / run_ts
    screenshots_dir = (
        Path(args.screenshot_dir)
        if args.screenshot_dir
        else run_root / "screenshots"
    )
    run_root.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    transitions_path = run_root / "transitions.jsonl"
    summaries_path = run_root / "episode_summaries.json"

    policy_path = Path(args.policy_path)
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
    if not args.no_vision:
        try:
            from runner.health_bar import HealthBarTracker

            tracker = HealthBarTracker()
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

                while time.perf_counter() < episode_end:
                    if stop_requested:
                        break
                    now = time.perf_counter()
                    t_run = now - episode_start
                    capture_region = _capture_region(target_pid, args.capture_mode)
                    shot = screen.grab(capture_region or monitor)
                    width, height = shot.size
                    frame = shot.rgb

                    screenshot_path = screenshots_dir / f"ep{episode_idx:03d}_step{step_idx:05d}.png"
                    _save_screenshot(frame, (width, height), screenshot_path)

                    my_hp = 1.0
                    enemy_hp = 1.0
                    if tracker is not None:
                        from PIL import Image  # type: ignore

                        image = Image.frombytes("RGB", (width, height), frame)
                        my_hp, enemy_hp = tracker.update(image)

                    if episode_health_start is None:
                        episode_health_start = (my_hp, enemy_hp)

                    reward = 0.0
                    delta_enemy = 0.0
                    delta_me = 0.0
                    if prev_health is not None and tracker is not None:
                        reward, delta_enemy, delta_me = compute_reward(
                            enemy_prev=prev_health["enemy"],
                            enemy_now=enemy_hp,
                            me_prev=prev_health["me"],
                            me_now=my_hp,
                            idle_penalty=args.idle_penalty,
                        )

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
                }
                episode_summaries.append(summary)
                summaries_path.write_text(
                    json.dumps({"episodes": episode_summaries}, indent=2),
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
    generate_report(
        transitions_path=transitions_path,
        summaries_path=summaries_path,
        output_path=report_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
