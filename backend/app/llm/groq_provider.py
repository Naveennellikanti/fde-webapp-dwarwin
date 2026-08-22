"""Hosted Groq provider (OpenAI-compatible API) running open-source Llama models.

Only the schema + masked samples + question transit to this API — never the raw files.
"""
from __future__ import annotations

import asyncio

import httpx

from app.llm.base import Completion, LLMProvider, LLMUnavailableError

# Hosted free tiers rate-limit aggressively. Retrying with backoff turns a hard failure
# into a short pause, which matters when several questions are asked in quick succession.
_MAX_HTTP_RETRIES = 4
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(
        self, api_key: str | None, base_url: str, model: str, temperature: float, timeout_s: float
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s

    async def available(self) -> bool:
        return bool(self.api_key)

    async def complete(
        self, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion:
        if not self.api_key:
            raise LLMUnavailableError("GROQ_API_KEY is not set.")
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        data = None
        last_error: Exception | None = None
        for attempt in range(_MAX_HTTP_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    r = await client.post(
                        f"{self.base_url}/chat/completions", json=payload, headers=headers
                    )
                if r.status_code in _RETRY_STATUSES and attempt < _MAX_HTTP_RETRIES - 1:
                    await asyncio.sleep(_retry_delay(r, attempt))
                    continue
                r.raise_for_status()
                data = r.json()
                break
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    raise LLMUnavailableError(
                        "The model provider is rate-limiting requests (free tier). "
                        "Wait a few seconds and ask again."
                    ) from e
                if e.response.status_code == 401:
                    raise LLMUnavailableError("Model provider rejected the API key (401).") from e
                raise LLMUnavailableError(f"Groq request failed: {e}") from e
            except Exception as e:  # noqa: BLE001 - network/timeout: retry then give up
                last_error = e
                if attempt < _MAX_HTTP_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise LLMUnavailableError(f"Groq request failed: {e}") from e

        if data is None:
            raise LLMUnavailableError(f"Groq request failed after retries: {last_error}")

        text = data["choices"][0]["message"]["content"]
        tokens = int((data.get("usage") or {}).get("total_tokens", 0))
        return Completion(text=text, tokens_used=tokens, backend=f"groq:{self.model}")


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Honour Retry-After when the provider sends it, else exponential backoff."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(float(header), 20.0)
        except ValueError:
            pass
    return min(2 ** attempt, 8.0)
