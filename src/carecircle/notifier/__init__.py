from __future__ import annotations

from ..config import Settings
from .base import ConsoleNotifier, Notifier, RecordingNotifier, format_alert
from .telegram import BotCommands, TelegramClient, TelegramNotifier, TelegramPoller


def build_notifier(settings: Settings) -> Notifier:
    """Telegram when a bot token is configured, otherwise log-only."""
    if settings.telegram_bot_token:
        return TelegramNotifier(TelegramClient(settings.telegram_bot_token))
    return ConsoleNotifier()


__all__ = [
    "BotCommands", "ConsoleNotifier", "Notifier", "RecordingNotifier", "TelegramClient",
    "TelegramNotifier", "TelegramPoller", "build_notifier", "format_alert",
]
