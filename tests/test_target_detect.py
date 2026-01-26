"""Tests for target detection helpers."""
from __future__ import annotations

import pytest

from runner import target_detect


class _FakeClock:
    def __init__(self) -> None:
        self._now = 0.0

    def now(self) -> float:
        return self._now

    def advance(self, delta: float) -> None:
        self._now += max(0.0, delta)

    def sleep(self, delta: float) -> None:
        self.advance(delta)


def _make_target(process: str, title: str, *, pid: int = 123) -> target_detect.TargetInfo:
    return target_detect.TargetInfo(
        hwnd=pid + 10,
        pid=pid,
        exe_path=f"C:/Games/{process}",
        process_name=process,
        window_title=title,
    )


def test_sanitize_name_replaces_symbols() -> None:
    assert target_detect.sanitize_name("Street Fighter 6.exe") == "street-fighter-6-exe"
    assert target_detect.sanitize_name("@@weird__name!!", fallback="unk") == "weird-name"


def test_lock_target_skips_filtered_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = _FakeClock()
    explorer = _make_target("explorer.exe", "Task Switching", pid=1)
    street_fighter = _make_target("StreetFighter6.exe", "Street Fighter 6", pid=2)
    sequence = [explorer] * 5 + [street_fighter] * 6

    def _fake_detect() -> target_detect.TargetInfo:
        index = min(_fake_detect.calls, len(sequence) - 1)
        _fake_detect.calls += 1
        fake_time.advance(0.2)
        return sequence[index]

    _fake_detect.calls = 0  # type: ignore[attr-defined]
    monkeypatch.setattr(target_detect, "detect_foreground_target", _fake_detect)

    locked = target_detect.lock_target(
        mode="first-non-terminal",
        lock_seconds=1,
        poll_ms=200,
        ignore_processes=("explorer.exe",),
        logger=None,
        clock=fake_time.now,
        sleeper=fake_time.sleep,
    )

    assert locked is not None
    assert locked.info.process_name == "StreetFighter6.exe"
    assert locked.label.startswith("streetfighter6")
