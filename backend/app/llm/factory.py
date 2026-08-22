"""Chooses the provider at runtime: local-first, hosted fallback.

LLM_BACKEND=auto   -> Ollama if reachable, else Groq (this is the default)
LLM_BACKEND=ollama -> force local
LLM_BACKEND=groq   -> force hosted
"""
from __future__ import annotations

from app.config import Settings
from app.llm.base import LLMProvider, LLMUnavailableError
from app.llm.groq_provider import GroqProvider
from app.llm.ollama_provider import OllamaProvider


def _ollama(s: Settings) -> OllamaProvider:
    # Local inference gets its own, much larger budget — see Settings.ollama_timeout_s.
    return OllamaProvider(s.ollama_url, s.ollama_model, s.temperature, s.ollama_timeout_s)


def _groq(s: Settings) -> GroqProvider:
    return GroqProvider(s.groq_api_key, s.groq_base_url, s.groq_model, s.temperature, s.request_timeout_s)


async def get_provider(settings: Settings) -> LLMProvider:
    if settings.llm_backend == "ollama":
        return _ollama(settings)
    if settings.llm_backend == "groq":
        return _groq(settings)

    # auto: prefer local (private, free), fall back to hosted.
    local = _ollama(settings)
    if await local.available():
        return local
    hosted = _groq(settings)
    if await hosted.available():
        return hosted
    raise LLMUnavailableError(
        "No LLM backend available. Start Ollama locally (`ollama serve` + "
        "`ollama pull qwen2.5-coder:3b`) or set GROQ_API_KEY."
    )
