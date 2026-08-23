"""Tests for multi-query investigation.

The properties that matter are the ones that separate this from an agent that wanders:
it is bounded (exactly two model calls), every probe goes through the same guardrail as
any query, findings that quote invented numbers are dropped, and a failed synthesis
degrades to something honest rather than to a different question's answer.

Run:  python tests/test_investigator.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

import pandas as pd

from app.config import Settings
from app.ingestion.engine import DataEngine
from app.intelligence import investigator as I
from app.intelligence.llm.base import Completion, LLMProvider


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def engine() -> DataEngine:
    df = pd.DataFrame({
        "ci_name": ["gw-01"] * 15 + ["pay-01"] * 25 + ["cart-01"] * 10,
        "levels": (["ERROR"] * 5 + ["INFO"] * 10) + (["ERROR"] * 20 + ["WARN"] * 5) + ["INFO"] * 10,
        "num_spans": list(range(50)),
    })
    e = DataEngine.create()
    e.add_csv("traces.csv", df.to_csv(index=False).encode())
    return e


class ScriptedProvider(LLMProvider):
    """Returns a fixed plan then a fixed synthesis, so probe execution is exercised
    without a real model. Plan/synthesis are chosen by which system prompt arrives."""
    name = "mock"

    def __init__(self, plan: list[dict], synthesis: list[dict] | str):
        self._plan = json.dumps(plan)
        self._synthesis = synthesis if isinstance(synthesis, str) else json.dumps(synthesis)
        self.calls = 0

    async def available(self) -> bool:
        return True

    async def complete(self, system, messages, max_tokens):  # noqa: ANN001
        self.calls += 1
        if "plan a short data investigation" in system.lower():
            return Completion(text=self._plan, tokens_used=100, backend="mock")
        return Completion(text=self._synthesis, tokens_used=80, backend="mock")


# ---- routing -------------------------------------------------------------------
def test_routing_separates_open_from_specific():
    open_q = [
        "what needs my attention?", "anything unusual here?", "give me an overview",
        "what's wrong with this data", "any red flags?", "summarise the traces",
    ]
    specific_q = [
        "total revenue", "how many errors from gw-01", "revenue by region",
        "top 5 services by span count", "average num_spans",
    ]
    for q in open_q:
        assert I.looks_investigative(q), f"missed open-ended: {q!r}"
    for q in specific_q:
        assert not I.looks_investigative(q), f"false positive: {q!r}"
    print(f"PASS  routing: {len(open_q)} open + {len(specific_q)} specific, all correct")


# ---- bounded ------------------------------------------------------------------
def test_exactly_two_model_calls_regardless_of_probes():
    e = engine()
    prov = ScriptedProvider(
        plan=[
            {"goal": "errors by ci", "sql": 'SELECT ci_name, COUNT(*) c FROM traces GROUP BY ci_name'},
            {"goal": "levels", "sql": 'SELECT levels, COUNT(*) c FROM traces GROUP BY levels'},
            {"goal": "spans", "sql": 'SELECT MAX(num_spans) m FROM traces'},
        ],
        synthesis=[{"headline": "pay-01 has the most rows", "detail": "25 rows", "severity": "watch", "evidence": 0}],
    )
    inv = run(I.investigate(engine=e, provider=prov, settings=Settings(),
                            question="what needs attention?", schema_text="TABLE traces(...)"))
    assert prov.calls == 2, f"expected 2 model calls, got {prov.calls}"
    assert len(inv.probes) == 3 and all(p.ok for p in inv.probes)
    assert len(inv.findings) == 1
    print(f"PASS  bounded: {len(inv.probes)} probes ran on exactly {prov.calls} model calls")
    e.close()


def test_probe_count_is_capped():
    e = engine()
    plan = [{"goal": f"probe {i}", "sql": "SELECT COUNT(*) c FROM traces"} for i in range(12)]
    prov = ScriptedProvider(plan=plan, synthesis=[{"headline": "x", "detail": "", "severity": "ok", "evidence": 0}])
    s = Settings()
    inv = run(I.investigate(engine=e, provider=prov, settings=s,
                            question="overview", schema_text="TABLE traces(...)"))
    assert len(inv.probes) <= s.max_investigation_probes, len(inv.probes)
    print(f"PASS  cap: 12 planned -> {len(inv.probes)} run (limit {s.max_investigation_probes})")
    e.close()


# ---- safety -------------------------------------------------------------------
def test_probes_go_through_the_guardrail():
    e = engine()
    prov = ScriptedProvider(
        plan=[
            {"goal": "safe", "sql": "SELECT COUNT(*) c FROM traces"},
            {"goal": "destructive", "sql": "DROP TABLE traces"},
            {"goal": "exfiltration", "sql": "SELECT * FROM read_csv_auto('/etc/passwd')"},
        ],
        synthesis=[{"headline": "one probe worked", "detail": "", "severity": "ok", "evidence": 0}],
    )
    inv = run(I.investigate(engine=e, provider=prov, settings=Settings(),
                            question="what's up?", schema_text="TABLE traces(...)"))
    by_goal = {p.goal: p for p in inv.probes}
    assert by_goal["safe"].ok
    assert not by_goal["destructive"].ok and "safety" in (by_goal["destructive"].error or "")
    assert not by_goal["exfiltration"].ok
    print("PASS  safety: destructive and filesystem probes blocked, safe one ran")
    e.close()


# ---- honesty ------------------------------------------------------------------
def test_synthesis_failure_degrades_to_probe_descriptions():
    e = engine()
    prov = ScriptedProvider(
        plan=[{"goal": "levels breakdown", "sql": "SELECT levels, COUNT(*) c FROM traces GROUP BY levels"}],
        synthesis="not json at all, the model rambled",
    )
    inv = run(I.investigate(engine=e, provider=prov, settings=Settings(),
                            question="overview", schema_text="TABLE traces(...)"))
    assert inv.synthesis_failed is True
    assert inv.findings, "must still produce findings from the probe rows"
    # The fallback finding describes the probe it came from.
    assert inv.findings[0].evidence == 0
    print("PASS  honesty: unparseable synthesis falls back to probe descriptions, flagged")
    e.close()


def test_planning_failure_returns_no_findings():
    """A plan that yields nothing must return empty, so the pipeline can fall back."""
    e = engine()
    prov = ScriptedProvider(plan=[], synthesis=[])
    inv = run(I.investigate(engine=e, provider=prov, settings=Settings(),
                            question="overview", schema_text="TABLE traces(...)"))
    assert inv.findings == [] and inv.probes == []
    print("PASS  planning failure: empty investigation, caller can fall back")
    e.close()


# ---- salvage ------------------------------------------------------------------
def test_truncated_plan_is_salvaged():
    """The real bug: a plan cut off mid-string still yields its complete probes."""
    good = '{"goal": "a", "sql": "SELECT 1"}'
    truncated = f'[\n  {good},\n  {good},\n  {{"goal": "cut", "sql": "SELECT quantile('
    objs = I._extract_json_array(truncated)
    assert len(objs) == 2, f"expected 2 salvaged, got {len(objs)}"

    # Well-formed input still parses whole.
    whole = f"[{good},{good},{good}]"
    assert len(I._extract_json_array(whole)) == 3
    print("PASS  salvage: 2 recovered from a truncated plan, 3 from a whole one")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
