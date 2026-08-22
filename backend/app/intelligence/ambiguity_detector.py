"""Detect questions that are underspecified against the loaded schema.

"Show me the best region" has no single correct SQL: best by revenue or by units, over
all time or this quarter, and if two files both have a `region` column, from which one?
The model will answer anyway, because that is what it is for — it picks an
interpretation, silently, and the user has no way to tell that a choice was made.

Two options once ambiguity is found. Blocking to ask a question is the safer-looking
one, but it makes the app feel obstructive and is wrong most of the time — usually one
reading is obviously intended. So the default is to answer and *state the assumption*,
and only ask when there is genuinely nothing to prefer (a superlative with several
equally plausible measures, no hint in the wording).

This runs before the LLM call and costs nothing: it is lexical matching against the
schema that has already been profiled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.ingestion.engine import DataEngine

Action = Literal["assume", "ask"]

# Superlatives need a measure to rank by; "best" does not name one.
_VAGUE_SUPERLATIVE = re.compile(
    r"\b(best|worst|top|bottom|strongest|weakest|leading|biggest|largest|smallest|highest|lowest)\b",
    re.I,
)
# Words that would supply the missing measure.
_MEASURE_HINT = re.compile(
    r"\b(revenue|sales|amount|total|value|units|quantity|count|price|profit|margin|"
    r"cost|score|rating|salary|hours|days|by)\b",
    re.I,
)
_RELATIVE_TIME = re.compile(
    r"\b(recent|recently|lately|current|now|latest|this (?:month|quarter|year|week)|"
    r"last (?:month|quarter|year|week)|ytd|mtd)\b",
    re.I,
)
_MEASURE_WORDS = {
    "revenue", "sales", "amount", "total", "value", "price", "profit", "margin",
    "cost", "units", "quantity", "qty", "count", "score", "rating", "salary",
    "hours", "spend", "budget", "target",
}
_NUMERIC_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT",
    "UINTEGER", "UBIGINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL",
}
_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class Ambiguity:
    kind: str
    action: Action
    # What the user should be told, phrased for display.
    message: str
    # Candidate readings, most plausible first. Used when action == "ask".
    options: list[str] = field(default_factory=list)
    # A line appended to the prompt so the model commits to the stated reading.
    prompt_hint: str = ""


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _numeric_columns(engine: DataEngine) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for table in engine.tables.values():
        for name, dtype in table.columns:
            if dtype.split("(")[0].upper() in _NUMERIC_TYPES:
                out.append((table.name, name))
    return out


def _measure_candidates(engine: DataEngine) -> list[tuple[str, str]]:
    """Numeric columns that read like something you would rank by."""
    ranked: list[tuple[str, str]] = []
    for table, col in _numeric_columns(engine):
        toks = _tokens(col)
        if toks & _MEASURE_WORDS:
            # An identifier is numeric but is not a measure.
            if not re.search(r"(^|_)(id|no|num|code|key|year|month|day)$", col, re.I):
                ranked.append((table, col))
    return ranked


def detect(question: str, engine: DataEngine) -> list[Ambiguity]:
    """Ambiguities worth telling the user about. Empty list is the common case."""
    found: list[Ambiguity] = []
    q_tokens = _tokens(question)

    # ---- superlative with no measure named ----------------------------------
    if _VAGUE_SUPERLATIVE.search(question) and not _MEASURE_HINT.search(question):
        candidates = _measure_candidates(engine)
        names = [c for _t, c in candidates]
        unique = list(dict.fromkeys(names))
        if len(unique) > 1:
            found.append(Ambiguity(
                kind="superlative_without_measure",
                action="ask",
                message=(
                    "\"Best\" could be measured several ways in this data. "
                    f"Which did you mean: {', '.join(unique[:4])}?"
                ),
                options=unique[:4],
            ))
        elif len(unique) == 1:
            found.append(Ambiguity(
                kind="superlative_without_measure",
                action="assume",
                message=f'Ranked by "{unique[0]}", the only measure in this data.',
                prompt_hint=f'Rank by "{unique[0]}" and say so in your answer.',
            ))

    # ---- a column name that exists in more than one table -------------------
    by_column: dict[str, list[str]] = {}
    for table in engine.tables.values():
        for name, _dtype in table.columns:
            by_column.setdefault(name.lower(), []).append(table.name)
    for col, tables in by_column.items():
        if len(tables) > 1 and col in q_tokens:
            found.append(Ambiguity(
                kind="column_in_multiple_tables",
                action="assume",
                message=(
                    f'"{col}" appears in {len(tables)} tables '
                    f"({', '.join(tables[:3])}) — check the SQL for which was used."
                ),
                prompt_hint=(
                    f'"{col}" exists in several tables ({", ".join(tables)}). Pick the one '
                    f"the question is about and qualify it explicitly."
                ),
            ))
            break

    # ---- relative time with no anchor in the data ---------------------------
    if _RELATIVE_TIME.search(question):
        found.append(Ambiguity(
            kind="relative_time",
            action="assume",
            message=(
                "Relative dates are resolved against the newest date in the data, "
                "not today's date."
            ),
            prompt_hint=(
                "Resolve any relative time expression against MAX() of the relevant date "
                "column in the data, never against the current date, and state the window "
                "you used."
            ),
        ))

    return found


def prompt_addendum(ambiguities: list[Ambiguity]) -> str:
    """Hints for the ones being answered under a stated assumption."""
    hints = [a.prompt_hint for a in ambiguities if a.action == "assume" and a.prompt_hint]
    if not hints:
        return ""
    return "RESOLVING AMBIGUITY:\n" + "\n".join(f"  - {h}" for h in hints)


def blocking(ambiguities: list[Ambiguity]) -> Ambiguity | None:
    """The first ambiguity, if any, that should be asked about rather than assumed."""
    for a in ambiguities:
        if a.action == "ask":
            return a
    return None
