"""Decide what kind of question this is: a lookup, an investigation, or a refusal.

Routing used to be a keyword list — "what needs attention", "any anomalies", and so on.
That works for the phrasings someone thought of and silently fails for the ones they
did not: a differently-worded open question fell through to the single-query path and
got refused, so the app only "worked for anything" if the anything matched a regex.

Intent is a language-understanding problem, so the model decides it. One cheap call
classifies the question against the actual schema, which also means it can tell "show me
errors by service" (a lookup this data supports) from "what should I worry about" (an
investigation) without either being enumerated anywhere.

The lexical matcher is kept, demoted to two supporting roles: an instant fast-path for
the obvious cases so a plain lookup does not pay for a classification call, and an
offline fallback when no model is reachable. It is a shortcut now, not the decider.
"""
from __future__ import annotations

import re
from typing import Literal

from app.config import Settings
from app.intelligence.llm.base import LLMProvider, LLMUnavailableError

Intent = Literal["lookup", "investigate"]

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)

# Fast-path only. A hit means "almost certainly investigative, skip the model call";
# a miss means "ask the model", NOT "it's a lookup" — that is the bug we are fixing.
_OBVIOUSLY_INVESTIGATIVE = re.compile(
    r"""\b(
        what\s+(?:needs?|should)\b
      | anything\s+(?:unusual|wrong|odd|concerning|interesting)
      | red\s+flags?
      | what(?:'s| is)\s+wrong
      | give\s+me\s+(?:an?\s+)?overview
      | health\s+check
    )\b""",
    re.X | re.I,
)
# Fast-path for the other direction: a question that opens with an aggregate verb and
# names no interpretation is a lookup, no call needed.
_OBVIOUSLY_LOOKUP = re.compile(
    r"""^\s*(
        how\s+many | count | what\s+is\s+the\s+(?:total|average|sum|max|min|number)
      | show\s+(?:me\s+)?(?:the\s+)?(?:total|average|count|top|bottom|revenue|number)
      | list\s+the
    )\b""",
    re.X | re.I,
)

CLASSIFY_SYSTEM = """You classify a data question into exactly one category.

lookup      — answerable by a single SQL query: a total, average, count, filter,
              a breakdown by one dimension, a ranking, a trend over time.
investigate — open-ended, needing several queries read together: "what needs my
              attention", "anything unusual", "give me an overview", "what's wrong",
              "summarise this data". It asks for judgement, not a specific figure.

You are given the schema and the question. Reply with ONE word, lowercase: lookup or
investigate. Nothing else."""


def _lexical(question: str) -> Intent | None:
    """A confident lexical guess, or None when the wording is not decisive."""
    if _OBVIOUSLY_INVESTIGATIVE.search(question):
        return "investigate"
    if _OBVIOUSLY_LOOKUP.search(question):
        return "lookup"
    return None


async def classify(
    question: str,
    schema_text: str,
    provider: LLMProvider,
    settings: Settings,
) -> tuple[Intent, str]:
    """Return (intent, how_it_was_decided).

    Order: obvious lexical fast-path, then the model, then lexical fallback if the model
    is unreachable. Defaults to "lookup" only as a last resort, because a wrong lookup
    still produces a checkable answer whereas a wrong investigation spends five queries.
    """
    if not settings.llm_intent_routing:
        return (_lexical(question) or "lookup"), "lexical (routing disabled)"

    fast = _lexical(question)
    if fast is not None:
        return fast, "lexical fast-path"

    prompt = f"SCHEMA:\n{schema_text}\n\nQUESTION: {question}\n\nCATEGORY:"
    try:
        # Reasoning models (gpt-oss, Qwen3) spend output on an internal <think> pass
        # first, so the cap must cover the reasoning plus the one word — too tight and it
        # returns an empty string and every question falls back to the lexical guess.
        # See Settings.intent_max_tokens for the measured floor.
        completion = await provider.complete(
            CLASSIFY_SYSTEM, [{"role": "user", "content": prompt}],
            max_tokens=settings.intent_max_tokens,
        )
    except LLMUnavailableError:
        return (_lexical(question) or "lookup"), "lexical (model unavailable)"

    answer = _THINK.sub("", completion.text).strip().lower()
    # Read the decision from the last word, so a trailing "investigate" wins over a
    # "lookup" that appeared inside the reasoning.
    if "investigate" in answer and answer.rfind("investigate") >= answer.rfind("lookup"):
        return "investigate", "model"
    if "lookup" in answer:
        return "lookup", "model"
    if "investigate" in answer:
        return "investigate", "model"
    # An unreadable classification is not worth a second call; trust the wording.
    return (_lexical(question) or "lookup"), "lexical (unclear model reply)"
