"""Generate a Markdown training report for closed-loop runs."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple


@dataclass
class EpisodeSummary:
    episode_idx: int
    total_reward: float
    net_advantage: float


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _load_episode_summaries(path: Path) -> tuple[List[EpisodeSummary], dict]:
    if not path.exists():
        return [], {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    summaries: List[EpisodeSummary] = []
    for item in payload.get("episodes", []):
        summaries.append(
            EpisodeSummary(
                episode_idx=int(item.get("episode_idx", 0)),
                total_reward=float(item.get("total_reward", 0.0)),
                net_advantage=float(item.get("net_advantage", 0.0)),
            )
        )
    meta = {
        "roi_mode": payload.get("roi_mode"),
        "roi_px": payload.get("roi_px"),
        "hud_y_offset_px": payload.get("hud_y_offset_px"),
    }
    return summaries, meta


def _trend_slope(points: List[Tuple[int, float]]) -> float:
    if len(points) < 2:
        return 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_mean = mean(xs)
    y_mean = mean(ys)
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    return num / den if den else 0.0


def generate_report(
    *,
    transitions_path: Path,
    summaries_path: Path,
    output_path: Path,
) -> None:
    transitions = _load_jsonl(transitions_path)
    summaries, meta = _load_episode_summaries(summaries_path)

    if summaries:
        avg_reward = mean(s.total_reward for s in summaries)
        best = max(summaries, key=lambda s: s.net_advantage)
        worst = min(summaries, key=lambda s: s.net_advantage)
        trend = _trend_slope([(s.episode_idx, s.net_advantage) for s in summaries])
    else:
        avg_reward = 0.0
        best = None
        worst = None
        trend = 0.0

    action_stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {"count": 0, "reward": 0.0, "d_enemy": 0.0, "d_me": 0.0})
    time_bucket_stats: Dict[int, List[float]] = defaultdict(list)
    screen_deltas: List[float] = []
    delta_threshold: float | None = None
    delta_gt_count = 0
    epsilons: List[float] = []

    for row in transitions:
        action = row.get("action", "UNKNOWN")
        reward = float(row.get("reward", 0.0))
        d_enemy = float(row.get("delta_enemy", 0.0))
        d_me = float(row.get("delta_me", 0.0))
        time_bucket = int(row.get("time_bucket", 0))
        if "screen_delta" in row:
            try:
                screen_delta = float(row.get("screen_delta", 0.0))
                screen_deltas.append(screen_delta)
            except (TypeError, ValueError):
                pass
        if delta_threshold is None and row.get("delta_threshold") is not None:
            try:
                delta_threshold = float(row.get("delta_threshold"))
            except (TypeError, ValueError):
                delta_threshold = None
        epsilon = row.get("epsilon")
        if epsilon is not None:
            try:
                epsilons.append(float(epsilon))
            except (TypeError, ValueError):
                pass
        stats = action_stats[action]
        stats["count"] += 1
        stats["reward"] += reward
        stats["d_enemy"] += d_enemy
        stats["d_me"] += d_me
        time_bucket_stats[time_bucket].append(reward)
        if delta_threshold is not None and "screen_delta" in row:
            try:
                if float(row.get("screen_delta", 0.0)) > delta_threshold:
                    delta_gt_count += 1
            except (TypeError, ValueError):
                pass

    action_rows = []
    for action, stats in action_stats.items():
        count = stats["count"]
        if count <= 0:
            continue
        action_rows.append(
            (
                action,
                stats["reward"] / count,
                count,
                stats["d_enemy"] / count,
                stats["d_me"] / count,
            )
        )
    action_rows.sort(key=lambda r: r[1], reverse=True)

    excelled = action_rows[:3]
    needs_work = action_rows[-3:] if len(action_rows) >= 3 else action_rows

    high_damage = sorted(
        [(bucket, mean(vals)) for bucket, vals in time_bucket_stats.items()],
        key=lambda x: x[1],
    )[:3]

    epsilon_start = epsilons[0] if epsilons else None
    epsilon_end = epsilons[-1] if epsilons else None

    lines: List[str] = []
    lines.append("# Training Report")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Episodes: {len(summaries)}")
    lines.append(f"- Average reward per episode: {avg_reward:.4f}")
    if meta.get("roi_mode"):
        lines.append(f"- ROI mode: {meta['roi_mode']}")
    if meta.get("hud_y_offset_px") is not None:
        lines.append(f"- HUD y-offset px: {meta['hud_y_offset_px']}")
    if meta.get("roi_px"):
        lines.append(f"- ROI px: {meta['roi_px']}")
    if screen_deltas:
        lines.append(f"- Avg screen delta: {mean(screen_deltas):.4f}")
        if delta_threshold is not None:
            pct_delta = (delta_gt_count / max(1, len(screen_deltas))) * 100.0
            lines.append(f"- Steps delta > threshold: {pct_delta:.1f}% (threshold={delta_threshold:.3f})")
    if best:
        lines.append(f"- Best episode: {best.episode_idx} (net_advantage={best.net_advantage:.4f})")
    if worst:
        lines.append(f"- Worst episode: {worst.episode_idx} (net_advantage={worst.net_advantage:.4f})")
    if trend > 0:
        lines.append(f"- Trend: improving (slope={trend:.4f})")
    elif trend < 0:
        lines.append(f"- Trend: declining (slope={trend:.4f})")
    else:
        lines.append("- Trend: flat")
    if epsilon_start is not None and epsilon_end is not None:
        lines.append(f"- Epsilon: {epsilon_start:.3f} -> {epsilon_end:.3f}")

    lines.append("")
    lines.append("## Excelled In")
    if excelled:
        for action, avg, count, d_enemy, d_me in excelled:
            lines.append(
                f"- {action}: avg_reward={avg:.4f}, count={count}, damage_dealt={d_enemy:.4f}, damage_taken={d_me:.4f}"
            )
    else:
        lines.append("- No action data available.")

    lines.append("")
    lines.append("## Needs Work")
    if needs_work:
        for action, avg, count, d_enemy, d_me in needs_work:
            lines.append(
                f"- {action}: avg_reward={avg:.4f}, count={count}, damage_dealt={d_enemy:.4f}, damage_taken={d_me:.4f}"
            )
    else:
        lines.append("- No action data available.")

    if high_damage:
        lines.append("")
        lines.append("## High Damage Periods")
        for bucket, avg_reward in high_damage:
            lines.append(f"- time_bucket {bucket}: avg_reward={avg_reward:.4f}")

    lines.append("")
    lines.append("## Action Histogram")
    for action, avg, count, _, _ in action_rows:
        lines.append(f"- {action}: count={count}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
