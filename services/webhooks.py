"""Webhook dispatcher (stub)."""
from __future__ import annotations

from typing import Dict

import urllib.request


def send_webhook(url: str, payload: Dict[str, object]) -> None:
    if not url:
        return
    data = str(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:  # pragma: no cover - we do not hit real webhooks in tests
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass
