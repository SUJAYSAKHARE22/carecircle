"""Domain errors. The MCP layer maps these to structured, voice-friendly results."""

from __future__ import annotations


class CareCircleError(Exception):
    """Base class for all expected domain errors."""


class NotFound(CareCircleError):
    """A person, reminder, message or alert could not be found."""


class ValidationError(CareCircleError):
    """Caller supplied invalid input."""


class Ambiguous(CareCircleError):
    """More than one candidate matched; the caller should ask a follow-up question."""

    def __init__(self, message: str, options: list[str]) -> None:
        super().__init__(message)
        self.options = options
