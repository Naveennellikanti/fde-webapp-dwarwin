"""The /ask pipeline: question -> SQL -> guardrail -> execute -> (retry) -> chart + answer.

Design notes
------------
* Data never enters the prompt. Only the compact schema (+ optional masked samples)
  does, so token cost is ~constant regardless of file size.
* The LLM never does arithmetic. DuckDB computes; the model only translates and
  explains the returned numbers.
* Failed SQL is fed back to the model with its error (bounded retries) — this is what
  turns a brittle demo into something that actually holds up.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.core import schema as schema_mod
from app.core.duckdb_engine import DataEngine
from app.core.guardrails import GuardrailError, validate_select
from app.llm.base import LLMProvider
from app.schemas import AskResponse, ChartSpec, SqlAttempt
from app.services.chart_selector import select_chart
from app.services.prompts import CANNOT_ANSWER, SQL_SYSTEM, SUMMARY_SYSTEM
from app.services.sql_generator import SqlGenerator, build_sql_generator

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.S | re.I)
# Reasoning models (Qwen3, DeepSeek-R1, …) prefix their answer with a thinking block.
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_OPEN_THINK = re.compile(r"^.*?</think>", re.S | re.I)
_SQL_START = re.compile(r"\b(WITH|SELECT)\b", re.I)


@dataclass
class Turn:
    """One prior exchange, kept compact — we store the SQL, never the result data."""
    question: str
    sql: str | None


def _clean_sql(text: str) -> str:
    """Extract the SQL from a model response.

    Handles markdown fences and the <think> blocks emitted by reasoning models, so the
    app stays portable across model families rather than being tuned to one.
    """
    text = (text or "").strip()

    text = _THINK.sub("", text)
    if "</think>" in text.lower():  # unclosed/truncated thinking block
        text = _OPEN_THINK.sub("", text)
    text = text.strip()

    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()

    # Keep the CANNOT_ANSWER sentinel intact; otherwise drop any prose before the SQL.
    if CANNOT_ANSWER not in text:
        start = _SQL_START.search(text)
        if start and start.start() > 0:
            text = text[start.start():]
    return text.strip()


def _history_block(history: list[Turn], limit: int) -> str:
    """Bounded multi-turn context: last N turns as (question, sql) pairs only.

    We deliberately do NOT resend prior result rows — that is what makes multi-turn
    cheap and keeps follow-ups ("now break that down by month") grounded in the SQL.
    """
    recent = history[-limit:] if limit > 0 else []
    if not recent:
        return ""
    lines = ["PREVIOUS TURNS (for resolving follow-up references like 'that' or 'those'):"]
    for t in recent:
        lines.append(f"  Q: {t.question}")
        if t.sql:
            lines.append(f"  SQL: {t.sql}")
    return "\n".join(lines)


async def answer_question(
    *,
    engine: DataEngine,
    provider: LLMProvider,
    settings: Settings,
    question: str,
    history: list[Turn],
    session_id: str,
    sql_generator: SqlGenerator | None = None,
) -> AskResponse:
    tokens_used = 0
    attempts: list[SqlAttempt] = []
    # SQL generation is pluggable (native provider call, or a LangChain LCEL chain).
    # Everything after generation — guardrails, execution, retries — is identical.
    generator = sql_generator or build_sql_generator(settings.sql_generator, provider)

    # ---- 1. Ground the model in the (possibly narrowed) schema ------------------
    tables, per_cols = schema_mod.select_relevant(engine, question, settings)
    joins = schema_mod.detect_joins(engine)
    schema_text = schema_mod.build_schema_context(engine, settings, tables, per_cols, joins)

    history_text = _history_block(history, settings.max_history_turns)
    base_prompt = f"SCHEMA:\n{schema_text}\n"
    if history_text:
        base_prompt += f"\n{history_text}\n"
    base_prompt += f"\nQUESTION: {question}\n\nSQL:"

    messages: list[dict[str, str]] = [{"role": "user", "content": base_prompt}]

    # ---- 2. Generate -> validate -> execute, with self-correction ---------------
    last_error: str | None = None
    for attempt in range(settings.max_sql_retries):
        completion = await generator.complete(SQL_SYSTEM, messages, settings.sql_max_tokens)
        tokens_used += completion.tokens_used
        raw = _clean_sql(completion.text)

        # The model may explicitly decline — honest failure beats a confident wrong answer.
        if raw.startswith(CANNOT_ANSWER) or CANNOT_ANSWER in raw:
            reason = raw.split(CANNOT_ANSWER, 1)[1].strip() or "the uploaded data does not contain it"
            return AskResponse(
                session_id=session_id, question=question, status="cannot_answer",
                answer=f"I can't answer that from the uploaded data — {reason}",
                attempts=attempts, backend_used=completion.backend, tokens_used=tokens_used,
            )

        try:
            sql = validate_select(raw)
        except GuardrailError as e:
            last_error = f"Rejected by safety check: {e}"
            attempts.append(SqlAttempt(sql=raw, error=last_error))
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"{last_error}\nReturn a single read-only SELECT. SQL:"},
            ]
            continue

        try:
            columns, rows, truncated = engine.run_select(sql, settings.result_row_cap)
        except Exception as e:  # noqa: BLE001 - any DuckDB error feeds the retry loop
            last_error = str(e).strip().splitlines()[0][:400]
            attempts.append(SqlAttempt(sql=sql, error=last_error))
            messages += [
                {"role": "assistant", "content": sql},
                {
                    "role": "user",
                    "content": (
                        f"That query failed with:\n{last_error}\n"
                        "Fix it using only the columns in the schema. Return corrected SQL only."
                    ),
                },
            ]
            continue

        # ---- 3. Success path -------------------------------------------------
        attempts.append(SqlAttempt(sql=sql, error=None))

        if not rows:
            return AskResponse(
                session_id=session_id, question=question, status="empty",
                answer="That query ran fine but matched no rows. Try widening the filters.",
                sql=sql, columns=columns, rows=[], chart=ChartSpec(type="none"),
                attempts=attempts, backend_used=completion.backend, tokens_used=tokens_used,
            )

        chart = select_chart(columns, rows, question)
        summary, summary_tokens, backend = await _summarize(
            provider, settings, question, columns, rows
        )
        tokens_used += summary_tokens

        return AskResponse(
            session_id=session_id, question=question, status="ok", answer=summary,
            sql=sql, columns=columns, rows=rows, chart=chart, attempts=attempts,
            backend_used=backend or completion.backend, tokens_used=tokens_used,
            truncated=truncated,
        )

    # ---- 4. Exhausted retries — surface the real error, don't fake an answer ----
    return AskResponse(
        session_id=session_id, question=question, status="error",
        answer=(
            "I couldn't build a working query for that question after several attempts. "
            f"Last error: {last_error}. Try rephrasing, or check the column names in the sidebar."
        ),
        sql=attempts[-1].sql if attempts else None,
        attempts=attempts, tokens_used=tokens_used,
    )


async def _summarize(
    provider: LLMProvider,
    settings: Settings,
    question: str,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> tuple[str, int, str | None]:
    """Explain the RESULT (small, already-computed) — never the source data."""
    preview = rows[:20]
    payload = json.dumps({"columns": columns, "rows": preview}, default=str)[:4000]
    note = "" if len(rows) <= 20 else f"\n(showing first 20 of {len(rows)} result rows)"
    user = f"QUESTION: {question}\n\nRESULT:\n{payload}{note}\n\nAnswer:"
    try:
        c = await provider.complete(SUMMARY_SYSTEM, [{"role": "user", "content": user}],
                                    settings.summary_max_tokens)
        text = c.text.strip()
        return (text or _fallback_answer(columns, rows)), c.tokens_used, c.backend
    except Exception:  # noqa: BLE001 - summary is a nicety; the numbers are already correct
        return _fallback_answer(columns, rows), 0, None


def _fallback_answer(columns: list[str], rows: list[dict[str, Any]]) -> str:
    if len(rows) == 1 and len(columns) == 1:
        return f"{columns[0].replace('_', ' ').title()}: {rows[0][columns[0]]}"
    return f"Returned {len(rows)} row(s) across {len(columns)} column(s). See the table below."
