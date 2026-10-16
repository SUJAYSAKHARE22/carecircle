"""Optional LLM integration over any OpenAI-compatible endpoint.

Works with free tiers (Groq, Gemini's OpenAI-compatible endpoint, OpenRouter) and local
servers (Ollama, LM Studio). Nothing here is required: the rule-based paths always work.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .config import Settings
from .models import Severity
from .safety import Assessment, Match

log = logging.getLogger("carecircle.llm")

_TRIAGE_PROMPT = (
    "You triage short messages from an elderly person to their family check-in assistant. "
    'Reply with JSON only: {"severity": "info" | "attention" | "urgent", "category": "<one word>"}. '
    "urgent = possible emergency (fall, chest pain, cannot breathe, stroke signs, collapse, severe "
    "bleeding, talk of self-harm, asking for help). attention = discomfort a family member should "
    "know about (dizziness, pain, not eating, confusion, loneliness, poor sleep). info = everything "
    "else. Respect negation: 'no pain' is info. Messages may be English, Hindi or Marathi."
)
_JSON = re.compile(r"\{.*?\}", re.DOTALL)


class LLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 6.0,
        http: httpx.Client | None = None,
    ) -> None:
        logging.getLogger("httpx").setLevel(logging.WARNING)  # keep URLs/keys out of logs
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = http or httpx.Client(timeout=timeout)

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMClient | None":
        if not settings.llm_configured:
            return None
        return cls(
            settings.llm_base_url or "", settings.llm_model or "", settings.llm_api_key,
            settings.llm_timeout,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self._model, "messages": messages, "temperature": temperature}
        if tools:
            payload["tools"] = tools
        response = self._http.post(self._url, json=payload, headers=self._headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]


class LLMSecondOpinion:
    """Catches phrasing the rules miss. Its verdict can only raise severity."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def assess(self, text: str) -> Assessment:
        message = self._client.chat(
            [{"role": "system", "content": _TRIAGE_PROMPT}, {"role": "user", "content": text[:600]}]
        )
        return self.parse(message.get("content") or "", text)

    @staticmethod
    def parse(content: str, source_text: str = "") -> Assessment:
        found = _JSON.search(content)
        if not found:
            return Assessment()
        try:
            data = json.loads(found.group(0))
            severity = Severity[str(data.get("severity", "info")).strip().upper()]
        except (ValueError, KeyError):
            return Assessment()
        if severity is Severity.INFO:
            return Assessment()
        category = str(data.get("category") or "llm").strip().lower()[:24] or "llm"
        return Assessment(severity, (Match(f"llm:{category}", severity, source_text[:60]),))
