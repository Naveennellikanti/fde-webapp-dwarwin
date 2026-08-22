"""Run the eval set and report accuracy.

    python evals/run_eval.py                  # against the configured backend
    python evals/run_eval.py --mock            # no model needed; CI uses this
    python evals/run_eval.py --json out.json   # machine-readable, for tracking over time

Why this exists: "the demo worked" is not a measure of whether text-to-SQL is correct.
A labelled set turns SQL accuracy into a number that can regress visibly — change a
prompt, rerun, see what it cost. Every expectation is computed in pandas from the same
fixtures, so the suite cannot drift into blessing a wrong answer.

The `--mock` path exercises the whole pipeline (guardrails, retries, chart selection,
validation) with scripted SQL instead of a model, which is what makes it usable in CI
with no API key. Accuracy of a *model* obviously requires a real one.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from app.config import Settings
from app.analytics.pipeline import Turn, answer_question
from app.ingestion.engine import DataEngine
from app.intelligence.llm.base import Completion, LLMProvider
from app.intelligence.llm.factory import get_provider
from app.validation.data_quality import profile_session
from evals.dataset import CASES, EvalCase, build_frames, to_csv_bytes, truth

REFUSAL_STATUSES = {"cannot_answer", "error"}


@dataclass
class CaseResult:
    id: str
    passed: bool
    status: str
    detail: str
    seconds: float
    attempts: int
    sql: str | None = None
    confidence: str | None = None


@dataclass
class EvalRun:
    results: list[CaseResult] = field(default_factory=list)
    backend: str = "unknown"

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def accuracy(self) -> float:
        return self.passed / len(self.results) if self.results else 0.0

    def by_category(self) -> dict[str, tuple[int, int]]:
        """Grouped by case-id prefix, so a systematic weakness stands out."""
        groups: dict[str, list[CaseResult]] = {}
        for r in self.results:
            key = "refusal" if r.id in _REFUSAL_IDS else r.id.split("_")[0]
            groups.setdefault(key, []).append(r)
        return {k: (sum(1 for r in v if r.passed), len(v)) for k, v in sorted(groups.items())}


_REFUSAL_IDS = {c.id for c in CASES if c.kind == "refusal"}


class MockProvider(LLMProvider):
    """Hand-written SQL per case: exercises the pipeline without a model.

    Cases with no entry fall through to a deliberate refusal, which is the honest
    behaviour for a provider that cannot answer.
    """
    name = "mock"

    SQL: dict[str, str] = {
        "total_revenue": 'SELECT SUM("revenue") AS total_revenue FROM "sales"',
        "avg_revenue": 'SELECT AVG("revenue") AS avg_revenue FROM "sales"',
        "order_count": 'SELECT COUNT(*) AS order_count FROM "sales"',
        "total_units": 'SELECT SUM("units") AS total_units FROM "sales"',
        "west_orders": 'SELECT COUNT(*) AS order_count FROM "sales" WHERE "region" = \'West\'',
        "revenue_by_region": (
            'SELECT "region", SUM("revenue") AS total_revenue FROM "sales" '
            'GROUP BY "region" ORDER BY total_revenue DESC'
        ),
        "best_product": (
            'SELECT "product", SUM("revenue") AS total_revenue FROM "sales" '
            'GROUP BY "product" ORDER BY total_revenue DESC LIMIT 1'
        ),
        "monthly_trend": (
            'SELECT date_trunc(\'month\', "order_date") AS month, '
            'SUM("revenue") AS total_revenue FROM "sales" GROUP BY month ORDER BY month'
        ),
        "top_rep_named": (
            'SELECT r."rep_name", SUM(s."revenue") AS total_revenue FROM "sales" s '
            'JOIN "reps" r ON s."rep_id" = r."rep_id" GROUP BY r."rep_name" '
            'ORDER BY total_revenue DESC LIMIT 1'
        ),
        "top_rep_amount": (
            'SELECT r."rep_name", SUM(s."revenue") AS total_revenue FROM "sales" s '
            'JOIN "reps" r ON s."rep_id" = r."rep_id" GROUP BY r."rep_name" '
            'ORDER BY total_revenue DESC LIMIT 1'
        ),
        "vs_target": (
            'SELECT s."region", SUM(s."revenue") AS actual, t."target", '
            'SUM(s."revenue") - t."target" AS variance FROM "sales" s '
            'JOIN "targets" t ON s."region" = t."region" '
            'GROUP BY s."region", t."target" ORDER BY s."region"'
        ),
        "over_target": (
            'SELECT COUNT(*) AS n FROM (SELECT s."region", SUM(s."revenue") rev, t."target" tgt '
            'FROM "sales" s JOIN "targets" t ON s."region" = t."region" '
            'GROUP BY s."region", t."target") WHERE rev > tgt'
        ),
    }

    def __init__(self) -> None:
        self.case_id = ""

    async def available(self) -> bool:
        return True

    async def complete(self, system, messages, max_tokens):  # noqa: ANN001
        if "explain analytical query results" in system:
            return Completion(text="Mock explanation.", tokens_used=5, backend="mock")
        sql = self.SQL.get(self.case_id)
        if sql is None:
            return Completion(
                text="-- CANNOT_ANSWER: not present in the schema",
                tokens_used=5, backend="mock",
            )
        return Completion(text=sql, tokens_used=20, backend="mock")


def _judge(case: EvalCase, res: Any, expected: dict[str, Any]) -> tuple[bool, str]:
    if case.kind == "refusal":
        if res.status in REFUSAL_STATUSES:
            return True, f"declined ({res.status})"
        return False, f"answered a question it should have declined (status={res.status})"

    if case.kind == "clarify":
        if res.status == "needs_clarification":
            return True, "asked for clarification"
        return False, f"expected a clarifying question, got {res.status}"

    if res.status != "ok":
        return False, f"status={res.status}: {res.answer[:90]}"
    if not res.rows:
        return False, "no rows returned"

    if case.chart_in and res.chart.type not in case.chart_in:
        return False, f"chart was {res.chart.type}, expected one of {sorted(case.chart_in)}"

    if case.check is not None:
        try:
            if not case.check(res.rows, expected):
                return False, f"wrong value: {str(res.rows[:2])[:140]}"
        except Exception as e:  # noqa: BLE001 - a malformed result is a failure, not a crash
            return False, f"could not evaluate result ({type(e).__name__}: {e})"
    return True, "correct"


async def run(mock: bool, only: str | None = None) -> EvalRun:
    frames = build_frames()
    expected = truth(frames)
    files = to_csv_bytes(frames)

    settings = Settings()
    provider: LLMProvider
    if mock:
        provider = MockProvider()
    else:
        provider = await get_provider(settings)

    engine = DataEngine.create()
    for name, data in files.items():
        engine.add_csv(name, data)
    quality = profile_session(engine)

    run_result = EvalRun(backend="mock" if mock else provider.name)
    cases = [c for c in CASES if not only or only in c.id]

    for case in cases:
        if isinstance(provider, MockProvider):
            provider.case_id = case.id
        t0 = time.perf_counter()
        try:
            res = await answer_question(
                engine=engine, provider=provider, settings=settings,
                question=case.question, history=[], session_id="eval", quality=quality,
            )
            ok, detail = _judge(case, res, expected)
            run_result.results.append(CaseResult(
                id=case.id, passed=ok, status=res.status, detail=detail,
                seconds=time.perf_counter() - t0, attempts=len(res.attempts),
                sql=res.sql, confidence=res.confidence,
            ))
        except Exception as e:  # noqa: BLE001
            run_result.results.append(CaseResult(
                id=case.id, passed=False, status="exception",
                detail=f"{type(e).__name__}: {e}", seconds=time.perf_counter() - t0,
                attempts=0,
            ))

    engine.close()
    return run_result


def report(run_result: EvalRun, verbose: bool) -> None:
    width = max(len(r.id) for r in run_result.results) + 1
    print(f"\nbackend: {run_result.backend}\n" + "-" * 74)
    for r in run_result.results:
        mark = "PASS" if r.passed else "FAIL"
        extra = f" [{r.attempts} attempt{'s' if r.attempts != 1 else ''}]" if r.attempts > 1 else ""
        conf = f" conf={r.confidence}" if r.confidence else ""
        print(f"{mark}  {r.id:<{width}} {r.seconds:5.1f}s{extra}{conf}  {r.detail}")
        if verbose and r.sql:
            print(f"        SQL: {' '.join(r.sql.split())[:160]}")

    print("-" * 74)
    for group, (ok, total) in run_result.by_category().items():
        bar = "#" * ok + "." * (total - ok)
        print(f"  {group:<18} {ok}/{total}  {bar}")
    print("-" * 74)
    print(f"accuracy: {run_result.passed}/{len(run_result.results)} "
          f"({run_result.accuracy * 100:.0f}%)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the Data Q&A eval set.")
    ap.add_argument("--mock", action="store_true",
                    help="use scripted SQL instead of a model (no API key needed)")
    ap.add_argument("--json", metavar="PATH", help="also write results as JSON")
    ap.add_argument("--only", metavar="SUBSTR", help="run only cases whose id contains SUBSTR")
    ap.add_argument("--verbose", action="store_true", help="print the SQL for each case")
    ap.add_argument("--min-accuracy", type=float, default=None,
                    help="exit non-zero below this accuracy (0-1). CI uses this as a gate.")
    args = ap.parse_args()

    result = asyncio.run(run(mock=args.mock, only=args.only))
    report(result, args.verbose)

    if args.json:
        Path(args.json).write_text(json.dumps({
            "backend": result.backend,
            "accuracy": result.accuracy,
            "passed": result.passed,
            "total": len(result.results),
            "cases": [
                {
                    "id": r.id, "passed": r.passed, "status": r.status, "detail": r.detail,
                    "seconds": round(r.seconds, 2), "attempts": r.attempts,
                    "confidence": r.confidence,
                }
                for r in result.results
            ],
        }, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    if args.min_accuracy is not None and result.accuracy < args.min_accuracy:
        print(f"\nFAILED GATE: accuracy {result.accuracy:.0%} < required {args.min_accuracy:.0%}")
        return 1
    return 0 if result.passed == len(result.results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
