#!/usr/bin/env python3
from __future__ import annotations

"""Keep a virtual Xbox 360 controller alive for stable P2 assignment."""

import argparse
import time

import vgamepad as vg


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


def _release_all(gamepad: vg.VX360Gamepad) -> None:
    if hasattr(gamepad, "left_joystick_float"):
        gamepad.left_joystick_float(0.0, 0.0)
    else:
        gamepad.left_joystick(0, 0)
    for button in (
        vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    ):
        gamepad.release_button(button=button)
    for button in (
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    ):
        gamepad.release_button(button=button)
    gamepad.update()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Keep a virtual controller alive; optionally tap A to confirm P2."
    )
    parser.add_argument("--tap-a", action="store_true", help="Tap the A button before idling.")
    parser.add_argument("--tap-count", type=int, default=1, help="Number of A taps to send.")
    parser.add_argument("--tap-hold-seconds", type=float, default=0.08, help="Seconds to hold A per tap.")
    parser.add_argument("--tap-interval-seconds", type=float, default=0.6, help="Seconds between A taps.")
    parser.add_argument(
        "--keep-alive-seconds",
        type=float,
        default=30.0,
        help="Duration to keep the controller active. Use 0 for indefinite.",
    )
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
        _release_all(gamepad)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
