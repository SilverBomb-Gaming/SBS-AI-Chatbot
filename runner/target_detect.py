"""Windows foreground target detection helpers."""
from __future__ import annotations

import ctypes
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

MIN_POLL_SECONDS = 0.05
DEFAULT_SANITIZE_MAX = 48
WINDOW_TITLE_BLOCKLIST = ("task switching", "alt-tab", "task view")
MODE_ALIASES = {
    "foreground": "foreground-at-start",
    "explicit": "exe",
}
SELF_EXE_NAMES = {
    os.path.basename(sys.executable).lower() if sys.executable else "python.exe",
    "python.exe",
    "pythonw.exe",
}


@dataclass(frozen=True)
class TargetInfo:
    hwnd: int
    pid: int
    exe_path: str
    process_name: str
    window_title: str


@dataclass(frozen=True)
class LockedTarget:
    info: TargetInfo
    label: str
    hash_suffix: str
    locked_at: datetime
    mode: str
    lock_seconds: int
    poll_ms: int

    @property
    def label_token(self) -> str:
        return f"{self.label}_{self.hash_suffix}"


def sanitize_name(value: str, *, fallback: str = "unknown", max_length: int = DEFAULT_SANITIZE_MAX) -> str:
    cleaned = value.strip().lower().replace(" ", "-")
    cleaned = re.sub(r"[^a-z0-9-]", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length] if max_length > 0 else cleaned


def short_title_hash(value: str, length: int = 8) -> str:
    digest = hashlib.md5(value.encode("utf-8", errors="ignore")).hexdigest()
    return digest[:length]


def format_target_message(target: TargetInfo | None) -> str:
    if not target:
        return "target missing"
    return (
        f"pid={target.pid} hwnd={target.hwnd} "
        f"exe={target.exe_path} title={target.window_title}"
    )


def detect_foreground_target() -> Optional[TargetInfo]:
    if sys.platform != "win32":
        return None

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None

    title = _get_window_text(user32, hwnd)
    exe_path = _get_process_path(kernel32, pid.value)
    if not exe_path:
        exe_path = ""
    process_name = os.path.basename(exe_path) if exe_path else ""

    return TargetInfo(
        hwnd=int(hwnd),
        pid=int(pid.value),
        exe_path=exe_path,
        process_name=process_name,
        window_title=title,
    )


