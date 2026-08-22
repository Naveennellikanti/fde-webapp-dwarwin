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

    async def status(self) -> tuple[bool, str]:
        """Whether this backend can actually serve a question, and why not if it cannot.

        Checking only that the server answers is not enough: Ollama running without the
        configured model pulled reports perfectly healthy, so the UI would offer "Local"
        as selectable and the failure would surface later, on the user's first question,
        as a 404. The model has to be present for the backend to be usable, so it is
        part of the check — and the reason is returned so the UI can say what to do
        instead of a bare "unavailable".
        """
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.url}/api/tags")
        except Exception:  # noqa: BLE001
            return False, f"Ollama is not running at {self.url}. Start it with: ollama serve"

        if r.status_code != 200:
            return False, f"Ollama answered {r.status_code} at {self.url}."

        try:
            installed = {m.get("name", "") for m in (r.json().get("models") or [])}
        except Exception:  # noqa: BLE001
            return True, ""  # server is up; do not block on an unreadable tag list

        if not installed:
            return False, f"Ollama has no models. Pull one with: ollama pull {self.model}"

        # An untagged name means :latest to Ollama, so compare both forms.
        wanted = {self.model, self.model if ":" in self.model else f"{self.model}:latest"}
        if not (wanted & installed):
            return False, (
                f"Ollama is running but '{self.model}' is not pulled. "
                f"Run: ollama pull {self.model}"
            )
        return True, ""

    async def available(self) -> bool:
        ok, _reason = await self.status()
        return ok

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
