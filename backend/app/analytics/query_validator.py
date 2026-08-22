"""SQL guardrails: only a single read-only SELECT is ever allowed to run.

The LLM writes the SQL, so the risk is not classic injection but *unsafe or runaway*
SQL. We parse with sqlglot and reject anything that is not a lone SELECT/CTE, plus we
block statement types that could mutate data or touch the filesystem/network.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

# Expression types that must never appear anywhere in the parsed tree.
_FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Command,  # Command covers PRAGMA/ATTACH/COPY/INSTALL/SET/EXPORT etc.
)

# Table/scalar functions that reach the filesystem or network. A model-written
# `SELECT * FROM read_csv_auto('/etc/passwd')` is a valid SELECT, so the statement-type
# check above is not enough — these must be blocked by name.
_FORBIDDEN_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto",
    "read_ndjson", "read_ndjson_auto", "read_text", "read_blob", "parquet_scan",
    "json_scan", "csv_scan", "glob", "sniff_csv", "read_xlsx",
    "install", "load", "attach", "detach", "copy",
    "duckdb_settings", "duckdb_extensions", "sha256_file",
}


class GuardrailError(Exception):
    pass


def validate_select(sql: str) -> str:
    """Return the (single) SQL statement if it is a safe read-only SELECT, else raise."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise GuardrailError("Empty SQL statement.")

    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except Exception as e:  # noqa: BLE001
        raise GuardrailError(f"Could not parse SQL: {e}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise GuardrailError("Only a single SQL statement is allowed.")

    stmt = statements[0]

    # Top-level must be a SELECT or a WITH ... SELECT.
    root = stmt
    if isinstance(root, exp.With):
        root = root.this
    if not isinstance(root, (exp.Select, exp.Union, exp.Subquery)):
        raise GuardrailError("Only read-only SELECT queries are allowed.")

    # No forbidden node anywhere in the tree.
    for node in stmt.walk():
        node = node[0] if isinstance(node, tuple) else node
        if isinstance(node, _FORBIDDEN):
            raise GuardrailError(f"Statement type '{type(node).__name__}' is not allowed.")

        # Block filesystem/network-reaching functions, however sqlglot represents them.
        fname: str | None = None
        if isinstance(node, exp.Anonymous):
            fname = str(node.this or "")
        elif isinstance(node, exp.ReadCSV):
            fname = "read_csv"
        elif isinstance(node, exp.Func):
            fname = node.sql_name()
        if fname and fname.lower() in _FORBIDDEN_FUNCTIONS:
            raise GuardrailError(
                f"Function '{fname}' is not allowed (filesystem/network access is blocked)."
            )

    return sql


def referenced_tables(sql: str) -> set[str]:
    """Best-effort set of base table names referenced by the query."""
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:  # noqa: BLE001
        return set()
    names: set[str] = set()
    for t in tree.find_all(exp.Table):
        if t.name:
            names.add(t.name)
    return names
