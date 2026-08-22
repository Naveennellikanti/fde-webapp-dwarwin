"""Data quality profiling, run once per table at upload.

Real spreadsheets are messy in ways that quietly corrupt an answer: a column that is
90% null makes an average meaningless, duplicated rows inflate every total, and a
"revenue" column holding "1,200" and "N/A" as text will not sum at all. None of that is
visible in a schema listing, and none of it announces itself in the answer either — the
number just comes back wrong.

So the checks run at ingest and are surfaced next to the data, and the serious ones are
also passed to the model, because "this column is 40% null" changes how a question about
its average should be answered.

Everything here is a DuckDB aggregate over the loaded table. Nothing is pulled into
Python row by row, so profiling a million rows stays cheap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.ingestion.engine import DataEngine

Severity = Literal["info", "warning"]

# A column this empty cannot support an average or a trend worth trusting.
_HIGH_NULL_PCT = 40.0
_SOME_NULL_PCT = 5.0
# Text columns where almost every value is unique are identifiers, not categories:
# grouping by them produces one row per record rather than a summary.
_ID_LIKE_UNIQUE_RATIO = 0.95
# Below this many rows, "every value is unique" says nothing — a 5-row lookup table is
# all-unique by nature.
_MIN_ROWS_FOR_UNIQUENESS = 20
_NUMERIC_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT",
    "FLOAT", "DOUBLE", "DECIMAL", "REAL",
}
# Temporal columns are near-unique by nature and grouping by them is the *point* — a
# monthly trend is a GROUP BY over a date. Calling them identifiers would be advice
# against the most common analytical question there is.
_TEMPORAL_TYPES = {
    "DATE", "TIME", "TIMESTAMP", "TIMESTAMP_NS", "TIMESTAMP_MS", "TIMESTAMP_S",
    "TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ", "INTERVAL",
}


@dataclass
class QualityIssue:
    kind: str
    severity: Severity
    message: str
    column: str | None = None


@dataclass
class ColumnQuality:
    name: str
    dtype: str
    null_count: int
    null_pct: float
    distinct_count: int


@dataclass
class TableQuality:
    table: str
    row_count: int
    duplicate_rows: int
    columns: list[ColumnQuality] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def warnings(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity == "warning"]


def profile_table(engine: DataEngine, table: str) -> TableQuality:
    """Profile one loaded table. Never raises: a failed check must not block an upload."""
    loaded = engine.tables[table]
    con = engine.con
    row_count = loaded.row_count

    report = TableQuality(table=table, row_count=row_count, duplicate_rows=0)

    if row_count == 0:
        report.issues.append(
            QualityIssue("empty_table", "warning", "This table has no rows.")
        )
        return report

    # ---- one pass for per-column null and distinct counts ----------------------
    # Built as a single SELECT so the table is scanned once rather than 2N times.
    parts: list[str] = []
    for name, _dtype in loaded.columns:
        q = name.replace('"', '""')
        parts.append(f'COUNT("{q}") AS "n_{q}"')
        parts.append(f'COUNT(DISTINCT "{q}") AS "d_{q}"')
    try:
        row = con.execute(f'SELECT {", ".join(parts)} FROM "{table}"').fetchone()
    except Exception:  # noqa: BLE001 - profiling is advisory, never fatal
        return report

    for idx, (name, dtype) in enumerate(loaded.columns):
        non_null = int(row[idx * 2] or 0)
        distinct = int(row[idx * 2 + 1] or 0)
        nulls = row_count - non_null
        null_pct = round(100.0 * nulls / row_count, 1)
        report.columns.append(
            ColumnQuality(
                name=name, dtype=dtype, null_count=nulls,
                null_pct=null_pct, distinct_count=distinct,
            )
        )
        report.issues.extend(
            _column_issues(name, dtype, nulls, null_pct, distinct, non_null, row_count)
        )

    report.duplicate_rows = _duplicate_rows(engine, table)
    if report.duplicate_rows:
        pct = round(100.0 * report.duplicate_rows / row_count, 1)
        report.issues.append(
            QualityIssue(
                "duplicate_rows", "warning",
                f"{report.duplicate_rows:,} fully duplicated row(s) ({pct}%) — these "
                f"inflate every total and count.",
            )
        )

    numeric_text = _numeric_text_issues(engine, table, loaded.columns)
    report.issues.extend(numeric_text)

    # A numbers-stored-as-text column is also near-unique, so it collects an
    # "identifier" note too — two findings about the same column where the specific one
    # already says what to do. Keep the specific one.
    numeric_text_cols = {i.column for i in numeric_text if i.column}
    report.issues = [
        i for i in report.issues
        if not (i.kind == "identifier_like" and i.column in numeric_text_cols)
    ]
    return report


def _column_issues(
    name: str, dtype: str, nulls: int, null_pct: float,
    distinct: int, non_null: int, row_count: int,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []

    if nulls == row_count:
        issues.append(QualityIssue(
            "all_null", "warning", f'"{name}" is entirely empty.', name))
        return issues

    if null_pct >= _HIGH_NULL_PCT:
        issues.append(QualityIssue(
            "high_nulls", "warning",
            f'"{name}" is {null_pct}% empty — averages and trends over it are unreliable.',
            name))
    elif null_pct >= _SOME_NULL_PCT:
        issues.append(QualityIssue(
            "some_nulls", "info", f'"{name}" is {null_pct}% empty.', name))

    if distinct == 1 and non_null == row_count:
        issues.append(QualityIssue(
            "constant", "info",
            f'"{name}" holds a single value throughout — it cannot distinguish rows.',
            name))

    base = dtype.split("(")[0].upper()
    is_categorical_candidate = (
        base not in _NUMERIC_TYPES
        and base not in _TEMPORAL_TYPES
        and base != "BOOLEAN"
    )
    if is_categorical_candidate and non_null >= _MIN_ROWS_FOR_UNIQUENESS:
        if distinct / non_null >= _ID_LIKE_UNIQUE_RATIO:
            issues.append(QualityIssue(
                "identifier_like", "info",
                f'"{name}" is almost entirely unique — it looks like an identifier, '
                f"so grouping by it will not summarise anything.",
                name))
    return issues


def _duplicate_rows(engine: DataEngine, table: str) -> int:
    """Rows that are exact duplicates of another row, counting only the copies."""
    try:
        total = engine.con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        distinct = engine.con.execute(
            f'SELECT COUNT(*) FROM (SELECT DISTINCT * FROM "{table}")'
        ).fetchone()[0]
        return max(0, int(total) - int(distinct))
    except Exception:  # noqa: BLE001 - e.g. a column type with no equality operator
        return 0


def _numeric_text_issues(
    engine: DataEngine, table: str, columns: list[tuple[str, str]]
) -> list[QualityIssue]:
    """Text columns whose values are mostly numbers.

    This is the failure that looks like a bug in the app rather than the data: a
    thousands separator or a stray "N/A" keeps the whole column as VARCHAR, and then
    SUM() over it either errors or silently coerces. Worth saying out loud.
    """
    issues: list[QualityIssue] = []
    for name, dtype in columns:
        if dtype.split("(")[0].upper() in _NUMERIC_TYPES:
            continue
        if dtype.upper() not in {"VARCHAR", "TEXT", "STRING"}:
            continue
        q = name.replace('"', '""')
        try:
            row = engine.con.execute(
                f'''SELECT COUNT("{q}"),
                           COUNT(TRY_CAST(REPLACE(REPLACE("{q}", ',', ''), '$', '') AS DOUBLE))
                    FROM "{table}"'''
            ).fetchone()
        except Exception:  # noqa: BLE001
            continue
        non_null, numeric_like = int(row[0] or 0), int(row[1] or 0)
        if non_null < 10 or numeric_like == 0:
            continue
        ratio = numeric_like / non_null
        if 0.8 <= ratio < 1.0:
            issues.append(QualityIssue(
                "numeric_stored_as_text", "warning",
                f'"{name}" is text but {round(ratio * 100)}% of its values are numbers — '
                f"the rest (blanks, \"N/A\", symbols) keep it from being summed.",
                name))
        elif ratio == 1.0:
            issues.append(QualityIssue(
                "numeric_stored_as_text", "info",
                f'"{name}" holds numbers stored as text; cast it before doing arithmetic.',
                name))
    return issues


def profile_session(engine: DataEngine) -> list[TableQuality]:
    return [profile_table(engine, name) for name in engine.tables]


def quality_notes_for_prompt(reports: list[TableQuality], limit: int = 6) -> str:
    """The subset worth spending prompt tokens on.

    Only warnings, only a handful: a column being 60% null should change how the model
    writes an average over it, but a tidy-data lecture in the system prompt would just
    crowd out the schema.
    """
    lines: list[str] = []
    for r in reports:
        for issue in r.warnings:
            target = f'"{r.table}"."{issue.column}"' if issue.column else f'"{r.table}"'
            lines.append(f"  {target}: {issue.message}")
            if len(lines) >= limit:
                break
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return "DATA QUALITY NOTES (mention a caveat if it affects the answer):\n" + "\n".join(lines)
