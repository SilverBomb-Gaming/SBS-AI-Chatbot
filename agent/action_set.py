"""Discrete action set and controller mappings for SF6."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, List, Sequence

import vgamepad as vg


@dataclass(frozen=True)
class Action:
    name: str
    ls_x: float = 0.0
    ls_y: float = 0.0
    buttons: Sequence[str] = ()
    tap: bool = False


ACTIONS: List[Action] = [
    Action("NEUTRAL"),
    Action("WALK_LEFT", ls_x=-0.6),
    Action("WALK_RIGHT", ls_x=0.6),
    Action("CROUCH_BLOCK", ls_x=-0.6, ls_y=-0.6),
    Action("STAND_BLOCK", ls_x=-0.6),
    Action("LIGHT_PUNCH", buttons=("X",), tap=True),
    Action("LIGHT_KICK", buttons=("A",), tap=True),
]


def action_names() -> List[str]:
    return [action.name for action in ACTIONS]


def get_action(name: str) -> Action:
    for action in ACTIONS:
        if action.name == name:
            return action
    raise KeyError(f"Unknown action: {name}")


def _press_buttons(gamepad: vg.VX360Gamepad, buttons: Iterable[str]) -> None:
    for name in buttons:
        btn = getattr(vg.XUSB_BUTTON, f"XUSB_GAMEPAD_{name}")
        gamepad.press_button(btn)


def _release_buttons(gamepad: vg.VX360Gamepad, buttons: Iterable[str]) -> None:
    for name in buttons:
        btn = getattr(vg.XUSB_BUTTON, f"XUSB_GAMEPAD_{name}")
        gamepad.release_button(btn)


def apply_action(gamepad: vg.VX360Gamepad, action: Action) -> None:
    if hasattr(gamepad, "left_joystick_float"):
        gamepad.left_joystick_float(action.ls_x, action.ls_y)
    else:
        gamepad.left_joystick(int(action.ls_x * 32767), int(action.ls_y * 32767))

    _press_buttons(gamepad, action.buttons)
    gamepad.update()

    if action.tap and action.buttons:
        time.sleep(0.03)
        _release_buttons(gamepad, action.buttons)
        gamepad.update()


def release_all(gamepad: vg.VX360Gamepad) -> None:
    if hasattr(gamepad, "left_joystick_float"):
        gamepad.left_joystick_float(0.0, 0.0)
    else:
        gamepad.left_joystick(0, 0)
    for name in ("A", "B", "X", "Y", "LB", "RB", "BACK", "START", "LS", "RS"):
        btn = getattr(vg.XUSB_BUTTON, f"XUSB_GAMEPAD_{name}")
        gamepad.release_button(btn)
    for btn in (
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    ):
        gamepad.release_button(btn)
    gamepad.update()
