"""Keyboard helpers for human-observed Unity runs."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

LOGGER = logging.getLogger(__name__)

if sys.platform == "win32":  # pragma: no cover - Windows-only helper
    import ctypes
    import ctypes.wintypes as wintypes

    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    VK_F8 = 0x77
    VK_F9 = 0x78
    VK_F10 = 0x79
    VK_F11 = 0x7A
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012

    HOTKEY_MARK = 1
    HOTKEY_OPEN = 2
    HOTKEY_SCREENSHOT = 3
    HOTKEY_STOP = 4

    GLOBAL_HOTKEYS = {
        HOTKEY_MARK: (MOD_CONTROL | MOD_ALT, VK_F8, "mark"),
        HOTKEY_OPEN: (MOD_CONTROL | MOD_ALT, VK_F9, "open_artifacts"),
        HOTKEY_SCREENSHOT: (MOD_CONTROL | MOD_ALT, VK_F10, "manual_screenshot"),
        HOTKEY_STOP: (MOD_CONTROL | MOD_ALT, VK_F11, "stop_run"),
    }


class HotkeyListener:
    """Best-effort listener for F8/F9/F10 hotkeys on Windows consoles."""

    def __init__(
        self,
        *,
        on_mark: Callable[[], None],
        on_open_artifacts: Callable[[], None],
        on_manual_screenshot: Callable[[], None],
    ) -> None:
        self._on_mark = on_mark
        self._on_open_artifacts = on_open_artifacts
        self._on_manual_screenshot = on_manual_screenshot
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._msvcrt = None

    def start(self) -> None:
        if sys.platform != "win32":
            LOGGER.info("Hotkeys disabled on platform %s", sys.platform)
            return
        try:
            import msvcrt  # type: ignore
        except ImportError:  # pragma: no cover - platform specific
            LOGGER.warning("msvcrt module unavailable; hotkeys disabled for this run")
            return
        self._msvcrt = msvcrt
        self._thread = threading.Thread(
            target=self._loop, name="runner-hotkeys", daemon=True
        )
        self._thread.start()
        LOGGER.info("Hotkeys armed: F8=MARK, F9=Open artifacts, F10=Screenshot")

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> None:
        assert self._msvcrt is not None
        try:
            while not self._stop_event.is_set():
                if self._msvcrt.kbhit():  # type: ignore[attr-defined]
                    key = self._msvcrt.getwch()  # type: ignore[attr-defined]
                    if key in {"\x00", "\xe0"}:
                        code = self._msvcrt.getwch()  # type: ignore[attr-defined]
                        self._handle_function_key(code)
                else:
                    time.sleep(0.05)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Hotkey listener stopped: %s", exc)

    def _handle_function_key(self, code: str) -> None:
        actions = {
            "B": self._on_mark,  # F8
            "C": self._on_open_artifacts,  # F9
            "D": self._on_manual_screenshot,  # F10
        }
        action = actions.get(code)
        if not action:
            return
        try:
            action()
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Hotkey callback failed: %s", exc)


class ManualStopController:
    """Simple ENTER-to-stop helper for human runs."""

    def __init__(self, on_stop: Callable[[], None]) -> None:
        self._on_stop = on_stop
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not sys.stdin or not sys.stdin.isatty():
            LOGGER.info("Manual stop prompt disabled (STDIN not interactive)")
            return
        self._thread = threading.Thread(
            target=self._wait_for_enter, name="runner-stop", daemon=True
        )
        self._thread.start()
        print("Press ENTER in this terminal at any time to stop the run.")

    def stop(self) -> None:
        self._stop_event.set()

    def _wait_for_enter(self) -> None:
        try:
            sys.stdin.readline()
        except Exception:  # pragma: no cover - defensive
            LOGGER.warning("Manual stop listener failed; please Ctrl+C to end run")
            return
        if not self._stop_event.is_set():
            self._on_stop()


class TerminalCommandController:
    """Command loop for terminals where hotkeys are unreliable."""

    def __init__(
        self,
        *,
        on_mark: Callable[[], None],
        on_open_artifacts: Callable[[], None],
        on_manual_screenshot: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        self._on_mark = on_mark
        self._on_open_artifacts = on_open_artifacts
        self._on_manual_screenshot = on_manual_screenshot
        self._on_stop = on_stop
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not sys.stdin or not sys.stdin.isatty():
            LOGGER.warning("Terminal command loop disabled (STDIN not interactive)")
            return
        self._thread = threading.Thread(
            target=self._loop, name="runner-terminal-commands", daemon=True
        )
        self._thread.start()
        print("Press ENTER in this terminal at any time to stop the run.")

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                line = sys.stdin.readline()
                if line == "":
                    return
                command = line.strip().lower()
                if command == "":
                    self._on_stop()
                    return
                if command == "m":
                    self._on_mark()
                elif command == "s":
                    self._on_manual_screenshot()
                elif command == "o":
                    self._on_open_artifacts()
                elif command == "?":
                    print(
                        "Commands: m=mark, s=screenshot, o=open artifacts, ENTER=stop"
                    )
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Terminal command loop failed: %s", exc)


class GlobalHotkeyListener:
    """RegisterHotKey-based listener for global hotkeys on Windows."""

    def __init__(
        self,
        *,
        on_mark: Callable[[], None],
        on_open_artifacts: Callable[[], None],
        on_manual_screenshot: Callable[[], None],
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        self._on_mark = on_mark
        self._on_open_artifacts = on_open_artifacts
        self._on_manual_screenshot = on_manual_screenshot
        self._on_stop = on_stop
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._registered: set[int] = set()
        self._stop_event = threading.Event()

    def start(self) -> None:
        if sys.platform != "win32":
            LOGGER.warning("Global hotkeys unavailable: platform %s", sys.platform)
            return
        self._thread = threading.Thread(
            target=self._loop, name="runner-global-hotkeys", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if sys.platform != "win32":
            return
        self._stop_event.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _loop(self) -> None:
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        callbacks = {
            HOTKEY_MARK: self._on_mark,
            HOTKEY_OPEN: self._on_open_artifacts,
            HOTKEY_SCREENSHOT: self._on_manual_screenshot,
            HOTKEY_STOP: self._on_stop,
        }
        self._registered = self._register_hotkeys(user32)
        if not self._registered:
            return
        LOGGER.info("Global hotkeys enabled (RegisterHotKey)")
        msg = wintypes.MSG()
        try:
            while not self._stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    LOGGER.warning("Global hotkeys unavailable: GetMessage failure")
                    break
                if msg.message == WM_HOTKEY:
                    callback = callbacks.get(msg.wParam)
                    if callback:
                        try:
                            callback()
                        except Exception as exc:  # pragma: no cover - defensive
                            LOGGER.warning("Global hotkey callback failed: %s", exc)
        finally:
            self._unregister_hotkeys(user32, self._registered)
            self._registered.clear()

    @staticmethod
    def _register_hotkeys(user32) -> set[int]:
        registered: set[int] = set()
        for hotkey_id, (mods, vk, label) in GLOBAL_HOTKEYS.items():
            result = user32.RegisterHotKey(None, hotkey_id, mods, vk)
            if result:
                registered.add(hotkey_id)
            else:
                LOGGER.warning(
                    "Global hotkeys unavailable: failed to register %s", label
                )
        if not registered:
            LOGGER.warning("Global hotkeys unavailable: no hotkeys registered")
        return registered

    @staticmethod
    def _unregister_hotkeys(user32, hotkey_ids: set[int]) -> None:
        for hotkey_id in hotkey_ids:
            user32.UnregisterHotKey(None, hotkey_id)


def open_artifacts_folder(path: Path) -> None:
    """Attempt to open the artifacts directory in the native file explorer."""

    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning("Unable to open artifacts folder: %s", exc)
