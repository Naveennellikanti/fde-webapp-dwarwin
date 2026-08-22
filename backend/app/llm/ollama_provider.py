"""Local Ollama provider — data never leaves the machine."""
from __future__ import annotations

import httpx

from app.llm.base import Completion, LLMProvider, LLMUnavailableError


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, url: str, model: str, temperature: float, timeout_s: float):
        self.url = url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.url}/api/tags")
                return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def complete(
        self, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "options": {"temperature": self.temperature, "num_predict": max_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(f"{self.url}/api/chat", json=payload)
                r.raise_for_status()
                data = r.json()
        except Exception as e:  # noqa: BLE001
            raise LLMUnavailableError(f"Ollama request failed: {e}") from e

        text = (data.get("message") or {}).get("content", "")
        tokens = int(data.get("prompt_eval_count", 0)) + int(data.get("eval_count", 0))
        return Completion(text=text, tokens_used=tokens, backend=f"ollama:{self.model}")
