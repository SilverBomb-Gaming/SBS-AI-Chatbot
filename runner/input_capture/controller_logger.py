"""Controller input logging helpers for human-observed runs."""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Protocol

from runner.events import EventLogger

LOGGER = logging.getLogger(__name__)
STATUS_ON = "ON"
STATUS_OFF = "OFF"
STATUS_SKIPPED = "SKIPPED"
XINPUT_MAX_CONTROLLERS = 4
XINPUT_NOT_CONNECTED = 1167


@dataclass
class InputLoggingSummary:
    """Snapshot of controller logging results for a run."""

    status: str
    message: str
    events_captured: int = 0
    log_path: Path | None = None
    warnings: List[str] = field(default_factory=list)

    @classmethod
    def disabled(
        cls, reason: str, *, log_path: Path | None = None
    ) -> "InputLoggingSummary":
        return cls(status=STATUS_OFF, message=reason, log_path=log_path)

    @classmethod
    def skipped(
        cls, reason: str, *, warnings: List[str] | None = None
    ) -> "InputLoggingSummary":
        return cls(
            status=STATUS_SKIPPED,
            message=reason,
            warnings=list(warnings or []),
        )


@dataclass
class BackendControllerState:
    """Represents the instantaneous state of a controller device."""

    device_id: str
    index: int
    name: str
    axes: Dict[str, float] = field(default_factory=dict)
    buttons: Dict[str, int] = field(default_factory=dict)
    hats: Dict[str, int] = field(default_factory=dict)


class ControllerBackend(Protocol):
    """Interface that concrete controller polling backends must implement."""

    def initialize(self) -> None:
        ...

    def read(self) -> Dict[str, BackendControllerState]:
        ...

    def shutdown(self) -> None:
        ...


class ControllerBackendUnavailable(RuntimeError):
    """Raised when a controller backend cannot be used on this host."""


def _default_backend_factory() -> ControllerBackend:
    return PygameControllerBackend()


def resolve_backend_factory(name: str) -> Callable[[], ControllerBackend]:
    normalized = (name or "").strip().lower()
    if normalized == "xinput":
        return XInputControllerBackend
    if normalized == "stub":
        return StubControllerBackend
    if normalized != "auto":
        return PygameControllerBackend
    if sys.platform == "win32" and XInputControllerBackend.is_supported():
        return XInputControllerBackend
    return PygameControllerBackend


