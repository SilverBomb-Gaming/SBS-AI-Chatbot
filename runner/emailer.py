"""SMTP helper for delivering human run summaries."""
from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Mapping, Optional


@dataclass
class EmailConfig:
    enabled: bool
    to_address: str
    host: str
    port: int
    username: str
    password: str
    use_tls: bool
    from_address: str


@dataclass
class EmailResult:
    attempted: bool
    success: bool
    message: str


def load_email_config(env: Mapping[str, str]) -> Optional[EmailConfig]:
    enabled = _as_bool(env.get("EMAIL_ENABLED", "0"))
    if not enabled:
        return None
    to_address = (env.get("EMAIL_TO") or "").strip()
    host = (env.get("SMTP_HOST") or "").strip()
    port_raw = (env.get("SMTP_PORT") or "").strip()
    username = (env.get("SMTP_USER") or "").strip()
    password = env.get("SMTP_PASS")
    if not all([to_address, host, port_raw, username, password]):
        return None
    from_address = (env.get("EMAIL_FROM") or username).strip()
    try:
        port = int(port_raw)
    except ValueError:
        return None
    use_tls = _as_bool(env.get("SMTP_TLS", "1"))
    return EmailConfig(
        enabled=True,
        to_address=to_address,
        host=host,
        port=port,
        username=username,
        password=password or "",
        use_tls=use_tls,
        from_address=from_address,
    )


def send_email(
    config: EmailConfig,
    *,
    subject: str,
    body: str,
    attachment: Path | None = None,
) -> EmailResult:
    if not config.enabled:
        return EmailResult(attempted=False, success=False, message="Email disabled")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = config.to_address
    message.set_content(body)
    if attachment and attachment.exists():
        attachment_data = attachment.read_text(encoding="utf-8")
        message.add_attachment(
            attachment_data,
            subtype="markdown",
            maintype="text",
            filename=attachment.name,
        )
    try:
        with smtplib.SMTP(config.host, config.port, timeout=20) as client:
            if config.use_tls:
                client.starttls()
            if config.username:
                client.login(config.username, config.password)
            client.send_message(message)
        return EmailResult(attempted=True, success=True, message="Email sent")
    except Exception as exc:  # pragma: no cover - defensive
        return EmailResult(attempted=True, success=False, message=str(exc))


def _as_bool(raw_value: str | None) -> bool:
    if not raw_value:
        return False
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
