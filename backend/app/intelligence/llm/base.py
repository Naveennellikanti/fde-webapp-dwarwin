"""Provider-agnostic LLM interface.

Both providers run *open-source* models (Qwen2.5-Coder locally via Ollama, gpt-oss-120b
via Groq). Model ids are configuration, not assumptions in the code — hosted model
lineups change, so nothing here depends on a specific one. The rest of the app depends only on this interface, so switching between
local and hosted is a config change, not a code change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Completion:
    text: str
    tokens_used: int
    backend: str


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion:
        """Run a chat completion. `messages` is a list of {role, content}."""

    @abstractmethod
    async def available(self) -> bool:
        """Cheap health check used by the 'auto' backend selector."""


class LLMUnavailableError(RuntimeError):
    pass
