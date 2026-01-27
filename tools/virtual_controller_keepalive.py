#!/usr/bin/env python3
from __future__ import annotations

"""Keep a virtual Xbox 360 controller alive for stable P2 assignment."""

import sys
from pathlib import Path

# Ensure repo root is on sys.path so `import agent...` works even when run as a script
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import argparse
import time

import vgamepad as vg

from agent.action_set import release_all


def _tap_a(
    gamepad: vg.VX360Gamepad,
    *,
    count: int,
    hold_seconds: float,
    interval_seconds: float,
) -> None:
    for _ in range(max(1, count)):
        gamepad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        gamepad.update()
        time.sleep(max(0.0, hold_seconds))
        gamepad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        gamepad.update()
        time.sleep(max(0.0, interval_seconds))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Keep a virtual controller alive; optionally tap A to confirm P2."
    )
    parser.add_argument("--tap-a", action="store_true", help="Tap the A button before idling.")
    parser.add_argument("--tap-count", type=int, default=1, help="Number of A taps to send.")
    parser.add_argument("--tap-hold-seconds", type=float, default=0.08, help="Seconds to hold A per tap.")
    parser.add_argument("--tap-interval-seconds", type=float, default=0.6, help="Seconds between A taps.")
    parser.add_argument("--keep-alive-seconds", type=float, default=0.0, help="0 = run until Ctrl+C.")
    parser.add_argument("--exit-after-tap", action="store_true", help="Exit immediately after tap (no keep-alive).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    gamepad = vg.VX360Gamepad()
    print("Virtual controller created.")

    try:
        if args.tap_a:
            print("Sending A tap(s) to confirm P2 assignment...")
            _tap_a(
                gamepad,
                count=args.tap_count,
                hold_seconds=args.tap_hold_seconds,
                interval_seconds=args.tap_interval_seconds,
            )

        if args.exit_after_tap:
            return 0

        if args.keep_alive_seconds and args.keep_alive_seconds > 0:
            print(f"Keeping controller alive for {args.keep_alive_seconds:.1f}s...")
            time.sleep(args.keep_alive_seconds)
        else:
            print("Keeping controller alive. Press Ctrl+C to exit.")
            while True:
                time.sleep(1.0)

    except KeyboardInterrupt:
        print("Stopping keep-alive.")
    finally:
        release_all(gamepad)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
