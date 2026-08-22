"""Optional LangChain (LCEL) implementation of the SQL-generation step.

Why this exists
---------------
The default pipeline calls the model provider directly — deliberately, so that the
retry loop and token spend stay explicit (see WRITEUP.md). This module shows the same
step expressed idiomatically in LangChain, selectable with ``SQL_GENERATOR=langchain``,
without handing the framework control of correctness or cost:

    ChatPromptTemplate | ProviderChatModel | StrOutputParser

``ProviderChatModel`` is a custom LangChain chat model that delegates to our own
``LLMProvider``, so the *same* open-source models (Ollama / Groq) serve both paths and
the two are directly comparable.

Guardrails, execution and the self-correction loop remain outside the chain on purpose:
a framework-managed agent loop is exactly the unbounded-cost pattern we chose to avoid.
"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.llm.base import Completion, LLMProvider


class ProviderChatModel(BaseChatModel):
    """Adapts our LLMProvider to LangChain's chat-model interface."""

    provider: LLMProvider
    max_tokens: int = 512
    # Tokens reported by the last call — LangChain's callback plumbing is overkill here.
    last_tokens: int = 0
    last_backend: str = ""

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return "provider-chat-model"

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        system = "\n".join(m.content for m in messages if isinstance(m, SystemMessage))
        chat: list[dict[str, str]] = []
        for m in messages:
            if isinstance(m, SystemMessage):
                continue
            role = "assistant" if isinstance(m, AIMessage) else "user"
            chat.append({"role": role, "content": str(m.content)})

        completion = await self.provider.complete(system, chat, self.max_tokens)
        # Stash usage so the caller can report real token counts.
        object.__setattr__(self, "last_tokens", completion.tokens_used)
        object.__setattr__(self, "last_backend", completion.backend)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=completion.text))])

    def _generate(self, *args: Any, **kwargs: Any) -> ChatResult:  # pragma: no cover
        raise NotImplementedError("This app is async-only; use ainvoke().")


class LangChainSqlGenerator:
    """SQL generation as an LCEL chain over our own providers."""

    name = "langchain"

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def complete(
        self, system: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion:
        model = ProviderChatModel(provider=self.provider, max_tokens=max_tokens)

        prompt = ChatPromptTemplate.from_messages(
            [("system", "{system}"), MessagesPlaceholder("history")]
        )
        chain = prompt | model | StrOutputParser()

        history: list[BaseMessage] = [
            AIMessage(content=m["content"]) if m["role"] == "assistant"
            else HumanMessage(content=m["content"])
            for m in messages
        ]

        text = await chain.ainvoke({"system": system, "history": history})
        return Completion(
            text=text,
            tokens_used=model.last_tokens,
            backend=f"{model.last_backend} (via langchain)",
        )
