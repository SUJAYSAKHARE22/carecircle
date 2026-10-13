"""Environment-driven settings with validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path

from .timeutil import get_zone, parse_hhmm


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/carecircle.db"
    timezone: str = "Asia/Kolkata"
    checkin_deadline: time = time(10, 0)
    grace_minutes: int = 60
    reminder_grace_minutes: int = 45
    alert_dedupe_minutes: int = 30
    host: str = "127.0.0.1"
    port: int = 8000
    mcp_token: str | None = None
    telegram_bot_token: str | None = None
    allowed_hosts: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        tz = env.get("CARECIRCLE_TIMEZONE", cls.timezone)
        get_zone(tz)  # validate early
        deadline = parse_hhmm(env.get("CARECIRCLE_CHECKIN_DEADLINE", "10:00"))
        db_path = env.get("CARECIRCLE_DB", cls.db_path)
        if db_path != ":memory:":
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        return cls(
            db_path=db_path,
            timezone=tz,
            checkin_deadline=deadline,
            grace_minutes=_int("CARECIRCLE_GRACE_MINUTES", 60),
            reminder_grace_minutes=_int("CARECIRCLE_REMINDER_GRACE_MINUTES", 45),
            alert_dedupe_minutes=_int("CARECIRCLE_ALERT_DEDUPE_MINUTES", 30),
            host=env.get("CARECIRCLE_HOST", "127.0.0.1"),
            port=_int("CARECIRCLE_PORT", 8000, minimum=1),
            mcp_token=(env.get("CARECIRCLE_MCP_TOKEN") or None),
            telegram_bot_token=(env.get("CARECIRCLE_TELEGRAM_BOT_TOKEN") or None),
            allowed_hosts=tuple(
                h.strip() for h in env.get("CARECIRCLE_ALLOWED_HOSTS", "").split(",") if h.strip()
            ),
        )
