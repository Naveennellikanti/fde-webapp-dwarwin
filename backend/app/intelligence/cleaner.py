"""Propose data-cleaning fixes, deterministically, from the quality profile.

Cleaning is where it is tempting to reach for the model, and mostly wrong to. Whether a
column of "1,200"/"3,400" should be cast to a number is not a judgement call — it is a
rule, and a rule is reproducible where a model is not. So the mechanical fixes here are
derived directly from the quality report, not generated: the same messy file always
yields the same proposals, and every proposal is a plain SQL transform the user can read
before approving.

(The model's place in cleaning is *semantic* normalisation a rule cannot know — folding
"USA"/"U.S.A."/"United States" together — proposed for a human to approve. That is a
documented extension, deliberately not mixed into the mechanical path below, so a
hallucinated transform can never ride in with the safe ones.)

Nothing here mutates data. `propose` reads; applying is the caller's job, against a
snapshot, through the same guardrail as any query.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.ingestion.engine import DataEngine
from app.validation.data_quality import TableQuality

OpKind = Literal["cast_numeric", "dedupe_rows", "drop_empty_column", "trim_text"]


@dataclass
class CleaningOp:
    id: str                     # stable, e.g. "cast_numeric:amount_text"
    kind: OpKind
    table: str
    column: str | None
    description: str            # what it does, in plain language
    impact: str = ""            # what it would change, measured (filled by preview)


def propose(engine: DataEngine, table: str, quality: TableQuality) -> list[CleaningOp]:
    """Cleaning operations implied by the quality report for one table.

    Each maps to a specific detected issue, so a clean table yields an empty list.
    """
    ops: list[CleaningOp] = []
    for issue in quality.issues:
        col = issue.column
        if issue.kind == "numeric_stored_as_text" and col:
            ops.append(CleaningOp(
                id=f"cast_numeric:{col}", kind="cast_numeric", table=table, column=col,
                description=f'Convert "{col}" from text to a number so it can be summed and averaged.',
            ))
        elif issue.kind == "duplicate_rows":
            ops.append(CleaningOp(
                id="dedupe_rows", kind="dedupe_rows", table=table, column=None,
                description="Remove fully duplicated rows so totals and counts are not inflated.",
            ))
        elif issue.kind == "all_null" and col:
            ops.append(CleaningOp(
                id=f"drop_empty_column:{col}", kind="drop_empty_column", table=table, column=col,
                description=f'Drop "{col}", which is entirely empty and adds nothing.',
            ))

    # De-duplicate by id (a column can trigger more than one detector).
    seen: set[str] = set()
    unique = [o for o in ops if not (o.id in seen or seen.add(o.id))]
    return unique


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _cast_expr(col: str) -> str:
    """Strip thousands separators and currency, then cast; unparseable values become NULL."""
    q = _q(col)
    return f"TRY_CAST(REPLACE(REPLACE(REPLACE({q}, ',', ''), '$', ''), '%', '') AS DOUBLE) AS {q}"


def build_transform_sql(engine: DataEngine, table: str, ops: list[CleaningOp]) -> str:
    """Compose the selected operations into a single SELECT over the table.

    One statement so the whole clean is atomic and can be validated by the guardrail
    exactly like any query. Column order is preserved; dropped columns are omitted;
    dedupe wraps the projection in DISTINCT.
    """
    columns = engine.tables[table].columns
    drop = {o.column for o in ops if o.kind == "drop_empty_column"}
    casts = {o.column for o in ops if o.kind == "cast_numeric"}
    trims = {o.column for o in ops if o.kind == "trim_text"}
    distinct = any(o.kind == "dedupe_rows" for o in ops)

    items: list[str] = []
    for name, _dtype in columns:
        if name in drop:
            continue
        if name in casts:
            items.append(_cast_expr(name))
        elif name in trims:
            items.append(f"TRIM({_q(name)}) AS {_q(name)}")
        else:
            items.append(_q(name))

    if not items:
        # Every column dropped is not a clean, it is a delete — refuse to build it.
        raise ValueError("Refusing to drop every column.")

    select = "SELECT " + ("DISTINCT " if distinct else "") + ", ".join(items)
    return f'{select} FROM "{table}"'


def measure_impact(engine: DataEngine, table: str, op: CleaningOp) -> str:
    """A concrete before/after for one op, so approval is informed rather than blind.

    Read-only: runs a counting query, changes nothing.
    """
    con = engine.con
    try:
        if op.kind == "dedupe_rows":
            total = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            distinct = con.execute(
                f'SELECT COUNT(*) FROM (SELECT DISTINCT * FROM "{table}")'
            ).fetchone()[0]
            removed = int(total) - int(distinct)
            return f"{removed:,} duplicate row(s) removed, leaving {int(distinct):,}."
        if op.kind == "cast_numeric" and op.column:
            q = _q(op.column)
            row = con.execute(
                f"""SELECT COUNT({q}),
                           COUNT(TRY_CAST(REPLACE(REPLACE(REPLACE({q}, ',', ''), '$', ''), '%', '')
                                          AS DOUBLE))
                    FROM "{table}\""""
            ).fetchone()
            non_null, numeric = int(row[0] or 0), int(row[1] or 0)
            lost = non_null - numeric
            base = f"{numeric:,} value(s) become numeric"
            return base + (f"; {lost:,} non-numeric value(s) become NULL." if lost else ".")
        if op.kind == "drop_empty_column":
            return "Column removed from the table."
        if op.kind == "trim_text" and op.column:
            return "Leading/trailing whitespace removed."
    except Exception:  # noqa: BLE001 - impact is advisory; never block approval on it
        return ""
    return ""


def with_impacts(engine: DataEngine, table: str, ops: list[CleaningOp]) -> list[CleaningOp]:
    for op in ops:
        op.impact = measure_impact(engine, table, op)
    return ops
