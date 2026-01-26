"""Tests for global hotkeys."""
from __future__ import annotations

import logging

import runner.hotkeys as hotkeys


class _FakeUser32:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def RegisterHotKey(self, hwnd, hotkey_id, mods, vk):
        self.calls.append((hwnd, hotkey_id, mods, vk))
        return self._results.pop(0) if self._results else 0

    def UnregisterHotKey(self, hwnd, hotkey_id):
        return True


def test_global_hotkeys_registers_and_logs_failures(caplog):
    fake = _FakeUser32([1, 0, 1])
    with caplog.at_level(logging.WARNING):
        registered = hotkeys.GlobalHotkeyListener._register_hotkeys(fake)
    assert registered
    assert len(fake.calls) == len(hotkeys.GLOBAL_HOTKEYS)
    assert "failed to register" in caplog.text


def test_global_hotkeys_non_windows_fallback(monkeypatch, caplog):
    monkeypatch.setattr(hotkeys.sys, "platform", "linux")
    listener = hotkeys.GlobalHotkeyListener(
        on_mark=lambda: None,
        on_open_artifacts=lambda: None,
        on_manual_screenshot=lambda: None,
    )
    with caplog.at_level(logging.WARNING):
        listener.start()
    assert "Global hotkeys unavailable: platform" in caplog.text
