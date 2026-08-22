"""Check that the prose summary only quotes numbers that are actually in the result.

The app's central claim is that the model never produces a number — DuckDB computes and
the model explains. That holds for arithmetic, but explaining still means *transcribing*,
and transcription is where a small model slips: asked to summarise a result containing
177,199.00 it wrote "$1,771,990", off by a factor of ten, on every row. The table and
chart beneath it were correct, because those come straight from the engine. Only the
sentence a user reads first was wrong.

So every figure in the summary is matched back to a value the query actually returned.
An unmatched figure means the model invented or garbled it, and the summary is replaced
with a deterministic one built from the rows — dull, but true.

Matching is deliberately generous about *form* and strict about *value*: thousands
separators, currency symbols, "1.2M", percentages and rounding are all fine, because the
model is expected to reformat. A different quantity is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Numbers as they appear in prose: 1,771,990 · $177199.00 · 1.2M · 45% · -3.5
_NUMBER = re.compile(
    r"""
    (?P<sign>[-−])?
    \$?\s?
    (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?   # 1,771,990.00
        | \d+(?:\.\d+)?                    # 177199.00
    )
    \s?(?P<suffix>[kKmMbB]|bn|tn)?\b
    """,
    re.X,
)
_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9, "bn": 1e9, "tn": 1e12}

# Figures too small or too round to be worth policing: "the top 5", "3 regions",
# "2024". Chasing these produces false alarms on ordinary English.
_IGNORE_BELOW = 1000.0
_YEAR_RANGE = range(1900, 2200)


@dataclass
class SummaryCheck:
    ok: bool
    # Figures in the prose that match nothing in the result.
    unmatched: list[str]

    @property
    def reason(self) -> str:
        if self.ok:
            return ""
        shown = ", ".join(self.unmatched[:3])
        return (
            f"The written summary quoted {shown}, which does not appear in the query "
            f"result. It has been replaced with a summary generated directly from the "
            f"returned rows."
        )


def _numeric_values(rows: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for row in rows:
        for v in row.values():
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                out.append(float(v))
            elif isinstance(v, str):
                # Numbers can arrive as text (DECIMAL, or a numeric-as-text column).
                try:
                    out.append(float(v.replace(",", "").replace("$", "").strip()))
                except ValueError:
                    continue
    return out


def _plausible(value: float, candidates: list[float]) -> bool:
    """Is `value` a reasonable rendering of some returned number?

    Allows for rounding and for derived figures the model may legitimately state: a
    difference, a total, or a percentage of two returned values.
    """
    if not candidates:
        return False

    for c in candidates:
        # Direct match, generous enough for rounding to whole units or 2dp.
        tolerance = max(abs(c) * 0.01, 1.0)
        if abs(value - c) <= tolerance:
            return True
        # The model often rounds hard: "$177k" for 177,199.
        if abs(c) >= 1000 and abs(value - round(c, -3)) <= 1.0:
            return True

    # Sums and differences of returned values are fair game — "East and West together",
    # "short of target by".
    total = sum(candidates)
    if abs(value - total) <= max(abs(total) * 0.01, 1.0):
        return True
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            for derived in (a + b, abs(a - b)):
                if abs(value - derived) <= max(abs(derived) * 0.01, 1.0):
                    return True
    return False


def check_summary(summary: str, rows: list[dict[str, Any]]) -> SummaryCheck:
    """Verify the prose against the rows it claims to describe."""
    if not summary or not rows:
        return SummaryCheck(True, [])

    candidates = _numeric_values(rows)
    unmatched: list[str] = []

    for m in _NUMBER.finditer(summary):
        raw = m.group("num")
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        suffix = (m.group("suffix") or "").lower()
        if suffix:
            value *= _SUFFIX.get(suffix, 1.0)

        # Percentages are usually derived ratios, not quoted values.
        after = summary[m.end():m.end() + 1]
        if after == "%":
            continue
        if value < _IGNORE_BELOW:
            continue
        if int(value) in _YEAR_RANGE and value == int(value):
            continue

        if not _plausible(value, candidates):
            unmatched.append(m.group(0).strip())

    return SummaryCheck(not unmatched, unmatched)


def deterministic_summary(columns: list[str], rows: list[dict[str, Any]], limit: int = 5) -> str:
    """A summary built from the rows, with no model involved.

    Used when the model's prose failed verification. It reads as a plain rendering of
    the result rather than an explanation, which is the right trade: a duller sentence
    that is certainly true beats a fluent one that is not.
    """
    if not rows:
        return "The query returned no rows."

    # A single value: state it.
    if len(rows) == 1 and len(rows[0]) == 1:
        key, value = next(iter(rows[0].items()))
        return f"{_label(key)}: {_render(value)}."

    label_col = next(
        (c for c in columns if not isinstance(rows[0].get(c), (int, float))
         or isinstance(rows[0].get(c), bool)),
        None,
    )
    value_cols = [
        c for c in columns
        if c != label_col
        and isinstance(rows[0].get(c), (int, float))
        and not isinstance(rows[0].get(c), bool)
    ]

    if label_col and value_cols:
        primary = value_cols[0]
        parts = [
            f"{rows[i][label_col]} {_render(rows[i][primary])}"
            for i in range(min(len(rows), limit))
        ]
        more = f", and {len(rows) - limit} more" if len(rows) > limit else ""
        return f"{_label(primary)} by {_label(label_col)}: " + "; ".join(parts) + more + "."

    return (
        f"Returned {len(rows)} row{'s' if len(rows) != 1 else ''} "
        f"across {len(columns)} column{'s' if len(columns) != 1 else ''}; see the table below."
    )


def _label(column: str) -> str:
    return column.replace("_", " ").strip().capitalize()


def _render(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}" if value != int(value) else f"{int(value):,}"
    return str(value)