class ControllerLogger:
    """Background worker that polls controllers and writes JSONL events."""

    def __init__(
        self,
        log_path: Path,
        *,
        poll_interval_ms: int,
        deadzone: float,
        axis_epsilon: float,
        event_logger: EventLogger | None = None,
        backend_factory: Callable[[], ControllerBackend] | None = None,
    ) -> None:
        self.log_path = log_path
        self.poll_interval_ms = max(1, poll_interval_ms)
        self.deadzone = max(0.0, deadzone)
        self.axis_epsilon = max(0.0, axis_epsilon)
        self.event_logger = event_logger
        self._backend_factory = backend_factory or _default_backend_factory
        self._backend: ControllerBackend | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._run_started_at: float | None = None
        self._status = STATUS_OFF
        self._message = "not-started"
        self._warnings: List[str] = []
        self._events_captured = 0
        self._device_axes: Dict[str, Dict[str, float]] = {}
        self._device_buttons: Dict[str, Dict[str, int]] = {}
        self._device_hats: Dict[str, Dict[str, int]] = {}
        self._device_meta: Dict[str, BackendControllerState] = {}
        self._file_lock = threading.Lock()
        self._log_handle = None

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        try:
            self._backend = self._backend_factory()
            self._backend.initialize()
        except ControllerBackendUnavailable as exc:
            reason = str(exc) or "no compatible controller capture backend"
            self._warnings.append(reason)
            self._status = STATUS_SKIPPED
            self._message = reason
            self._log_runner_event("controller_logger_error", reason)
            return False
        except Exception as exc:  # pragma: no cover - defensive
            reason = f"controller backend failed: {exc}"
            LOGGER.warning(reason)
            self._warnings.append(reason)
            self._status = STATUS_SKIPPED
            self._message = reason
            self._log_runner_event("controller_logger_error", reason)
            return False

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._log_handle = self.log_path.open("a", encoding="utf-8")
        except OSError as exc:
            reason = f"unable to open controller log: {exc}"
            LOGGER.warning(reason)
            self._warnings.append(reason)
            self._status = STATUS_SKIPPED
            self._message = reason
            self._log_runner_event("controller_logger_error", reason)
            return False
        self._stop_event.clear()
        self._run_started_at = time.monotonic()
        self._status = STATUS_ON
        self._message = "controller logger running"
        self._log_runner_event(
            "controller_logger_start", f"controller logger started: {self.log_path}"
        )

        self._thread = threading.Thread(
            target=self._run_loop,
            name="controller-input-logger",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._backend:
            try:
                self._backend.shutdown()
            except Exception:  # pragma: no cover - defensive cleanup
                LOGGER.debug("Controller backend shutdown raised", exc_info=True)
        if self._log_handle:
            with self._file_lock:
                self._log_handle.close()
                self._log_handle = None
        if self._status == STATUS_ON:
            self._log_runner_event(
                "controller_logger_stop", f"events={self._events_captured}"
            )

    def summary(self) -> InputLoggingSummary:
        log_path = (
            self.log_path
            if self._status == STATUS_ON or self.log_path.exists()
            else None
        )
        return InputLoggingSummary(
            status=self._status,
            message=self._message,
            events_captured=self._events_captured,
            log_path=log_path,
            warnings=list(self._warnings),
        )

    def _run_loop(self) -> None:
        assert self._backend is not None
        interval = self.poll_interval_ms / 1000.0
        try:
            while not self._stop_event.is_set():
                states = self._backend.read()
                self._process_states(states)
                if self._stop_event.wait(interval):
                    break
        except Exception as exc:  # pragma: no cover - defensive
            reason = f"controller logger failed: {exc}"
            LOGGER.exception("Controller logger crashed")
            self._warnings.append(reason)
            self._message = reason
            self._status = STATUS_SKIPPED
            self._log_runner_event("controller_logger_error", reason)
        finally:
            if self._backend:
                try:
                    self._backend.shutdown()
                except Exception:  # pragma: no cover - defensive cleanup
                    LOGGER.debug("Backend shutdown raised", exc_info=True)

    def _process_states(self, states: Dict[str, BackendControllerState]) -> None:
        previous_ids = set(self._device_meta.keys())
        current_ids = set(states.keys())

        for added_id in current_ids - previous_ids:
            state = states[added_id]
            self._device_meta[added_id] = state
            self._device_axes[added_id] = {}
            self._device_buttons[added_id] = {}
            self._device_hats[added_id] = {}
            self._emit_event("connect", "device", 1, state)
            self._log_runner_event("controller_detected", f"{state.name}#{state.index}")

        for removed_id in previous_ids - current_ids:
            meta = self._device_meta.pop(removed_id)
            self._device_axes.pop(removed_id, None)
            self._device_buttons.pop(removed_id, None)
            self._device_hats.pop(removed_id, None)
            self._emit_event("disconnect", "device", 0, meta)
            self._log_runner_event(
                "controller_disconnected", f"{meta.name}#{meta.index}"
            )

        for device_id, state in states.items():
            self._device_meta[device_id] = state
            self._process_axes(device_id, state)
            self._process_buttons(device_id, state)
            self._process_hats(device_id, state)

    def _process_axes(self, device_id: str, state: BackendControllerState) -> None:
        prev_axes = self._device_axes.setdefault(device_id, {})
        curr_axes: Dict[str, float] = {}
        for control, raw_value in state.axes.items():
            normalized = self._normalize_axis(raw_value)
            previous = prev_axes.get(control)
            if previous is None:
                if abs(normalized) > 0:
                    self._emit_event("axis", control, normalized, state)
            elif abs(normalized - previous) >= self.axis_epsilon:
                self._emit_event("axis", control, normalized, state)
            curr_axes[control] = normalized
        self._device_axes[device_id] = curr_axes

    def _process_buttons(self, device_id: str, state: BackendControllerState) -> None:
        prev_buttons = self._device_buttons.setdefault(device_id, {})
        curr_buttons: Dict[str, int] = {}
        for control, value in state.buttons.items():
            prev_value = prev_buttons.get(control)
            if prev_value is None:
                if value:
                    self._emit_event("button", control, value, state)
            elif value != prev_value:
                self._emit_event("button", control, value, state)
            curr_buttons[control] = value
        self._device_buttons[device_id] = curr_buttons

    def _process_hats(self, device_id: str, state: BackendControllerState) -> None:
        prev_hats = self._device_hats.setdefault(device_id, {})
        curr_hats: Dict[str, int] = {}
        for control, value in state.hats.items():
            prev_value = prev_hats.get(control)
            if prev_value is None:
                if value != 0:
                    self._emit_event("hat", control, value, state)
            elif value != prev_value:
                self._emit_event("hat", control, value, state)
            curr_hats[control] = value
        self._device_hats[device_id] = curr_hats

    def _normalize_axis(self, value: float) -> float:
        if abs(value) < self.deadzone:
            return 0.0
        return round(float(value), 6)

    def _emit_event(
        self,
        event_type: str,
        control: str,
        value: float | int,
        state: BackendControllerState,
    ) -> None:
        if self._run_started_at is None:
            return
        payload = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "t_run_s": round(time.monotonic() - self._run_started_at, 6),
            "device": {
                "id": state.device_id,
                "index": state.index,
                "name": state.name,
            },
            "event_type": event_type,
            "control": control,
            "value": value,
        }
        line = json.dumps(payload, separators=(",", ":"))
        with self._file_lock:
            if self._log_handle:
                self._log_handle.write(line + "\n")
                self._log_handle.flush()
        self._events_captured += 1

    def _log_runner_event(self, event_type: str, message: str | None) -> None:
        if self.event_logger:
            self.event_logger.log(event_type, message)


