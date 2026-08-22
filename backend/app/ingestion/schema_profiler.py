"""Schema profiling and the schema text handed to the model.

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
from app.ingestion.engine import DataEngine, LoadedTable
from app.intelligence.relationship_detector import Join, join_key_columns
from app.validation.pii import mask_rows

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    """Split an identifier or question into comparable lowercase tokens."""
    return set(_WORD.findall(text.lower()))


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
    join_cols = join_key_columns(engine)
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
