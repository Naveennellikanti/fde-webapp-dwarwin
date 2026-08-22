"""Pluggable SQL-generation strategies.

The pipeline depends on this narrow interface, not on any particular framework. Two
implementations ship:

* ``NativeSqlGenerator``    — direct provider call. Default. Fewest moving parts.
* ``LangChainSqlGenerator`` — the same step expressed as an LCEL chain
  (ChatPromptTemplate | ChatModel | StrOutputParser) over a custom LangChain chat model
  that wraps our own providers.

Both return a plain ``Completion``, so the guardrails, the self-correction retry loop and
DuckDB execution are identical either way — the framework only owns prompt assembly and
output parsing, never correctness or cost control.

Select with ``SQL_GENERATOR=native|langchain``.
"""
from __future__ import annotations

from typing import Protocol

from app.llm.base import Completion, LLMProvider


class SqlGenerator(Protocol):
    """What the pipeline needs from a SQL generation strategy."""
    name: str

    async def complete(
        self, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion: ...


class NativeSqlGenerator:
    """Straight provider call — no framework in the path."""
    name = "native"

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def complete(
        self, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion:
        return await self.provider.complete(system, messages, max_tokens)


def build_sql_generator(kind: str, provider: LLMProvider) -> SqlGenerator:
    if kind == "langchain":
        # Imported lazily so LangChain stays an optional dependency.
        from app.llm.langchain_generator import LangChainSqlGenerator

        return LangChainSqlGenerator(provider)
    return NativeSqlGenerator(provider)