def lock_target(
    *,
    mode: str,
    lock_seconds: int,
    poll_ms: int,
    ignore_processes: Iterable[str],
    explicit_exe: str | None = None,
    explicit_exe_path: str | None = None,
    logger: Callable[[str, str | None], None] | None = None,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> Optional[LockedTarget]:
    mode_value = (mode or "foreground-at-start").strip().lower()
    normalized_mode = MODE_ALIASES.get(mode_value, mode_value)
    if normalized_mode not in {"foreground-at-start", "first-non-terminal", "exe"}:
        normalized_mode = "foreground-at-start"
    clock = clock or time.monotonic
    sleeper = sleeper or time.sleep
    lock_seconds = max(1, lock_seconds)
    poll_seconds = max(MIN_POLL_SECONDS, poll_ms / 1000.0)

    initial = detect_foreground_target()
    _log_target_event(logger, "target_detected", initial)
    if normalized_mode == "foreground-at-start":
        return _finalize_lock(initial, normalized_mode, lock_seconds, poll_ms, logger)

    ignore_set = _build_ignore_set(ignore_processes)
    explicit_exe_norm = (explicit_exe or "").strip().lower()
    explicit_path_norm = _normalize_path(explicit_exe_path)
    stable_candidate: TargetInfo | None = None
    stable_since: float | None = None
    fallback_candidate: TargetInfo | None = initial
    absolute_deadline = clock() + max(lock_seconds * 3, lock_seconds + 5)

    while clock() < absolute_deadline:
        candidate = detect_foreground_target()
        now = clock()
        if not candidate:
            stable_candidate = None
            stable_since = None
            if sleeper:
                sleeper(poll_seconds)
            continue

        is_explicit_match = _matches_explicit(candidate, explicit_exe_norm, explicit_path_norm)
        if normalized_mode == "exe" and not is_explicit_match:
            stable_candidate = None
            stable_since = None
            fallback_candidate = fallback_candidate or candidate
            if sleeper:
                sleeper(poll_seconds)
            continue

        if normalized_mode == "first-non-terminal" and not _passes_filters(candidate, ignore_set):
            stable_candidate = None
            stable_since = None
            if sleeper:
                sleeper(poll_seconds)
            continue

        if candidate:
            if normalized_mode != "exe" and not _passes_filters(candidate, ignore_set):
                if sleeper:
                    sleeper(poll_seconds)
                continue
            fallback_candidate = candidate

        if stable_candidate is None or _target_changed(stable_candidate, candidate):
            stable_candidate = candidate
            stable_since = now
            _log_target_event(logger, "target_candidate", candidate)
        elif stable_since is not None and (now - stable_since) >= lock_seconds:
            return _finalize_lock(candidate, normalized_mode, lock_seconds, poll_ms, logger)

        if sleeper:
            sleeper(poll_seconds)

    _log_target_event(logger, "target_lock_fallback", fallback_candidate)
    return _finalize_lock(fallback_candidate, normalized_mode, lock_seconds, poll_ms, logger)


def _finalize_lock(
    target: TargetInfo | None,
    mode: str,
    lock_seconds: int,
    poll_ms: int,
    logger: Callable[[str, str | None], None] | None,
) -> Optional[LockedTarget]:
    if not target:
        return None
    label, hash_suffix = _build_target_label(target)
    locked = LockedTarget(
        info=target,
        label=label,
        hash_suffix=hash_suffix,
        locked_at=datetime.now(timezone.utc),
        mode=mode,
        lock_seconds=lock_seconds,
        poll_ms=poll_ms,
    )
    _log_target_event(logger, "target_locked", target)
    return locked


def _build_target_label(target: TargetInfo) -> tuple[str, str]:
    base = target.process_name or os.path.basename(target.exe_path) or "target"
    sanitized = sanitize_name(base, fallback="target")
    hash_source = target.exe_path or target.process_name or target.window_title
    hash_suffix = short_title_hash(hash_source or sanitized, length=8)
    return sanitized or "target", hash_suffix


def _log_target_event(
    logger: Callable[[str, str | None], None] | None,
    event: str,
    target: TargetInfo | None,
) -> None:
    if logger:
        logger(event, format_target_message(target))


def _passes_filters(target: TargetInfo, ignore_set: set[str]) -> bool:
    exe = (target.process_name or "").lower()
    title = (target.window_title or "").strip().lower()
    if exe in ignore_set:
        return False
    if exe == "explorer.exe" and any(token in title for token in WINDOW_TITLE_BLOCKLIST):
        return False
    if exe in SELF_EXE_NAMES:
        return False
    return True


def _matches_explicit(
    target: TargetInfo,
    exe_name: str,
    exe_path: str | None,
) -> bool:
    exe = (target.process_name or "").lower()
    if exe_name and exe == exe_name:
        return True
    path = _normalize_path(target.exe_path)
    return bool(exe_path and path and path == exe_path)


def _build_ignore_set(values: Iterable[str]) -> set[str]:
    normalized = {value.strip().lower() for value in values if value}
    normalized.update(SELF_EXE_NAMES)
    return normalized


def _normalize_path(value: str | None) -> str | None:
    if not value:
        return None
    return os.path.normcase(os.path.abspath(value.strip()))


def _target_changed(previous: TargetInfo | None, current: TargetInfo | None) -> bool:
    if previous is None and current is None:
        return False
    if previous is None or current is None:
        return True
    return (
        previous.hwnd != current.hwnd
        or previous.pid != current.pid
        or (previous.exe_path or "").lower() != (current.exe_path or "").lower()
    )


def _get_window_text(user32, hwnd) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.strip()


def _get_process_path(kernel32, pid: int) -> str:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buffer_len = ctypes.c_ulong(4096)
        buffer = ctypes.create_unicode_buffer(buffer_len.value)
        if kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(buffer_len)
        ):
            return buffer.value.strip()
        return ""
    finally:
        kernel32.CloseHandle(handle)
