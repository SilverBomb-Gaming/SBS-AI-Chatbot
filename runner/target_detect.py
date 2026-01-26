"""Windows foreground target detection helpers."""
from __future__ import annotations

import ctypes
import hashlib
import os
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TargetInfo:
    hwnd: int
    pid: int
    exe_path: str
    process_name: str
    window_title: str


def sanitize_name(value: str, *, fallback: str = "unknown") -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    cleaned = cleaned.strip("-")
    return cleaned or fallback


def short_title_hash(title: str, length: int = 8) -> str:
    digest = hashlib.md5(title.encode("utf-8", errors="ignore")).hexdigest()
    return digest[:length]


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
