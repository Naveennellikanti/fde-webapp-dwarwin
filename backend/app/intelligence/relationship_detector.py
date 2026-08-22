"""Cross-file relationship detection.

The model cannot join tables it does not know are related, so candidate join keys are
inferred at upload time and handed to it as hints. Purely heuristic — name and dtype
agreement, scored by how much the two columns' values actually overlap — and always
surfaced alongside the generated SQL, so a wrong guess is visible rather than silent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.ingestion.engine import DataEngine

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


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


def join_key_columns(engine: DataEngine) -> set[tuple[str, str]]:
    """Every column participating in a detected relationship.

    Schema retrieval keeps these even when a question does not mention them, so
    narrowing the schema can never make a cross-file question unanswerable.
    """
    cols: set[tuple[str, str]] = set()
    for j in detect_joins(engine):
        cols.add((j.left_table, j.left_column))
        cols.add((j.right_table, j.right_column))
    return cols
