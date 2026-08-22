"""Schema description, join auto-detection, and (conditional) schema-RAG.

Key cost property: only this compact schema text ever enters the LLM prompt — never
the data rows. So prompt size is ~constant regardless of how big the files are.

When a session has many tables / very wide tables, `select_relevant` narrows the
schema to the tables & columns lexically relevant to the question (schema-RAG), so
token cost stays bounded at enterprise scale.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings
from app.core.duckdb_engine import DataEngine, LoadedTable
from app.core.pii import mask_rows

_WORD = re.compile(r"[a-z0-9]+")

# Columns whose names/dtypes suggest they are natural join keys.
_NUMERIC_TYPES = {"BIGINT", "INTEGER", "HUGEINT", "SMALLINT", "TINYINT", "DOUBLE", "FLOAT", "DECIMAL"}


@dataclass
class Join:
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


# ---- join detection -------------------------------------------------------------
def detect_joins(engine: DataEngine, max_hints: int = 12) -> list[Join]:
    """Find candidate join keys across tables by column-name + dtype match,
    boosted by value overlap on a sample. Purely heuristic, surfaced as *hints*."""
    tables = list(engine.tables.values())
    joins: list[Join] = []
    seen: set[tuple[str, str, str, str]] = set()

    def base_type(t: str) -> str:
        return t.split("(")[0].upper()

    for i in range(len(tables)):
        for j in range(i + 1, len(tables)):
            a, b = tables[i], tables[j]
            a_cols = {c[0].lower(): c for c in a.columns}
            b_cols = {c[0].lower(): c for c in b.columns}
            for name, (acol, atype) in a_cols.items():
                if name not in b_cols:
                    continue
                bcol, btype = b_cols[name]
                if base_type(atype) != base_type(btype):
                    continue
                key = (a.name, acol, b.name, bcol)
                if key in seen:
                    continue
                seen.add(key)
                conf = 0.6
                # Names like *_id / id / key are stronger signals.
                if re.search(r"(^|_)(id|key|code|no|num)$", name) or name in {"id", "key"}:
                    conf += 0.2
                conf += _value_overlap(engine, a.name, acol, b.name, bcol) * 0.2
                joins.append(Join(a.name, acol, b.name, bcol, round(min(conf, 0.99), 2)))

    joins.sort(key=lambda j: j.confidence, reverse=True)
    return joins[:max_hints]


def _value_overlap(engine: DataEngine, ta: str, ca: str, tb: str, cb: str) -> float:
    try:
        q = (
            f'WITH a AS (SELECT DISTINCT "{ca}" v FROM "{ta}" WHERE "{ca}" IS NOT NULL LIMIT 500), '
            f'b AS (SELECT DISTINCT "{cb}" v FROM "{tb}" WHERE "{cb}" IS NOT NULL LIMIT 500) '
            f"SELECT (SELECT COUNT(*) FROM a JOIN b USING (v))::DOUBLE "
            f"/ NULLIF((SELECT COUNT(*) FROM a), 0)"
        )
        val = engine.con.execute(q).fetchone()[0]
        return float(val or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


# ---- schema-RAG: pick relevant tables/columns for large schemas -----------------
def select_relevant(
    engine: DataEngine, question: str, settings: Settings
) -> tuple[list[LoadedTable], dict[str, list[str]] | None]:
    """Return (tables_to_include, per_table_columns_or_None).

    Below the thresholds we return everything (per_table_columns=None). Above them we
    keep only tables/columns whose names lexically overlap the question, always keeping
    detected join keys so cross-file JOINs remain possible.
    """
    tables = list(engine.tables.values())
    q_tokens = _tokens(question)

    total_cols = sum(len(t.columns) for t in tables)
    widest = max((len(t.columns) for t in tables), default=0)
    if len(tables) <= settings.schema_rag_table_threshold and widest <= settings.schema_rag_column_threshold:
        return tables, None  # small enough: send full schema

    # --- narrow tables by name/column overlap ---
    scored: list[tuple[float, LoadedTable]] = []
    for t in tables:
        toks = _tokens(t.name) | {tok for c in t.columns for tok in _tokens(c[0])}
        score = len(q_tokens & toks)
        scored.append((score, t))
    scored.sort(key=lambda s: s[0], reverse=True)
    keep = [t for score, t in scored if score > 0][:5] or [scored[0][1]]

    # --- narrow columns within kept tables (only if very wide) ---
    join_cols = _join_key_columns(engine)
    per_cols: dict[str, list[str]] = {}
    for t in keep:
        if len(t.columns) <= settings.schema_rag_column_threshold:
            per_cols[t.name] = [c[0] for c in t.columns]
            continue
        chosen = []
        for cname, _ in t.columns:
            if _tokens(cname) & q_tokens or (t.name, cname) in join_cols:
                chosen.append(cname)
        # always keep a few so aggregations have something to select
        if len(chosen) < 5:
            chosen += [c[0] for c in t.columns if c[0] not in chosen][: 5 - len(chosen)]
        per_cols[t.name] = chosen
    return keep, per_cols


def _join_key_columns(engine: DataEngine) -> set[tuple[str, str]]:
    cols: set[tuple[str, str]] = set()
    for j in detect_joins(engine):
        cols.add((j.left_table, j.left_column))
        cols.add((j.right_table, j.right_column))
    return cols


# ---- schema text for the prompt -------------------------------------------------
def build_schema_context(
    engine: DataEngine,
    settings: Settings,
    tables: list[LoadedTable],
    per_table_columns: dict[str, list[str]] | None,
    joins: list[Join],
) -> str:
    lines: list[str] = []
    for t in tables:
        allowed = per_table_columns.get(t.name) if per_table_columns else None
        col_defs = [
            f'"{name}" {dtype}'
            for name, dtype in t.columns
            if allowed is None or name in allowed
        ]
        lines.append(f'TABLE "{t.name}"  -- {t.row_count} rows, from {t.source_file}')
        lines.append("  columns: " + ", ".join(col_defs))
        if not settings.schema_only and settings.sample_rows > 0:
            rows = engine.sample_rows(t.name, settings.sample_rows)
            if allowed is not None:
                rows = [{k: r.get(k) for k in allowed} for r in rows]
            rows = mask_rows(rows)
            if rows:
                lines.append(f"  sample_rows: {rows}")
        lines.append("")

    if joins:
        lines.append("LIKELY JOIN KEYS (use when a question spans tables):")
        for j in joins:
            lines.append(
                f'  "{j.left_table}"."{j.left_column}" <-> '
                f'"{j.right_table}"."{j.right_column}"  (conf {j.confidence})'
            )
    return "\n".join(lines).strip()