class PygameControllerBackend(ControllerBackend):
    """Controller backend powered by pygame's joystick APIs."""

    BUTTON_NAMES = {
        0: "A",
        1: "B",
        2: "X",
        3: "Y",
        4: "LB",
        5: "RB",
        6: "BACK",
        7: "START",
        8: "LS",
        9: "RS",
    }
    AXIS_NAMES = {
        0: "LS_X",
        1: "LS_Y",
        2: "LT",
        3: "RS_X",
        4: "RS_Y",
        5: "RT",
    }

    def __init__(self) -> None:
        self._pygame = None

    def initialize(self) -> None:
        try:
            import pygame
        except ImportError as exc:  # pragma: no cover - import guard
            raise ControllerBackendUnavailable(
                "no compatible controller capture backend"
            ) from exc
        self._pygame = pygame
        if not pygame.get_init():
            pygame.init()
        pygame.joystick.init()

    def read(self) -> Dict[str, BackendControllerState]:
        if self._pygame is None:  # pragma: no cover - defensive
            raise ControllerBackendUnavailable("pygame backend unavailable")
        pygame = self._pygame
        pygame.event.pump()
        states: Dict[str, BackendControllerState] = {}
        for index in range(pygame.joystick.get_count()):
            joystick = pygame.joystick.Joystick(index)
            if not joystick.get_init():
                joystick.init()
            name = joystick.get_name() or f"controller-{index}"
            device_id = self._device_id(joystick, index)
            axes = self._read_axes(joystick)
            buttons = self._read_buttons(joystick)
            hats = self._read_hats(joystick)
            states[device_id] = BackendControllerState(
                device_id=device_id,
                index=index,
                name=name,
                axes=axes,
                buttons=buttons,
                hats=hats,
            )
        return states

    def shutdown(self) -> None:
        if self._pygame:
            self._pygame.joystick.quit()

    def _device_id(self, joystick, index: int) -> str:  # type: ignore[no-untyped-def]
        guid = getattr(joystick, "get_guid", None)
        if callable(guid):  # pygame >= 2.0
            try:
                guid_value = guid()
                if guid_value:
                    return f"{guid_value}:{index}"
            except Exception:  # pragma: no cover - defensive
                LOGGER.debug("Unable to query joystick GUID", exc_info=True)
        return f"controller-{index}"

    def _read_axes(self, joystick) -> Dict[str, float]:  # type: ignore[no-untyped-def]
        axes: Dict[str, float] = {}
        for axis_index in range(joystick.get_numaxes()):
            name = self.AXIS_NAMES.get(axis_index, f"AXIS_{axis_index}")
            axes[name] = float(joystick.get_axis(axis_index))
        return axes

    def _read_buttons(self, joystick) -> Dict[str, int]:  # type: ignore[no-untyped-def]
        buttons: Dict[str, int] = {}
        for button_index in range(joystick.get_numbuttons()):
            name = self.BUTTON_NAMES.get(button_index, f"BUTTON_{button_index}")
            buttons[name] = int(joystick.get_button(button_index))
        return buttons

    def _read_hats(self, joystick) -> Dict[str, int]:  # type: ignore[no-untyped-def]
        hats: Dict[str, int] = {}
        for hat_index in range(joystick.get_numhats()):
            hat_x, hat_y = joystick.get_hat(hat_index)
            prefix = "DPAD" if hat_index == 0 else f"DPAD{hat_index}"
            hats[f"{prefix}_X"] = int(hat_x)
            hats[f"{prefix}_Y"] = int(hat_y)
        return hats


