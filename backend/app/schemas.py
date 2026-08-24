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
    quality: list[TableQualityInfo] = Field(default_factory=list)


# ---- Session / upload -----------------------------------------------------------
class SessionResponse(BaseModel):
    session_id: str


class SettingsUpdate(BaseModel):
    """Non-secret runtime settings the UI may change. API keys are NOT settable here."""
    schema_only: Optional[bool] = None
    llm_backend: Optional[Literal["auto", "ollama", "groq"]] = None
    sample_rows: Optional[int] = Field(default=None, ge=0, le=10)


class CleaningOpInfo(BaseModel):
    id: str
    kind: str
    table: str
    column: Optional[str] = None
    description: str
    impact: str = ""


class CleaningProposal(BaseModel):
    table: str
    ops: list[CleaningOpInfo] = Field(default_factory=list)
    undo_available: bool = False


class CleaningApplyRequest(BaseModel):
    op_ids: list[str] = Field(default_factory=list)


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


class ColumnQualityInfo(BaseModel):
    name: str
    dtype: str
    null_count: int
    null_pct: float
    distinct_count: int


class QualityIssueInfo(BaseModel):
    kind: str
    severity: Literal["info", "warning"]
    message: str
    column: Optional[str] = None


class TableQualityInfo(BaseModel):
    table: str
    row_count: int
    duplicate_rows: int
    columns: list[ColumnQualityInfo] = Field(default_factory=list)
    issues: list[QualityIssueInfo] = Field(default_factory=list)


class ProbeInfo(BaseModel):
    """One query run during an investigation, kept so any claim can be checked."""
    goal: str
    sql: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class FindingInfo(BaseModel):
    headline: str
    detail: str = ""
    severity: Literal["notable", "watch", "ok"] = "notable"
    evidence: Optional[int] = None


class ConversationTurn(BaseModel):
    """One stored exchange, for rebuilding the chat thread after a refresh."""
    question: str
    response: "AskResponse"


class ConversationResponse(BaseModel):
    session_id: str
    turns: list[ConversationTurn] = Field(default_factory=list)


class AskResponse(BaseModel):
    session_id: str
    question: str
    status: Literal[
        "ok", "cannot_answer", "empty", "error", "needs_clarification", "investigation"
    ]
    answer: str
    sql: Optional[str] = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    chart: ChartSpec = ChartSpec(type="none")
    attempts: list[SqlAttempt] = Field(default_factory=list)
    backend_used: Optional[str] = None
    tokens_used: int = 0
    # For an investigation, the two model calls itemised (plan + synthesis). Lets the UI
    # show the cost as bounded, named work rather than one large opaque figure. Null on a
    # single-query answer, which is one call and needs no breakdown.
    plan_tokens: Optional[int] = None
    synthesis_tokens: Optional[int] = None
    truncated: bool = False

    # ---- validation & transparency -------------------------------------------
    # Things the user should know about this answer without having to read the SQL.
    caveats: list[str] = Field(default_factory=list)
    # Interpretations the app chose on the user's behalf, stated rather than hidden.
    assumptions: list[str] = Field(default_factory=list)
    # Set when status == "needs_clarification": the readings worth choosing between.
    clarification_options: list[str] = Field(default_factory=list)
    # Derived from how the answer was produced, not from asking the model.
    confidence: Optional[Literal["high", "medium", "low"]] = None
    confidence_score: Optional[float] = None
    confidence_reasons: list[str] = Field(default_factory=list)

    # ---- investigation (status == "investigation") ----------------------------
    # Several probes were run and read together; each finding points at the probe it
    # came from so the reader can verify rather than trust.
    findings: list[FindingInfo] = Field(default_factory=list)
    probes: list[ProbeInfo] = Field(default_factory=list)


# ConversationTurn references AskResponse by name (forward ref); resolve it now that the
# concrete class exists.
ConversationTurn.model_rebuild()
