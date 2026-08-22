"""Pick a chart from the SHAPE of the result set — deterministic, no LLM call.

The backend returns a chart *spec*; the frontend renders it with Recharts. Keeping
this rule-based makes it testable and free.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.schemas import ChartSpec

_DATE_NAME = re.compile(r"(date|day|month|year|quarter|week|time|period|ts)", re.I)
_MAX_CATEGORIES = 50


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _col_kind(name: str, values: list[Any]) -> str:
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "empty"
    if all(isinstance(v, (datetime, date)) for v in non_null):
        return "datetime"
    if _DATE_NAME.search(name) and all(isinstance(v, str) for v in non_null):
        # e.g. strftime output '2024-07'
        if all(re.match(r"^\d{4}(-\d{2}){0,2}", v) for v in non_null):
            return "datetime"
    if _DATE_NAME.search(name) and all(_is_number(v) for v in non_null):
        # year numbers like 2024
        if all(1900 <= float(v) <= 2200 for v in non_null):
            return "datetime"
    if all(_is_number(v) for v in non_null):
        return "numeric"
    return "categorical"


def select_chart(columns: list[str], rows: list[dict[str, Any]], question: str = "") -> ChartSpec:
    if not rows or not columns:
        return ChartSpec(type="none")

    # Single scalar -> KPI card.
    if len(rows) == 1 and len(columns) == 1:
        return ChartSpec(type="kpi", y=columns[0], title=columns[0].replace("_", " ").title())

    kinds = {c: _col_kind(c, [r.get(c) for r in rows]) for c in columns}
    datetimes = [c for c in columns if kinds[c] == "datetime"]
    numerics = [c for c in columns if kinds[c] == "numeric"]
    categoricals = [c for c in columns if kinds[c] == "categorical"]

    # Time series -> line chart.
    if datetimes and numerics and len(rows) > 1:
        series = categoricals[0] if categoricals and _cardinality(rows, categoricals[0]) <= 8 else None
        return ChartSpec(
            type="line", x=datetimes[0], y=numerics[0], series=series,
            title=f"{_pretty(numerics[0])} over {_pretty(datetimes[0])}",
        )

    # One category + one measure -> bar chart.
    if categoricals and numerics and 1 < len(rows) <= _MAX_CATEGORIES:
        cat = min(categoricals, key=lambda c: _cardinality(rows, c))
        series = None
        others = [c for c in categoricals if c != cat]
        if others and _cardinality(rows, others[0]) <= 6:
            series = others[0]
        return ChartSpec(
            type="bar", x=cat, y=numerics[0], series=series,
            title=f"{_pretty(numerics[0])} by {_pretty(cat)}",
        )

    # Two measures, no obvious category -> scatter.
    if len(numerics) >= 2 and not categoricals and len(rows) > 2:
        return ChartSpec(
            type="scatter", x=numerics[0], y=numerics[1],
            title=f"{_pretty(numerics[1])} vs {_pretty(numerics[0])}",
        )

    return ChartSpec(type="table")


def _cardinality(rows: list[dict[str, Any]], col: str) -> int:
    return len({r.get(col) for r in rows})


def _pretty(name: str) -> str:
    return name.replace("_", " ").strip().title()
