"""Sanity checks on a result set before it is presented as an answer.

The guardrail in `analytics/query_validator` asks whether SQL is *safe* to run. This
asks a different question: the query ran, but does the answer look like it means what
the user asked?

Nothing here can prove an answer correct — that would require knowing the intent. What
it can do is catch the shapes that are almost always a misunderstanding rather than a
finding: an aggregate over a column that is mostly empty, a filter that matched nothing,
a "top N" that silently returned one row, a count that came back negative. Each is
reported as a caveat shown beside the answer, never as a reason to hide it — the user
still gets the number and the SQL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.validation.data_quality import TableQuality

Severity = Literal["info", "warning"]


@dataclass
class ResultCaveat:
    kind: str
    severity: Severity
    message: str


@dataclass
class ValidationReport:
    caveats: list[ResultCaveat] = field(default_factory=list)

    @property
    def warnings(self) -> list[ResultCaveat]:
        return [c for c in self.caveats if c.severity == "warning"]

    def add(self, kind: str, severity: Severity, message: str) -> None:
        self.caveats.append(ResultCaveat(kind, severity, message))


_AGG = re.compile(r"\b(AVG|SUM|MIN|MAX|MEDIAN|STDDEV|VARIANCE)\s*\(\s*(?:DISTINCT\s+)?\"?([A-Za-z_][A-Za-z0-9_]*)\"?", re.I)

# Column names are matched by tokenising on non-alphanumerics rather than with word
# boundaries: `\bcount\b` does not match "order_count", because `_` is itself a word
# character, so there is no boundary before "count". That silently skipped the most
# common naming conventions.
_IDENT_SPLIT = re.compile(r"[^a-z0-9]+")
_COUNT_TOKENS = {"count", "counts", "n", "num", "orders", "qty", "quantity", "total"}
_TOP_N = re.compile(r"\b(top|bottom|first|last)\s+(\d+)\b", re.I)
_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\b", re.I)
_HAS_FILTER = re.compile(r"\bWHERE\b", re.I)


def validate_result(
    *,
    question: str,
    sql: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    quality: list[TableQuality] | None = None,
    truncated: bool = False,
) -> ValidationReport:
    report = ValidationReport()
    sql = sql or ""

    # ---- empty result --------------------------------------------------------
    if not rows:
        if _HAS_FILTER.search(sql):
            report.add(
                "empty_filtered", "warning",
                "No rows matched the filters. The value being filtered on may be "
                "spelled differently in the data.",
            )
        else:
            report.add("empty", "warning", "The query returned no rows.")
        return report

    # ---- aggregates over columns that are mostly empty ----------------------
    # An AVG that skips 60% of the rows is not the average the user has in mind.
    if quality:
        null_pct = {
            (t.table, c.name): c.null_pct for t in quality for c in t.columns
        }
        for func, col in _AGG.findall(sql):
            worst = max(
                (pct for (_tbl, name), pct in null_pct.items() if name == col),
                default=0.0,
            )
            if worst >= 40.0:
                report.add(
                    "aggregate_over_sparse_column", "warning",
                    f'{func.upper()}() ignores empty values, and "{col}" is {worst}% '
                    f"empty — this covers only the rows that have a value.",
                )
                break

    # ---- a "top N" that came back short ------------------------------------
    asked = _TOP_N.search(question)
    if asked:
        want = int(asked.group(2))
        if len(rows) < want:
            report.add(
                "fewer_rows_than_requested", "info",
                f"Asked for {want} but the data only yields {len(rows)}.",
            )

    # ---- a single row where a comparison was expected ----------------------
    if len(rows) == 1 and re.search(r"\b(by|per|each|compare|across|breakdown)\b", question, re.I):
        if "GROUP BY" not in sql.upper():
            report.add(
                "no_grouping", "info",
                "This returned one overall figure rather than a breakdown.",
            )

    # ---- impossible values in count-like columns ---------------------------
    for col in columns:
        if not (set(_IDENT_SPLIT.split(col.lower())) & _COUNT_TOKENS):
            continue
        for r in rows[:200]:
            v = r.get(col)
            if isinstance(v, (int, float)) and v < 0:
                report.add(
                    "negative_count", "warning",
                    f'"{col}" contains a negative value, which a count cannot be.',
                )
                break
        else:
            continue
        break

    # ---- truncation ---------------------------------------------------------
    if truncated:
        report.add(
            "truncated", "info",
            "Only the first rows are shown; any figure you compute from the table "
            "below is over that subset, not the whole result.",
        )

    # ---- a LIMIT the user did not ask for ----------------------------------
    limit = _LIMIT.search(sql)
    if limit and not asked and not re.search(r"\b(top|bottom|first|last|sample|few)\b", question, re.I):
        report.add(
            "unrequested_limit", "info",
            f"The query caps the result at {limit.group(1)} rows, which the question "
            f"did not ask for.",
        )

    return report
