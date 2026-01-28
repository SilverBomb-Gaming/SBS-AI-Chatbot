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
    Action("MEDIUM_PUNCH", buttons=("Y",), tap=True),
    Action("HEAVY_PUNCH", buttons=("RB",), tap=True),
    Action("LIGHT_KICK", buttons=("A",), tap=True),
    Action("MEDIUM_KICK", buttons=("B",), tap=True),
    Action("HEAVY_KICK", buttons=("LB",), tap=True),
    Action("DPAD_LEFT", buttons=("DPAD_LEFT",), tap=True),
    Action("DPAD_RIGHT", buttons=("DPAD_RIGHT",), tap=True),
    Action("DPAD_UP", buttons=("DPAD_UP",), tap=True),
    Action("DPAD_DOWN", buttons=("DPAD_DOWN",), tap=True),
    Action("CROUCH_LIGHT_PUNCH", ls_y=-1.0, buttons=("X",), tap=True),
    Action("CROUCH_MEDIUM_PUNCH", ls_y=-1.0, buttons=("Y",), tap=True),
    Action("CROUCH_HEAVY_KICK", ls_y=-1.0, buttons=("B",), tap=True),
    Action("JUMP_NEUTRAL", ls_y=0.8),
    Action("JUMP_FORWARD", ls_x=0.5, ls_y=0.8),
    Action("JUMP_BACK", ls_x=-0.5, ls_y=0.8),
    Action("JUMP_NEUTRAL_PUNCH", ls_y=0.8, buttons=("X",), tap=True),
    Action("JUMP_FORWARD_KICK", ls_x=0.5, ls_y=0.8, buttons=("B",), tap=True),
    Action("START_BUTTON", buttons=("START",), tap=True),
]

_BUTTON_ALIASES = {
    "A": "XUSB_GAMEPAD_A",
    "B": "XUSB_GAMEPAD_B",
    "X": "XUSB_GAMEPAD_X",
    "Y": "XUSB_GAMEPAD_Y",
    "LB": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "LS": "XUSB_GAMEPAD_LEFT_THUMB",
    "RS": "XUSB_GAMEPAD_RIGHT_THUMB",
    "BACK": "XUSB_GAMEPAD_BACK",
    "START": "XUSB_GAMEPAD_START",
    "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP",
    "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
    "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT",
    "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
}


def resolve_button(name: str) -> vg.XUSB_BUTTON | None:
    key = (name or "").strip().upper()
    attr = _BUTTON_ALIASES.get(key)
    if not attr:
        return None
    return getattr(vg.XUSB_BUTTON, attr, None)


def action_names() -> List[str]:
    return [action.name for action in ACTIONS]


def get_action(name: str) -> Action:
    for action in ACTIONS:
        if action.name == name:
            return action
    raise KeyError(f"Unknown action: {name}")


def _press_buttons(gamepad: vg.VX360Gamepad, buttons: Iterable[str]) -> None:
    for name in buttons:
        btn = resolve_button(name)
        if btn is None:
            continue
        gamepad.press_button(btn)


def _release_buttons(gamepad: vg.VX360Gamepad, buttons: Iterable[str]) -> None:
    for name in buttons:
        btn = resolve_button(name)
        if btn is None:
            continue
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
        btn = resolve_button(name)
        if btn is None:
            continue
        gamepad.release_button(btn)
    for btn in (
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
        vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    ):
        gamepad.release_button(btn)
    gamepad.update()
