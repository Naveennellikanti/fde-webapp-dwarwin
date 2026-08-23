"""Pipeline tests using a scripted mock LLM.

These verify the parts that must be right regardless of which model is plugged in:
guardrails, the self-correction retry loop, honest failure, chart selection, and that
DuckDB (not the model) produces the numbers.

Run:  .venv/Scripts/python.exe -m pytest tests -q     (or: python tests/test_pipeline.py)
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd  # noqa: E402

from app.config import Settings  # noqa: E402
from app.ingestion.engine import DataEngine  # noqa: E402
from app.analytics.query_validator import GuardrailError, validate_select  # noqa: E402
from app.intelligence.llm.base import Completion, LLMProvider  # noqa: E402
from app.visualization.chart_builder import select_chart  # noqa: E402
from app.analytics.pipeline import answer_question  # noqa: E402


class ScriptedProvider(LLMProvider):
    """Returns pre-scripted completions in order — lets us test the retry loop."""
    name = "mock"

    def __init__(self, sql_script: list[str], summary: str = "Mock summary."):
        self.sql_script = list(sql_script)
        self.summary = summary
        self.calls: list[list[dict[str, str]]] = []

    async def available(self) -> bool:
        return True

    async def complete(self, system, messages, max_tokens):  # noqa: ANN001
        self.calls.append(messages)
        # Intent routing now precedes SQL generation; answer "lookup" without spending a
        # scripted SQL, so these tests exercise the single-query path they are about.
        if "classify a data question" in system.lower():
            return Completion(text="lookup", tokens_used=2, backend="mock")
        if "explain analytical query results" in system:
            return Completion(text=self.summary, tokens_used=10, backend="mock")
        text = self.sql_script.pop(0) if self.sql_script else "SELECT 1"
        return Completion(text=text, tokens_used=20, backend="mock")


def build_engine() -> tuple[DataEngine, pd.DataFrame]:
    sales = pd.DataFrame({
        "order_date": pd.to_datetime(
            ["2024-01-05", "2024-01-20", "2024-02-11", "2024-02-27", "2024-03-03"]
        ),
        "region": ["West", "East", "West", "North", "East"],
        "rep_id": [1, 2, 1, 3, 2],
        "revenue": [100.0, 250.5, 400.25, 75.0, 300.0],
    })
    reps = pd.DataFrame({
        "rep_id": [1, 2, 3],
        "rep_name": ["Ann", "Bo", "Cy"],
        "email": ["ann@example.com", "bo@example.com", "cy@example.com"],
    })
    engine = DataEngine.create()
    engine.add_csv("sales.csv", sales.to_csv(index=False).encode())
    engine.add_csv("reps.csv", reps.to_csv(index=False).encode())
    return engine, sales


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------- guardrails ----
def test_guardrails():
    allowed = ["SELECT 1", "WITH x AS (SELECT 1 a) SELECT * FROM x", "select * from sales limit 5"]
    blocked = [
        "DROP TABLE sales", "INSERT INTO sales VALUES (1)", "UPDATE sales SET revenue=0",
        "DELETE FROM sales", "SELECT 1; DELETE FROM sales", "PRAGMA database_list",
        "COPY sales TO 'out.csv'", "ATTACH 'x.db'", "INSTALL httpfs",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM read_parquet('s3://bucket/x.parquet')",
        "SELECT * FROM glob('C:/**')",
    ]
    for sql in allowed:
        validate_select(sql)
    for sql in blocked:
        try:
            validate_select(sql)
        except GuardrailError:
            continue
        raise AssertionError(f"guardrail failed to block: {sql}")
    print("PASS  guardrails: allowed 3, blocked 12")


# ------------------------------------------------------------ chart selection ---
def test_chart_selection():
    cases = [
        (["total"], [{"total": 5}], "kpi"),
        (["region", "rev"], [{"region": "W", "rev": 1}, {"region": "E", "rev": 2}], "bar"),
        (["month", "rev"],
         [{"month": "2024-01", "rev": 1}, {"month": "2024-02", "rev": 2}, {"month": "2024-03", "rev": 3}],
         "line"),
        (["x", "y"], [{"x": 1.0, "y": 2.0}, {"x": 2.0, "y": 4.0}, {"x": 3.0, "y": 9.0}], "scatter"),
        ([], [], "none"),
    ]
    for cols, rows, expected in cases:
        got = select_chart(cols, rows).type
        assert got == expected, f"{cols} -> expected {expected}, got {got}"
    print("PASS  chart selection: 5/5 shapes correct")


# ------------------------------------------------------------------- pipeline ---
def test_happy_path():
    engine, sales = build_engine()
    provider = ScriptedProvider(
        ["SELECT region, SUM(revenue) AS total_revenue FROM sales GROUP BY region ORDER BY total_revenue DESC"],
        summary="West leads with 500.25.",
    )
    res = run(answer_question(engine=engine, provider=provider, settings=Settings(),
                              question="revenue by region", history=[], session_id="s1"))
    assert res.status == "ok", res
    assert res.chart.type == "bar"
    # The numbers must come from DuckDB and match pandas exactly.
    expected = sales.groupby("region")["revenue"].sum().to_dict()
    got = {r["region"]: r["total_revenue"] for r in res.rows}
    assert got == expected, (got, expected)
    print(f"PASS  happy path: chart=bar, numbers match pandas exactly {got}")


def test_self_correction():
    """First SQL references a bad column; the pipeline must feed the error back and recover."""
    engine, _ = build_engine()
    provider = ScriptedProvider([
        "SELECT SUM(sales_amount) AS total FROM sales",          # bad column -> DuckDB error
        "SELECT SUM(revenue) AS total_revenue FROM sales",       # corrected
    ])
    res = run(answer_question(engine=engine, provider=provider, settings=Settings(),
                              question="total revenue", history=[], session_id="s1"))
    assert res.status == "ok", res
    assert len(res.attempts) == 2, res.attempts
    assert res.attempts[0].error is not None
    assert res.rows[0]["total_revenue"] == 1125.75
    # The retry prompt must actually contain the DuckDB error text.
    retry_prompt = provider.calls[1][-1]["content"]
    assert "failed with" in retry_prompt and "sales_amount" in retry_prompt
    print(f"PASS  self-correction: recovered on attempt 2, total={res.rows[0]['total_revenue']}")


def test_guardrail_rejection_is_retried():
    engine, _ = build_engine()
    provider = ScriptedProvider([
        "DROP TABLE sales",                                  # blocked by guardrail
        "SELECT COUNT(*) AS n FROM sales",                   # safe retry
    ])
    res = run(answer_question(engine=engine, provider=provider, settings=Settings(),
                              question="how many orders", history=[], session_id="s1"))
    assert res.status == "ok"
    assert "safety check" in (res.attempts[0].error or "")
    assert res.rows[0]["n"] == 5
    print("PASS  guardrail rejection fed back to model and recovered")


def test_cannot_answer():
    engine, _ = build_engine()
    provider = ScriptedProvider(["-- CANNOT_ANSWER: there is no customer age column"])
    res = run(answer_question(engine=engine, provider=provider, settings=Settings(),
                              question="what is the average customer age?", history=[], session_id="s1"))
    assert res.status == "cannot_answer", res
    assert res.chart.type == "none" and not res.rows
    print(f"PASS  honest failure: {res.answer!r}")


def test_retries_exhausted():
    engine, _ = build_engine()
    provider = ScriptedProvider(["SELECT bad1 FROM sales", "SELECT bad2 FROM sales", "SELECT bad3 FROM sales"])
    res = run(answer_question(engine=engine, provider=provider, settings=Settings(),
                              question="nonsense", history=[], session_id="s1"))
    assert res.status == "error"
    assert len(res.attempts) == 3
    print("PASS  retries exhausted -> honest error, no fabricated answer")


def test_cross_file_join():
    engine, _ = build_engine()
    provider = ScriptedProvider([
        "SELECT r.rep_name, SUM(s.revenue) AS rev FROM sales s "
        "JOIN reps r ON s.rep_id = r.rep_id GROUP BY 1 ORDER BY rev DESC"
    ])
    res = run(answer_question(engine=engine, provider=provider, settings=Settings(),
                              question="revenue by rep name", history=[], session_id="s1"))
    assert res.status == "ok"
    assert {r["rep_name"] for r in res.rows} == {"Ann", "Bo", "Cy"}
    assert res.rows[0]["rev"] == 550.5  # Bo: 250.5 + 300
    print(f"PASS  cross-file join: top rep {res.rows[0]['rep_name']} = {res.rows[0]['rev']}")


def test_multi_turn_context_is_bounded():
    """History must be included but must NOT grow without bound."""
    from app.analytics.pipeline import Turn, _history_block
    history = [Turn(question=f"q{i}", sql=f"SELECT {i}") for i in range(20)]
    block = _history_block(history, 4)
    assert "q19" in block and "q15" not in block, block
    assert block.count("Q:") == 4
    print("PASS  multi-turn context bounded to last 4 turns")


def test_data_never_enters_prompt():
    """The prompt may contain the schema, but must not contain bulk data rows."""
    engine, _ = build_engine()
    settings = Settings(schema_only=True)  # strictest privacy mode
    provider = ScriptedProvider(["SELECT COUNT(*) AS n FROM sales"])
    run(answer_question(engine=engine, provider=provider, settings=settings,
                        question="row count", history=[], session_id="s1"))
    prompt = provider.calls[0][0]["content"]
    assert "sample_rows" not in prompt, "schema_only mode leaked sample rows"
    assert "ann@example.com" not in prompt, "PII leaked into prompt"
    assert '"revenue" DOUBLE' in prompt, "schema missing from prompt"
    print(f"PASS  schema-only mode: no data values in prompt ({len(prompt)} chars)")


def test_pii_masking():
    from app.validation.pii import mask_value
    assert mask_value("ann@example.com") == "«email»"
    assert mask_value("2024-07-01") == "2024-07-01"          # dates preserved
    assert mask_value("2024-07-01T10:30:00") == "2024-07-01T10:30:00"
    assert mask_value(1234.56) == 1234.56                     # normal numbers preserved
    assert mask_value("123456789012") == "«id»"
    print("PASS  PII masking: emails/ids masked, dates & numbers preserved")


def test_ollama_errors_always_state_a_cause():
    """Timeouts must produce an actionable message, not a bare colon.

    Found live: httpx.ReadTimeout stringifies to "", so the UI rendered
    "Ollama request failed:" with nothing after it. Local inference is slow enough
    that timeouts are the *expected* failure, so this is the message users see most.
    """
    import httpx

    from app.intelligence.llm.base import LLMUnavailableError
    from app.intelligence.llm.ollama_provider import OllamaProvider

    provider = OllamaProvider("http://localhost:11434", "qwen2.5-coder:3b", 0.0, 300.0)

    class _RaisingClient:
        def __init__(self, exc): self.exc = exc
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise self.exc

    cases = {
        "timeout": httpx.ReadTimeout(""),          # empty str() — the original bug
        "connect": httpx.ConnectError(""),
        "other": httpx.HTTPError(""),
    }
    for label, exc in cases.items():
        original = httpx.AsyncClient
        httpx.AsyncClient = lambda *a, **k: _RaisingClient(exc)  # type: ignore[misc]
        try:
            try:
                run(provider.complete("sys", [{"role": "user", "content": "q"}], 100))
                raise AssertionError(f"{label}: expected LLMUnavailableError")
            except LLMUnavailableError as e:
                msg = str(e)
                assert not msg.rstrip().endswith(":"), f"{label}: message ends in a bare colon: {msg!r}"
                assert len(msg.split(":", 1)[-1].strip()) > 3, f"{label}: no cause given: {msg!r}"
        finally:
            httpx.AsyncClient = original  # type: ignore[misc]

    # The local timeout budget must be far larger than the hosted one.
    from app.config import Settings
    s = Settings()
    assert s.ollama_timeout_s >= 5 * s.request_timeout_s, (
        f"local timeout {s.ollama_timeout_s}s is too close to hosted {s.request_timeout_s}s"
    )
    print(f"PASS  ollama errors: {len(cases)} failure modes give a cause; "
          f"local budget {s.ollama_timeout_s:.0f}s vs hosted {s.request_timeout_s:.0f}s")


def test_ollama_availability_requires_the_model_not_just_the_server():
    """A reachable Ollama with the wrong model is not an available backend.

    Found by pointing the app at a model that was never pulled: /api/tags answered 200,
    so availability reported healthy, the UI offered "Local" as selectable, and the
    failure only surfaced as a 404 on the user's first question. Whether a backend can
    serve a request is the thing being asked, so the model has to be present.
    """
    import httpx

    from app.intelligence.llm.ollama_provider import OllamaProvider

    class _Response:
        def __init__(self, payload, status=200):
            self.status_code = status
            self._payload = payload
        def json(self):
            return self._payload

    class _Client:
        def __init__(self, payload, status=200, boom=False):
            self._payload, self._status, self._boom = payload, status, boom
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k):
            if self._boom:
                raise httpx.ConnectError("refused")
            return _Response(self._payload, self._status)

    installed = {"models": [{"name": "qwen2.5-coder:3b"}]}
    cases = [
        ("model present",   "qwen2.5-coder:3b", installed, False, True,  ""),
        ("model not pulled","llama3.3:70b",     installed, False, False, "not pulled"),
        ("untagged name",   "qwen2.5-coder",    installed, False, False, "not pulled"),
        ("no models at all","qwen2.5-coder:3b", {"models": []}, False, False, "no models"),
        ("server down",     "qwen2.5-coder:3b", installed, True,  False, "not running"),
    ]
    original = httpx.AsyncClient
    try:
        for label, model, payload, boom, want_ok, want_text in cases:
            httpx.AsyncClient = lambda *a, **k: _Client(payload, boom=boom)  # type: ignore[misc,assignment]
            provider = OllamaProvider("http://localhost:11434", model, 0.0, 30.0)
            ok, reason = run(provider.status())
            assert ok is want_ok, f"{label}: ok={ok}, expected {want_ok}"
            assert want_text in reason.lower(), f"{label}: reason was {reason!r}"
            if not ok:
                # An unusable backend must say what to do about it.
                assert "ollama" in reason.lower(), f"{label}: no remedy in {reason!r}"
            assert run(provider.available()) is want_ok
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]
    print(f"PASS  ollama status: {len(cases)} states distinguished, each with a remedy")


def test_sql_extraction_across_model_styles():
    """Different model families wrap SQL differently — all must parse.

    Found live: Qwen3 on Groq emits <think> blocks, so the app must not be tuned to a
    single model's output format.
    """
    from app.analytics.pipeline import _clean_sql
    want = "SELECT a FROM t"
    cases = {
        "bare": want,
        "markdown fence": f"```sql\n{want}\n```",
        "plain fence": f"```\n{want}\n```",
        "reasoning block": f"<think>\nLet me think about this.\n</think>\n{want}",
        "reasoning + fence": f"<think>reasoning</think>\n```sql\n{want}\n```",
        "unclosed think": f"Thinking about it...</think>\n{want}",
        "prose preamble": f"Here is the query you asked for:\n{want}",
        "trailing semicolon": f"{want};",
    }
    for label, raw in cases.items():
        got = _clean_sql(raw).rstrip(";")
        assert got == want, f"{label}: got {got!r}"
    # The refusal sentinel must survive untouched.
    assert _clean_sql("-- CANNOT_ANSWER: no such column").startswith("-- CANNOT_ANSWER:")
    print(f"PASS  SQL extraction: {len(cases)} model output styles + refusal sentinel")


def test_langchain_generator_parity():
    """The optional LangChain path must produce the SAME result as the native path.

    This is the point of the abstraction: the framework owns prompt assembly only —
    guardrails, execution and the retry loop are shared, so correctness cannot diverge.
    """
    try:
        from app.intelligence.llm.langchain_generator import LangChainSqlGenerator
    except ImportError:
        print("SKIP  langchain parity (langchain-core not installed)")
        return

    sql = "SELECT region, SUM(revenue) AS total_revenue FROM sales GROUP BY region ORDER BY total_revenue DESC"
    results = {}
    for label in ("native", "langchain"):
        engine, _ = build_engine()
        provider = ScriptedProvider([sql], summary="ok")
        gen = LangChainSqlGenerator(provider) if label == "langchain" else None
        res = run(answer_question(
            engine=engine, provider=provider, settings=Settings(),
            question="revenue by region", history=[], session_id="s1", sql_generator=gen,
        ))
        assert res.status == "ok", (label, res)
        results[label] = res

    assert results["native"].rows == results["langchain"].rows
    assert results["native"].sql == results["langchain"].sql
    assert results["native"].chart.type == results["langchain"].chart.type

    # The generator itself must report that it went through the LCEL chain.
    probe = ScriptedProvider(["SELECT 1"])
    out = run(LangChainSqlGenerator(probe).complete("sys", [{"role": "user", "content": "hi"}], 100))
    assert "langchain" in out.backend, out.backend
    assert out.text.strip() == "SELECT 1"
    assert out.tokens_used == 20, "token usage must survive the LangChain wrapper"
    print(f"PASS  langchain parity: identical rows/SQL/chart; generator reports {out.backend!r}")


def test_langchain_retry_loop_still_works():
    """Self-correction must work through the LangChain path too."""
    try:
        from app.intelligence.llm.langchain_generator import LangChainSqlGenerator
    except ImportError:
        print("SKIP  langchain retry (langchain-core not installed)")
        return
    engine, _ = build_engine()
    provider = ScriptedProvider([
        "SELECT SUM(nope) AS total FROM sales",
        "SELECT SUM(revenue) AS total_revenue FROM sales",
    ])
    res = run(answer_question(
        engine=engine, provider=provider, settings=Settings(),
        question="total revenue", history=[], session_id="s1",
        sql_generator=LangChainSqlGenerator(provider),
    ))
    assert res.status == "ok" and len(res.attempts) == 2
    assert res.rows[0]["total_revenue"] == 1125.75
    print("PASS  langchain path: self-correction loop intact")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
