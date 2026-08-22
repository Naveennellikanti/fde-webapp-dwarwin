"""FastAPI app: session, upload, schema, ask.

Run locally:  uvicorn app.main:app --reload --port 8000  (single worker — see README)
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core import schema as schema_mod
from app.core.runtime_settings import effective_settings, update_overrides
from app.core.session_store import SessionStore
from app.llm.base import LLMUnavailableError
from app.llm.factory import get_provider
from app.llm.ollama_provider import OllamaProvider
from app.schemas import (
    AskRequest,
    AskResponse,
    ColumnInfo,
    JoinHint,
    SchemaResponse,
    SessionResponse,
    SettingsUpdate,
    TableInfo,
    UploadResponse,
)
from app.services.pipeline import Turn, answer_question

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
    ollama_ok = await OllamaProvider(
        eff.ollama_url, eff.ollama_model, eff.temperature, eff.request_timeout_s
    ).available()

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
    joins = schema_mod.detect_joins(engine)
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
        joins=[
            JoinHint(
                left_table=j.left_table, left_column=j.left_column,
                right_table=j.right_table, right_column=j.right_column,
                confidence=j.confidence,
            )
            for j in joins
        ],
    )
