"""Per-session DuckDB engine.

One `DataEngine` == one in-memory DuckDB database holding all of a session's tables
(each CSV -> one table, each Excel sheet -> one table). The engine is sandboxed:
no external file/network access, read-only querying, statement timeout, row cap.
"""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from app.ingestion.naming import unique_name


@dataclass
class LoadedTable:
    name: str
    source_file: str
    columns: list[tuple[str, str]]  # (name, dtype)
    row_count: int


@dataclass
class DataEngine:
    con: duckdb.DuckDBPyConnection
    tables: dict[str, LoadedTable] = field(default_factory=dict)
    _taken: set[str] = field(default_factory=set)

    @classmethod
    def create(cls, statement_timeout_s: int = 30) -> "DataEngine":
        con = duckdb.connect(database=":memory:")
        # ---- sandboxing -------------------------------------------------------
        # Block reading arbitrary files / http(s) from inside SQL the model writes.
        try:
            con.execute("SET enable_external_access = false")
        except Exception:  # noqa: BLE001 - older/newer duckdb may name this differently
            pass
        try:
            con.execute(f"SET statement_timeout = '{int(statement_timeout_s) * 1000}ms'")
        except Exception:  # noqa: BLE001
            pass
        return cls(con=con)

    # ---- ingestion ------------------------------------------------------------
    def add_csv(self, filename: str, data: bytes) -> LoadedTable:
        table = unique_name(_strip_ext(filename), self._taken)
        df = _read_csv_bytes(data)
        return self._register_df(table, filename, df)

    def add_excel(self, filename: str, data: bytes) -> list[LoadedTable]:
        xls = pd.ExcelFile(io.BytesIO(data))
        loaded: list[LoadedTable] = []
        multi = len(xls.sheet_names) > 1
        for sheet in xls.sheet_names:
            df = xls.parse(sheet)
            if df.empty and len(df.columns) == 0:
                continue
            base = f"{_strip_ext(filename)}_{sheet}" if multi else _strip_ext(filename)
            table = unique_name(base, self._taken)
            loaded.append(self._register_df(table, f"{filename} [{sheet}]", df))
        return loaded

    def add_json(self, filename: str, data: bytes) -> LoadedTable:
        """JSON / NDJSON. Nested objects are flattened into dotted column names."""
        table = unique_name(_strip_ext(filename), self._taken)
        df = _read_json_bytes(data)
        return self._register_df(table, filename, df)

    def add_parquet(self, filename: str, data: bytes) -> LoadedTable:
        table = unique_name(_strip_ext(filename), self._taken)
        df = pd.read_parquet(io.BytesIO(data))
        return self._register_df(table, filename, df)

    def _register_df(self, table: str, source_file: str, df: pd.DataFrame) -> LoadedTable:
        df = _clean_columns(df)
        df = _coerce_dates(df)
        # DuckDB reads directly from the pandas frame, inferring types.
        self.con.register(f"_tmp_{table}", df)
        self.con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM _tmp_{table}')
        self.con.unregister(f"_tmp_{table}")

        cols = self.con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall()
        row_count = self.con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

        lt = LoadedTable(
            name=table,
            source_file=source_file,
            columns=[(c[0], c[1]) for c in cols],
            row_count=int(row_count),
        )
        self.tables[table] = lt
        return lt

    def drop_table(self, table: str) -> bool:
        """Remove one loaded table and its data. False if it was not loaded.

        The identifier is released as well, so re-uploading the same file gets its
        original name back rather than `sales_2` — otherwise correcting a mistaken
        upload would leave the schema permanently renamed.
        """
        if table not in self.tables:
            return False
        self.con.execute(f'DROP TABLE IF EXISTS "{table}"')
        del self.tables[table]
        self._taken.discard(table)
        return True

    # ---- querying -------------------------------------------------------------
    def sample_rows(self, table: str, n: int) -> list[dict[str, Any]]:
        if n <= 0:
            return []
        df = self.con.execute(f'SELECT * FROM "{table}" LIMIT {int(n)}').fetch_df()
        return _df_to_records(df)

    def run_select(self, sql: str, row_cap: int) -> tuple[list[str], list[dict[str, Any]], bool]:
        """Execute a validated SELECT. Returns (columns, rows, truncated)."""
        rel = self.con.execute(sql)
        columns = [d[0] for d in rel.description]
        df = rel.fetch_df()
        truncated = False
        if len(df) > row_cap:
            df = df.head(row_cap)
            truncated = True
        return columns, _df_to_records(df), truncated

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:  # noqa: BLE001
            pass


# ---- helpers --------------------------------------------------------------------
def _strip_ext(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    """Robust CSV reader: sniff encoding + delimiter via pandas' python engine."""
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    # Last resort: default settings.
    return pd.read_csv(io.BytesIO(data))


def _read_json_bytes(data: bytes) -> pd.DataFrame:
    """Read a JSON array, a JSON object of arrays, or NDJSON — flattening nested keys."""
    text = data.decode("utf-8-sig", errors="replace").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Newline-delimited JSON
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        return pd.json_normalize(records)

    if isinstance(parsed, list):
        return pd.json_normalize(parsed)
    if isinstance(parsed, dict):
        # A wrapper like {"data": [...]} is very common — unwrap the single list value.
        list_values = [v for v in parsed.values() if isinstance(v, list)]
        if len(list_values) == 1:
            return pd.json_normalize(list_values[0])
        return pd.json_normalize(parsed)
    raise ValueError("Unsupported JSON structure — expected an array or object.")


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    seen: dict[str, int] = {}
    new_cols = []
    for c in df.columns:
        name = str(c).strip()
        if name == "" or name.lower().startswith("unnamed"):
            name = "column"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        new_cols.append(name)
    df.columns = new_cols
    return df


_DATE_HINT = re.compile(r"(date|time|day|month|year|created|updated|ts|period)", re.I)
_DATE_SHAPE = re.compile(r"^\s*\d{1,4}[-/]\d{1,2}[-/]\d{1,4}")


def _coerce_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse date-looking text columns into real timestamps.

    Without this, `order_date` lands as VARCHAR and every trend question fails at the
    DuckDB binder (strftime/date_trunc need a DATE/TIMESTAMP). We only convert a column
    when it is text, looks like a date, and parses cleanly for ~all non-null values.
    """
    df = df.copy()
    for col in df.columns:
        if df[col].dtype != object:
            continue
        non_null = df[col].dropna()
        if non_null.empty:
            continue
        sample = non_null.head(200).astype(str)
        looks_like_date = sample.str.match(_DATE_SHAPE).mean() > 0.9
        if not (looks_like_date or _DATE_HINT.search(str(col))):
            continue
        parsed = pd.to_datetime(df[col], errors="coerce", format="mixed")
        # Require nearly every non-null value to parse, else leave the column alone.
        if parsed.notna().sum() >= 0.95 * len(non_null):
            df[col] = parsed
    return df


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    # Convert to JSON-safe python types (NaN -> None, Timestamp -> isoformat).
    safe = df.where(pd.notnull(df), None)
    records: list[dict[str, Any]] = []
    for row in safe.to_dict(orient="records"):
        out: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, (pd.Timestamp,)):
                out[k] = v.isoformat()
            elif hasattr(v, "item"):  # numpy scalar
                try:
                    out[k] = v.item()
                except Exception:  # noqa: BLE001
                    out[k] = v
            else:
                out[k] = v
        records.append(out)
    return records
