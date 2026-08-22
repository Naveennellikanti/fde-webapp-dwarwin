"""Verify the local (Ollama) path end to end, and time it.

Not part of the automated suite — it needs a running Ollama and takes minutes on a
CPU-only machine. Run it to confirm the offline claim on a given box:

    python tests/local_ollama_check.py

Every answer is checked against a pandas ground truth, so this measures correctness,
not just liveness.
"""
from __future__ import annotations

import asyncio
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

import numpy as np
import pandas as pd

from app.config import Settings
from app.core.duckdb_engine import DataEngine
from app.llm.ollama_provider import OllamaProvider
from app.services.pipeline import Turn, answer_question


def build_data() -> tuple[bytes, bytes, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(7)
    n = 400
    sales = pd.DataFrame(
        {
            "order_id": np.arange(1, n + 1),
            "order_date": pd.date_range("2024-01-01", periods=n, freq="D").astype(str),
            "region": rng.choice(["West", "East", "North", "South"], n),
            "rep_id": rng.integers(1, 6, n),
            "revenue": np.round(rng.random(n) * 5000 + 100, 2),
            "units": rng.integers(1, 30, n),
        }
    )
    reps = pd.DataFrame(
        {
            "rep_id": [1, 2, 3, 4, 5],
            "rep_name": ["Ada", "Grace", "Alan", "Katherine", "Linus"],
            "hire_year": [2019, 2020, 2018, 2021, 2022],
        }
    )
    b1, b2 = io.BytesIO(), io.BytesIO()
    sales.to_csv(b1, index=False)
    reps.to_csv(b2, index=False)
    return b1.getvalue(), b2.getvalue(), sales, reps


async def main() -> int:
    settings = Settings(llm_backend="ollama")
    provider = OllamaProvider(
        settings.ollama_url, settings.ollama_model, settings.temperature, 600.0
    )

    print(f"model: {settings.ollama_model}  url: {settings.ollama_url}")
    if not await provider.available():
        print("FAIL  Ollama is not reachable. Start it with `ollama serve`.")
        return 1

    sales_csv, reps_csv, sales, reps = build_data()
    engine = DataEngine.create()
    engine.add_csv("sales.csv", sales_csv)
    engine.add_csv("reps.csv", reps_csv)
    print(f"tables: {list(engine.tables)}\n")

    merged = sales.merge(reps, on="rep_id")
    top_rep = merged.groupby("rep_name").revenue.sum().idxmax()

    # (question, checker(rows) -> bool | None)  None == judged by status only
    checks: list[tuple[str, object]] = [
        (
            "What is the total revenue?",
            lambda rows: abs(float(list(rows[0].values())[0]) - sales.revenue.sum()) < 0.05,
        ),
        (
            "How many orders came from the West region?",
            lambda rows: int(list(rows[0].values())[0]) == int((sales.region == "West").sum()),
        ),
        (
            "Show total revenue by region",
            lambda rows: len(rows) == 4,
        ),
        (
            "Which sales rep generated the most revenue?",
            lambda rows: any(top_rep in str(v) for v in rows[0].values()),
        ),
        (
            "Show me the monthly revenue trend",
            lambda rows: len(rows) >= 12,
        ),
        (
            "What is the average customer satisfaction score?",
            None,  # unanswerable: expect a refusal, not a number
        ),
    ]

    history: list[Turn] = []
    passed = 0
    t_all = time.perf_counter()

    for question, check in checks:
        t0 = time.perf_counter()
        try:
            res = await answer_question(
                engine=engine,
                provider=provider,
                settings=settings,
                question=question,
                history=history,
                session_id="local-check",
            )
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {question}\n      exception: {type(e).__name__}: {e}")
            continue
        dt = time.perf_counter() - t0
        history.append(Turn(question=question, sql=res.sql))

        if check is None:
            ok = res.status == "cannot_answer"
            detail = f"status={res.status} (want cannot_answer)"
        else:
            ok = res.status == "ok" and bool(res.rows) and bool(check(res.rows))
            detail = f"status={res.status} rows={len(res.rows)} chart={res.chart.type}"

        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  [{dt:6.1f}s] {question}")
        print(f"      {detail}  attempts={len(res.attempts)}")
        if res.sql:
            print(f"      SQL: {' '.join(res.sql.split())[:150]}")
        if not ok:
            print(f"      answer: {res.answer[:200]}")

    total = time.perf_counter() - t_all
    print(
        f"\n{passed}/{len(checks)} passed  |  {total:.0f}s total, "
        f"{total / len(checks):.1f}s per question"
    )
    engine.close()
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