class StubControllerBackend(ControllerBackend):
    """Stub backend that reports no connected controllers."""

    def initialize(self) -> None:
        return None

    def read(self) -> Dict[str, BackendControllerState]:
        return {}

    def shutdown(self) -> None:
        return None


if sys.platform == "win32":  # pragma: no cover - Windows-only backend
    import ctypes

    class _XInputGamepad(ctypes.Structure):
        _fields_ = [
            ("wButtons", ctypes.c_ushort),
            ("bLeftTrigger", ctypes.c_ubyte),
            ("bRightTrigger", ctypes.c_ubyte),
            ("sThumbLX", ctypes.c_short),
            ("sThumbLY", ctypes.c_short),
            ("sThumbRX", ctypes.c_short),
            ("sThumbRY", ctypes.c_short),
        ]

    class _XInputState(ctypes.Structure):
        _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _XInputGamepad)]

    _XINPUT_DLL_NAMES = (
        "xinput1_4.dll",
        "xinput1_3.dll",
        "xinput9_1_0.dll",
        "xinput1_2.dll",
        "xinput1_1.dll",
    )

    XINPUT_GAMEPAD_DPAD_UP = 0x0001
    XINPUT_GAMEPAD_DPAD_DOWN = 0x0002
    XINPUT_GAMEPAD_DPAD_LEFT = 0x0004
    XINPUT_GAMEPAD_DPAD_RIGHT = 0x0008
    XINPUT_GAMEPAD_START = 0x0010
    XINPUT_GAMEPAD_BACK = 0x0020
    XINPUT_GAMEPAD_LEFT_THUMB = 0x0040
    XINPUT_GAMEPAD_RIGHT_THUMB = 0x0080
    XINPUT_GAMEPAD_LEFT_SHOULDER = 0x0100
    XINPUT_GAMEPAD_RIGHT_SHOULDER = 0x0200
    XINPUT_GAMEPAD_A = 0x1000
    XINPUT_GAMEPAD_B = 0x2000
    XINPUT_GAMEPAD_X = 0x4000
    XINPUT_GAMEPAD_Y = 0x8000

    def _load_xinput():
        for name in _XINPUT_DLL_NAMES:
            try:
                return ctypes.WinDLL(name)
            except OSError:
                continue
        return None

    class XInputControllerBackend(ControllerBackend):
        """Controller backend powered by Windows XInput APIs."""

        BUTTON_BITS = {
            "A": XINPUT_GAMEPAD_A,
            "B": XINPUT_GAMEPAD_B,
            "X": XINPUT_GAMEPAD_X,
            "Y": XINPUT_GAMEPAD_Y,
            "LB": XINPUT_GAMEPAD_LEFT_SHOULDER,
            "RB": XINPUT_GAMEPAD_RIGHT_SHOULDER,
            "BACK": XINPUT_GAMEPAD_BACK,
            "START": XINPUT_GAMEPAD_START,
            "LS": XINPUT_GAMEPAD_LEFT_THUMB,
            "RS": XINPUT_GAMEPAD_RIGHT_THUMB,
        }

        def __init__(self) -> None:
            self._xinput = None

        @classmethod
        def is_supported(cls) -> bool:
            return _load_xinput() is not None

        def initialize(self) -> None:
            self._xinput = _load_xinput()
            if self._xinput is None:
                raise ControllerBackendUnavailable("xinput DLL not found")
            self._xinput.XInputGetState.argtypes = [
                ctypes.c_uint,
                ctypes.POINTER(_XInputState),
            ]
            self._xinput.XInputGetState.restype = ctypes.c_uint

        def read(self) -> Dict[str, BackendControllerState]:
            if self._xinput is None:
                raise ControllerBackendUnavailable("xinput backend unavailable")
            states: Dict[str, BackendControllerState] = {}
            for index in range(XINPUT_MAX_CONTROLLERS):
                raw_state = _XInputState()
                result = self._xinput.XInputGetState(index, ctypes.byref(raw_state))
                if result == XINPUT_NOT_CONNECTED:
                    continue
                gamepad = raw_state.Gamepad
                axes = {
                    "LS_X": _normalize_thumb(gamepad.sThumbLX),
                    "LS_Y": _normalize_thumb(gamepad.sThumbLY),
                    "RS_X": _normalize_thumb(gamepad.sThumbRX),
                    "RS_Y": _normalize_thumb(gamepad.sThumbRY),
                    "LT": round(gamepad.bLeftTrigger / 255.0, 6),
                    "RT": round(gamepad.bRightTrigger / 255.0, 6),
                }
                buttons = {
                    name: 1 if (gamepad.wButtons & bit) else 0
                    for name, bit in self.BUTTON_BITS.items()
                }
                hats = _xinput_hats(gamepad.wButtons)
                states[f"xinput-{index}"] = BackendControllerState(
                    device_id=f"xinput-{index}",
                    index=index,
                    name="XInput Controller",
                    axes=axes,
                    buttons=buttons,
                    hats=hats,
                )
            return states

        def shutdown(self) -> None:
            return None

    def _normalize_thumb(value: int) -> float:
        if value < 0:
            return max(-1.0, value / 32768.0)
        return min(1.0, value / 32767.0)

    def _xinput_hats(buttons: int) -> Dict[str, int]:
        x = 0
        y = 0
        if buttons & XINPUT_GAMEPAD_DPAD_LEFT:
            x -= 1
        if buttons & XINPUT_GAMEPAD_DPAD_RIGHT:
            x += 1
        if buttons & XINPUT_GAMEPAD_DPAD_UP:
            y += 1
        if buttons & XINPUT_GAMEPAD_DPAD_DOWN:
            y -= 1
        return {"DPAD_X": x, "DPAD_Y": y}

else:

    def _load_xinput():
        return None

    class XInputControllerBackend(ControllerBackend):
        """Placeholder XInput backend for non-Windows platforms."""

        @classmethod
        def is_supported(cls) -> bool:
            return False

        def initialize(self) -> None:
            raise ControllerBackendUnavailable("xinput only available on Windows")

        def read(self) -> Dict[str, BackendControllerState]:
            return {}

        def shutdown(self) -> None:
            return None
