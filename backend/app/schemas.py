"""Pydantic request/response models — the contract shared with the Next.js frontend."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---- Schema description ---------------------------------------------------------
class ColumnInfo(BaseModel):
    name: str
    dtype: str


class TableInfo(BaseModel):
    name: str
    source_file: str
    columns: list[ColumnInfo]
    row_count: int
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)


class JoinHint(BaseModel):
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float


class SchemaResponse(BaseModel):
    session_id: str
    tables: list[TableInfo]
    joins: list[JoinHint] = Field(default_factory=list)


# ---- Session / upload -----------------------------------------------------------
class SessionResponse(BaseModel):
    session_id: str


class SettingsUpdate(BaseModel):
    """Non-secret runtime settings the UI may change. API keys are NOT settable here."""
    schema_only: Optional[bool] = None
    llm_backend: Optional[Literal["auto", "ollama", "groq"]] = None
    sample_rows: Optional[int] = Field(default=None, ge=0, le=10)


class SessionKeyUpdate(BaseModel):
    """Bring-your-own API key for a single session.

    Send an empty value to clear it. The key is never returned by any endpoint — the
    responses carry `has_key` instead.
    """
    api_key: Optional[str] = Field(default=None, max_length=512)


class UploadResponse(SchemaResponse):
    pass


# ---- Ask ------------------------------------------------------------------------
class AskRequest(BaseModel):
    session_id: str
    question: str


class ChartSpec(BaseModel):
    type: Literal["bar", "line", "scatter", "kpi", "table", "none"]
    x: Optional[str] = None
    y: Optional[str] = None
    series: Optional[str] = None
    title: Optional[str] = None


class SqlAttempt(BaseModel):
    sql: str
    error: Optional[str] = None


class AskResponse(BaseModel):
    session_id: str
    question: str
    status: Literal["ok", "cannot_answer", "empty", "error"]
    answer: str
    sql: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    chart: ChartSpec = ChartSpec(type="none")
    attempts: list[SqlAttempt] = Field(default_factory=list)
    backend_used: Optional[str] = None
    tokens_used: int = 0
    truncated: bool = False
