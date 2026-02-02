"""Regression coverage for engine adapter guardrails."""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_e.engine import RunContext, UnityEngineAdapter
import ai_e.engine.unity_adapter as unity_module
from core.run_contract import ensure_training_run_contract
from runner.target_detect import TargetInfo


@pytest.fixture(name="run_contract")
def _run_contract(tmp_path: Path) -> tuple[str, Path]:
    training_root = tmp_path / "training_runs"
    training_root.mkdir()
    run_id = "run_guardrail"
    contract = ensure_training_run_contract(training_root / run_id)
    return run_id, contract


def test_unity_adapter_observation_enforces_window_only(monkeypatch, run_contract) -> None:
    run_id, contract = run_contract
    ctx = RunContext(run_id=run_id, paths=contract, mode="unity")
    adapter = UnityEngineAdapter()
    adapter.start_session(ctx)

    # Force environment to look like a Windows window-capture setup.
    monkeypatch.setattr(unity_module.sys, "platform", "win32")
    monkeypatch.setattr(unity_module.capture_module, "mss", object())

    recorded: dict[str, object] = {}

    def fake_validate(mode: str, hwnd: int | None) -> None:
        recorded["mode"] = mode
        recorded["hwnd"] = hwnd

    monkeypatch.setattr(unity_module, "validate_window_capture_requirements", fake_validate)

    target = TargetInfo(
        hwnd=123,
        pid=456,
        exe_path="C:/Unity/Editor.exe",
        process_name="Unity.exe",
        window_title="Unity - SampleScene",
    )
    monkeypatch.setattr(unity_module, "detect_foreground_target", lambda: target)
    monkeypatch.setattr(unity_module.capture_module, "_find_window_rect", lambda _pid: (10, 10, 210, 130))

    class DummyRecorder:
        def __init__(self) -> None:
            self.pid_attached: int | None = None

        def attach_unity_pid(self, pid: int) -> None:
            self.pid_attached = pid

        def capture_now(self, label: str = "observe") -> Path:
            output = contract.screenshots_dir / f"{label}.png"
            output.write_bytes(b"stub")
            return output

    recorder = DummyRecorder()
    monkeypatch.setattr(adapter, "_build_recorder", lambda _paths: recorder)

    observation = adapter.capture_observation()

    assert recorded["mode"] == "window"
    assert recorded["hwnd"] == target.hwnd
    assert recorder.pid_attached == target.pid
    assert observation.frame_path
    assert Path(observation.frame_path).parent == contract.screenshots_dir
    assert observation.frame and observation.frame.width == 200 and observation.frame.height == 120


def test_unity_adapter_recorder_uses_window_capture(run_contract) -> None:
    run_id, contract = run_contract
    adapter = UnityEngineAdapter()
    recorder = adapter._build_recorder(contract)
    assert recorder.capture_mode == "unity_window"
    assert recorder.artifacts.screenshots_dir == contract.screenshots_dir
