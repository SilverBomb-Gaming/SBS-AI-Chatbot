from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

EVENT_TO_ACTION = {
    ("button", "A", 1): "LIGHT_KICK",
    ("button", "B", 1): "MEDIUM_KICK",
    ("button", "START", 1): "START_BUTTON",
    ("hat", "DPAD_X", -1): "DPAD_LEFT",
    ("hat", "DPAD_X", 1): "DPAD_RIGHT",
    ("hat", "DPAD_Y", -1): "DPAD_DOWN",
    ("hat", "DPAD_Y", 1): "DPAD_UP",
}

DEFAULT_DELAY_SPECS = ("LIGHT_KICK=3.0",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert controller event logs to an action script JSON"
    )
    parser.add_argument("input", type=Path, help="Path to controller_events.jsonl")
    parser.add_argument(
        "output",
        type=Path,
        help="Destination JSON file (e.g., scripts/p2_navigation.json)",
    )
    parser.add_argument(
        "--tick-seconds",
        type=float,
        default=0.25,
        help="Approximate time each trainer decision represents (default: 0.25s)",
    )
    parser.add_argument(
        "--delay-after",
        action="append",
        default=None,
        metavar="ACTION=SECONDS",
        help=(
            "Ensure at least this many seconds of NEUTRAL after ACTION. "
            "Repeatable; defaults to LIGHT_KICK=3.0"
        ),
    )
    args = parser.parse_args()
    if args.delay_after is None:
        args.delay_after = list(DEFAULT_DELAY_SPECS)
    return args


def map_event(payload: Dict[str, Any]) -> Optional[str]:
    event_type = payload.get("event_type")
    control = payload.get("control")
    value = payload.get("value")
    key = (event_type, control, value)
    return EVENT_TO_ACTION.get(key)


def append_action(script: List[Dict[str, Any]], name: str, repeat: int = 1) -> None:
    if repeat <= 0:
        return
    if script and script[-1]["action"] == name:
        script[-1]["repeat"] += repeat
    else:
        script.append({"action": name, "repeat": repeat})


def parse_delay_map(values: Sequence[str]) -> Dict[str, float]:
    mapping: Dict[str, float] = {}
    for raw in values:
        parts = raw.split("=", 1)
        if len(parts) != 2:
            raise SystemExit(
                f"Invalid --delay-after value '{raw}'. Expected format ACTION=SECONDS."
            )
        action = parts[0].strip().upper()
        try:
            seconds = float(parts[1])
        except ValueError as exc:
            raise SystemExit(
                f"Invalid delay seconds for '{raw}'. Provide a numeric value."
            ) from exc
        if seconds <= 0:
            continue
        mapping[action] = seconds
    return mapping


def enforce_action_delays(
    script: List[Dict[str, Any]],
    delay_map: Dict[str, float],
    tick_seconds: float,
) -> None:
    if not delay_map or not script:
        return
    tick = max(0.01, tick_seconds)
    idx = 0
    while idx < len(script):
        entry = script[idx]
        action_name = entry.get("action", "").upper()
        delay_seconds = delay_map.get(action_name)
        if delay_seconds is None:
            idx += 1
            continue
        required_ticks = max(1, int(math.ceil(delay_seconds / tick)))
        next_idx = idx + 1
        if next_idx < len(script) and script[next_idx]["action"] == "NEUTRAL":
            script[next_idx]["repeat"] = max(script[next_idx]["repeat"], required_ticks)
        else:
            script.insert(next_idx, {"action": "NEUTRAL", "repeat": required_ticks})
        idx = next_idx + 1


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Input file not found: {args.input}")

    delay_map = parse_delay_map(args.delay_after or [])

    events: List[Tuple[float, str]] = []
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            action_name = map_event(payload)
            if not action_name:
                continue
            t_run = float(payload.get("t_run_s", 0.0))
            events.append((t_run, action_name))

    if not events:
        raise SystemExit("No actionable events found in input log")

    base_time = events[0][0]
    normalized = [(t - base_time, name) for t, name in events]
    script: List[Dict[str, Any]] = []
    tick = max(0.05, float(args.tick_seconds))

    for idx, (curr_time, action_name) in enumerate(normalized):
        append_action(script, action_name)
        if idx == len(normalized) - 1:
            break
        next_time = normalized[idx + 1][0]
        gap = max(0.0, next_time - curr_time)
        neutral_ticks = max(0, int(round(gap / tick)) - 1)
        append_action(script, "NEUTRAL", neutral_ticks)

    enforce_action_delays(script, delay_map, tick)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(script, handle, indent=2)

    print(f"Wrote {len(script)} actions to {args.output}")


if __name__ == "__main__":
    main()
