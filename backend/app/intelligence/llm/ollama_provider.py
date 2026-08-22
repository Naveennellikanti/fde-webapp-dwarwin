"""Local Ollama provider — data never leaves the machine."""
from __future__ import annotations

import httpx

from app.intelligence.llm.base import Completion, LLMProvider, LLMUnavailableError


def _reason(e: Exception) -> str:
    """A human-readable cause.

    Several httpx exceptions (notably ReadTimeout) stringify to "", which would
    surface in the UI as "Ollama request failed:" with nothing after the colon. Fall
    back to the exception class name so the message always says something.
    """
    text = str(e).strip()
    return text or type(e).__name__


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
                if r.status_code == 404:
                    # Ollama is running but does not have this model pulled.
                    raise LLMUnavailableError(
                        f"Ollama has no model '{self.model}'. Pull it with: "
                        f"ollama pull {self.model}"
                    )
                r.raise_for_status()
                data = r.json()
        except LLMUnavailableError:
            raise
        except httpx.TimeoutException as e:
            raise LLMUnavailableError(
                f"Ollama did not respond within {self.timeout_s:.0f}s "
                f"({_reason(e)}). Local inference on a CPU-only machine is slow — "
                f"try a smaller model (e.g. qwen2.5-coder:3b) or raise "
                f"OLLAMA_TIMEOUT_S."
            ) from e
        except httpx.ConnectError as e:
            raise LLMUnavailableError(
                f"Could not reach Ollama at {self.url} ({_reason(e)}). "
                f"Start it with: ollama serve"
            ) from e
        except Exception as e:  # noqa: BLE001
            raise LLMUnavailableError(f"Ollama request failed: {_reason(e)}") from e

        text = (data.get("message") or {}).get("content", "")
        tokens = int(data.get("prompt_eval_count", 0)) + int(data.get("eval_count", 0))
        return Completion(text=text, tokens_used=tokens, backend=f"ollama:{self.model}")
