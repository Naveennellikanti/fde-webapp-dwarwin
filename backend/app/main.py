"""FastAPI app: session, upload, schema, ask.

Run locally:  uvicorn app.main:app --reload --port 8000  (single worker — see README)
"""
from __future__ import annotations

import logging
import re

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.ingestion import schema_profiler as schema_mod
from app.intelligence.relationship_detector import detect_joins
from app.runtime.settings import effective_settings, update_overrides
from app.runtime.session_store import SessionStore
from app.intelligence.llm.base import LLMUnavailableError
from app.intelligence.llm.factory import get_provider
from app.intelligence.llm.groq_provider import GroqProvider
from app.intelligence.llm.ollama_provider import OllamaProvider
from app.schemas import (
    AskRequest,
    AskResponse,
    ColumnInfo,
    JoinHint,
    SchemaResponse,
    SessionResponse,
    ColumnQualityInfo,
    QualityIssueInfo,
    TableQualityInfo,
    SessionKeyUpdate,
    SettingsUpdate,
    TableInfo,
    UploadResponse,
)
from app.analytics.pipeline import Turn, answer_question
from app.validation.data_quality import profile_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dataqa")

settings = get_settings()
store = SessionStore(settings)

app = FastAPI(title="Data Q&A API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXT = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".json", ".ndjson", ".jsonl", ".parquet"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
async def config() -> dict[str, object]:
    """What the UI needs to know about the runtime. Never returns secrets."""
    eff = effective_settings(settings)
    backend, model = "unavailable", None
    try:
        provider = await get_provider(eff)
        backend, model = provider.name, getattr(provider, "model", None)
    except LLMUnavailableError:
        pass

    # Which backends *could* be selected — lets the UI disable impossible options
    # without ever revealing the key itself.
    ollama_ok, ollama_reason = await OllamaProvider(
        eff.ollama_url, eff.ollama_model, eff.temperature, eff.ollama_timeout_s
    ).status()
    groq_reason = "" if eff.groq_api_key else "No API key configured. Add one below."

    return {
        "backend": backend,
        "model": model,
        "llm_backend": eff.llm_backend,
        "schema_only": eff.schema_only,
        "sample_rows": eff.sample_rows,
        "max_upload_mb": eff.max_upload_mb,
        "allowed_extensions": sorted(ALLOWED_EXT),
        "available_backends": {
            "ollama": ollama_ok,
            "groq": bool(eff.groq_api_key),  # boolean only — the key is never exposed
        },
        # Why a backend is unavailable, so the UI can say what to do rather than just
        # greying the option out. Never contains a secret.
        "backend_notes": {
            "ollama": ollama_reason,
            "groq": groq_reason,
        },
    }


@app.put("/settings")
async def update_settings(req: SettingsUpdate) -> dict[str, object]:
    """Update non-secret runtime settings from the UI.

    API keys are intentionally NOT settable here — they stay in the server environment.
    """
    try:
        update_overrides(
            schema_only=req.schema_only,
            llm_backend=req.llm_backend,
            sample_rows=req.sample_rows,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await config()


@app.post("/session", response_model=SessionResponse)
async def create_session() -> SessionResponse:
    s = store.create()
    return SessionResponse(session_id=s.id)


@app.delete("/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    return {"deleted": store.delete(session_id)}


@app.put("/session/{session_id}/key")
async def set_session_key(session_id: str, req: SessionKeyUpdate) -> dict[str, object]:
    """Attach a bring-your-own API key to one session.

    Scoped to the session on purpose. A single global key settable over HTTP would let
    any visitor to a deployed instance replace the key that everyone else's questions
    are billed to, so this never touches the process-wide configuration and is never
    written to disk. `POST /ask` prefers the session key when present and otherwise
    falls back to the server environment.

    The response reports only whether a key is now held — the value is never echoed.
    """
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    key = (req.api_key or "").strip()
    if not key:
        session.api_key = None
        return {**session.redacted(), "verified": False}

    # Verify before storing, so a typo surfaces here rather than on the next question.
    eff = effective_settings(settings)
    probe = GroqProvider(
        key, eff.groq_base_url, eff.groq_model, eff.temperature, eff.request_timeout_s
    )
    if not await probe.verify_key():
        raise HTTPException(
            status_code=400,
            detail=(
                "That key was rejected by the model provider (or it could not be "
                "reached). It has not been stored."
            ),
        )

    session.api_key = key
    return {**session.redacted(), "verified": True}


@app.delete("/session/{session_id}/key")
async def clear_session_key(session_id: str) -> dict[str, object]:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    session.api_key = None
    return session.redacted()


@app.post("/upload", response_model=UploadResponse)
async def upload(
    session_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    for f in files:
        name = f.filename or "upload"
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        if ext not in ALLOWED_EXT:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {name}")

        data = await f.read()
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413, detail=f"{name} exceeds the {settings.max_upload_mb} MB limit."
            )
        try:
            if ext in {".xlsx", ".xls"}:
                session.engine.add_excel(name, data)
            elif ext in {".json", ".ndjson", ".jsonl"}:
                session.engine.add_json(name, data)
            elif ext == ".parquet":
                session.engine.add_parquet(name, data)
            else:
                session.engine.add_csv(name, data)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Could not parse {name}: {e}") from e

    # Profile once, here, rather than per question.
    session.quality = profile_session(session.engine)
    return _schema_response(session_id)


@app.delete("/session/{session_id}/table/{table}", response_model=UploadResponse)
async def drop_table(session_id: str, table: str) -> UploadResponse:
    """Remove one loaded table.

    Excel sheets are separate tables, so a workbook is removed a sheet at a time —
    which matches what the sidebar lists, and lets you keep one sheet and drop another.
    """
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if not session.engine.drop_table(table):
        raise HTTPException(status_code=404, detail=f"No table named {table!r} in this session.")

    # The cached profile and join map describe a schema that no longer exists.
    session.quality = profile_session(session.engine)

    # Conversation history keeps prior SQL so follow-ups can be resolved against it.
    # Any turn referencing the dropped table would now feed the model a query it cannot
    # run, so those turns are forgotten rather than left to cause a retry loop.
    session.history = [
        t for t in session.history
        if not (t.sql and re.search(rf'\b"?{re.escape(table)}"?\b', t.sql, re.I))
    ]
    return _schema_response(session_id)


@app.get("/schema/{session_id}", response_model=SchemaResponse)
async def get_schema(session_id: str) -> SchemaResponse:
    if not store.get(session_id):
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    return _schema_response(session_id)


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    session = store.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if not session.engine.tables:
        raise HTTPException(status_code=400, detail="Upload at least one file first.")
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    # Cost guard: hard stop so a runaway session can never rack up spend.
    if session.tokens_used >= settings.session_token_budget:
        raise HTTPException(
            status_code=429,
            detail="This session reached its token budget. Start a new session.",
        )

    eff = effective_settings(settings)
    # A session-scoped key takes precedence over the server environment, so a reviewer
    # can bring their own without it leaking into anyone else's session.
    if session.api_key:
        eff = eff.model_copy(update={"groq_api_key": session.api_key})
    try:
        provider = await get_provider(eff)
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    try:
        result = await answer_question(
            engine=session.engine,
            provider=provider,
            settings=eff,
            question=req.question.strip(),
            history=session.history,
            session_id=req.session_id,
            quality=session.quality,
        )
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    session.tokens_used += result.tokens_used
    session.history.append(Turn(question=req.question.strip(), sql=result.sql))
    # Audit trail: question -> SQL is logged for traceability.
    logger.info("session=%s q=%r sql=%r status=%s", req.session_id, req.question, result.sql, result.status)
    return result


def _schema_response(session_id: str) -> UploadResponse:
    session = store.get(session_id)
    assert session is not None
    engine = session.engine
    joins = detect_joins(engine)
    tables = [
        TableInfo(
            name=t.name,
            source_file=t.source_file,
            columns=[ColumnInfo(name=c[0], dtype=c[1]) for c in t.columns],
            row_count=t.row_count,
            sample_rows=engine.sample_rows(t.name, 5),
        )
        for t in engine.tables.values()
    ]
    return UploadResponse(
        session_id=session_id,
        tables=tables,
        quality=[
            TableQualityInfo(
                table=q.table,
                row_count=q.row_count,
                duplicate_rows=q.duplicate_rows,
                columns=[
                    ColumnQualityInfo(
                        name=c.name, dtype=c.dtype, null_count=c.null_count,
                        null_pct=c.null_pct, distinct_count=c.distinct_count,
                    )
                    for c in q.columns
                ],
                issues=[
                    QualityIssueInfo(
                        kind=i.kind, severity=i.severity, message=i.message, column=i.column
                    )
                    for i in q.issues
                ],
            )
            for q in session.quality
        ],
        joins=[
            JoinHint(
                left_table=j.left_table, left_column=j.left_column,
                right_table=j.right_table, right_column=j.right_column,
                confidence=j.confidence,
            )
            for j in joins
        ],
    )
