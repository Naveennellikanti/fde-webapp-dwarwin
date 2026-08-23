"""Multi-query investigation for open-ended questions.

"What is the total revenue?" is one query. "What needs my attention?" is not — an
analyst answers it by running several probes and reading them together: count the
errors, find the outliers, check what is recent, group by service. The single-query
pipeline structurally cannot do that, so it declined those questions entirely, which is
the one job a chatbot should do that a SQL console cannot.

This plans a small set of probes, runs each through the same guardrail and executor as
any other query, and synthesises findings from the results. Two properties matter:

*Bounded, not agentic.* Exactly two model calls — one to plan, one to synthesise —
regardless of how many probes run. There is no loop that decides to keep going, because
that is the shape that produces surprising bills and non-reproducible answers.

*Every claim carries its evidence.* A finding names the probe it came from, and that
probe's SQL and rows are returned alongside, so an assertion like "payment-svc accounts
for most errors" can be checked rather than believed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.analytics.query_validator import GuardrailError, validate_select
from app.config import Settings
from app.ingestion.engine import DataEngine
from app.intelligence.llm.base import LLMProvider

# Questions that ask for interpretation rather than a figure. Matched lexically and
# pre-LLM: classifying with a model call would cost a round trip on every question to
# answer something the wording already tells us.
_INVESTIGATIVE = re.compile(
    r"""\b(
        what(?:'s| is| are)?\s+(?:wrong|up|happening|going\s+on|interesting|notable|unusual)
      | needs?\s+(?:my\s+)?attention
      | should\s+i\s+(?:know|look|worry|care|be\s+concerned)
      | anything\s+(?:unusual|odd|wrong|concerning|interesting|notable)
      | (?:any\s+)?(?:insights?|anomalies|anomaly|outliers?|red\s+flags?|problems?|issues?)
      | give\s+me\s+(?:an?\s+)?(?:overview|summary|picture|sense)
      | (?:summar(?:ise|ize)|analyse|analyze|investigate|explore|assess|review)\s+
            (?:the\s+|this\s+|my\s+|these\s+)?(?:data|dataset|traces|file|files|table|tables)?
      | health\s+(?:check|of)
      | tell\s+me\s+about
      | what\s+stands?\s+out
      | deep\s*dive
    )\b""",
    re.X | re.I,
)


@dataclass
class Probe:
    """One question asked of the data, and what came back."""
    goal: str
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class Finding:
    headline: str
    detail: str
    severity: str            # "notable" | "watch" | "ok"
    evidence: int | None     # index into the probe list


@dataclass
class Investigation:
    findings: list[Finding] = field(default_factory=list)
    probes: list[Probe] = field(default_factory=list)
    tokens_used: int = 0
    backend: str | None = None
    # True when the model's synthesis could not be parsed and the findings below are
    # deterministic descriptions of each probe instead of conclusions drawn across them.
    synthesis_failed: bool = False


def looks_investigative(question: str) -> bool:
    return bool(_INVESTIGATIVE.search(question))


PLAN_SYSTEM = """You plan a short data investigation.

You are given a database schema and an open-ended question. Produce a small set of
independent SQL probes whose combined results would let an analyst answer it.

Rules:
1. Output ONLY a JSON array. No prose, no markdown fences.
2. Each element: {"goal": "<what this probe establishes, one short phrase>",
                  "sql": "<one DuckDB SELECT>"}
3. Between 3 and 5 probes. Fewer is better if fewer suffice.
4. Every probe must be a single read-only SELECT. CTEs are fine. Never INSERT/UPDATE/
   DELETE/DROP/CREATE/ATTACH/COPY/INSTALL/PRAGMA, and never read files.
5. Use ONLY tables and columns from the schema. Quote identifiers with double quotes.
6. Each probe must return few rows — aggregate, and LIMIT 20 or fewer. You are looking
   for shape and outliers, not for dumps.
7. Make the probes *different in kind*. Good sets cover: overall scale, a breakdown by
   the most meaningful category, extremes or outliers, error/severity levels where such
   a column exists, and recency where a date column exists.
8. Prefer probes that could surface a problem. "Which category has the most failures"
   is more useful than "how many rows are there".
9. For recency, anchor to the data: compare against MAX() of the date column, never
   against CURRENT_TIMESTAMP or NOW(). Uploaded files are usually historical, so a
   probe filtered on the wall clock silently returns nothing.
"""

SYNTHESIS_SYSTEM = """You report findings from a completed data investigation.

You are given the user's question and the RESULTS of several SQL probes that have
already run. Report what the results actually show.

Rules:
1. Output ONLY a JSON array. No prose, no markdown fences.
2. Each element: {"headline": "<one sentence, the finding itself>",
                  "detail": "<ONE short sentence of specifics — keep it brief>",
                  "severity": "notable" | "watch" | "ok",
                  "evidence": <probe number the finding comes from>}
3. Use ONLY numbers present in the probe results. Never recompute, never estimate,
   never carry a figure over from your own knowledge.
4. Between 2 and 5 findings, most important first.
5. "watch" means a reader should act or look closer. "notable" means it is worth
   knowing. "ok" means the probe showed nothing wrong — say so plainly rather than
   manufacturing concern.
6. Be specific. "api-gateway-api-gw-01 has 15 traces, three times the median" is a
   finding; "some CIs have more traces" is not.
7. If the probes genuinely show nothing of interest, return a single "ok" finding
   saying that. Do not invent problems to look useful.
8. Keep the whole array compact. Three tight findings are better than five verbose ones,
   and an over-long response gets cut off before it can be read.
"""


def _extract_json_array(text: str) -> list[dict[str, Any]]:
    """Pull a JSON array out of a model response, tolerating fences and truncation.

    Truncation is the common failure, not malformed syntax: a plan of five probes with
    verbose SQL can exceed the token budget, and then the array is cut mid-string.
    Discarding the whole response for that loses four perfectly good probes, so the
    complete objects are salvaged individually. Raising the budget alone would not fix
    this — any budget can be exceeded by a wordier plan.
    """
    text = (text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fence:
        text = fence.group(1).strip()

    start = text.find("[")
    if start == -1:
        return []
    end = text.rfind("]")
    if end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass  # fall through to salvage

    # Salvage: walk the array and decode each balanced {...} on its own.
    return _salvage_objects(text[start + 1 :])


def _salvage_objects(body: str) -> list[dict[str, Any]]:
    """Decode every complete JSON object in a fragment, ignoring a trailing partial."""
    out: list[dict[str, Any]] = []
    depth = 0
    in_string = False
    escaped = False
    obj_start = -1

    for i, ch in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start >= 0:
                try:
                    parsed = json.loads(body[obj_start : i + 1])
                    if isinstance(parsed, dict):
                        out.append(parsed)
                except json.JSONDecodeError:
                    pass
                obj_start = -1
    return out


async def investigate(
    *,
    engine: DataEngine,
    provider: LLMProvider,
    settings: Settings,
    question: str,
    schema_text: str,
    quality_notes: str = "",
) -> Investigation:
    result = Investigation()

    # ---- 1. Plan (one model call) --------------------------------------------
    plan_prompt = f"SCHEMA:\n{schema_text}\n"
    if quality_notes:
        plan_prompt += f"\n{quality_notes}\n"
    plan_prompt += f"\nQUESTION: {question}\n\nJSON:"

    completion = await provider.complete(
        PLAN_SYSTEM,
        [{"role": "user", "content": plan_prompt}],
        settings.investigation_plan_tokens,
    )
    result.tokens_used += completion.tokens_used
    result.backend = completion.backend

    planned = _extract_json_array(completion.text)[: settings.max_investigation_probes]
    if not planned:
        return result  # caller falls back to the single-query path

    # ---- 2. Execute every probe through the normal safety path ---------------
    # No retry loop here: a probe that fails is reported as failed and the
    # investigation continues. One bad probe should not cost three more model calls.
    for item in planned:
        goal = str(item.get("goal") or "").strip() or "unnamed probe"
        raw = str(item.get("sql") or "").strip()
        if not raw:
            continue
        probe = Probe(goal=goal, sql=raw)
        try:
            probe.sql = validate_select(raw)
        except GuardrailError as e:
            probe.error = f"blocked by safety check: {e}"
            result.probes.append(probe)
            continue
        try:
            cols, rows, _truncated = engine.run_select(
                probe.sql, settings.investigation_probe_rows
            )
            probe.columns, probe.rows = cols, rows
        except Exception as e:  # noqa: BLE001 - a failed probe is data, not a crash
            probe.error = str(e).strip().splitlines()[0][:200]
        result.probes.append(probe)

    if not any(p.ok and p.rows for p in result.probes):
        return result

    # ---- 3. Synthesise (one model call) --------------------------------------
    lines: list[str] = []
    for i, p in enumerate(result.probes):
        if not p.ok:
            continue
        lines.append(f"PROBE {i}: {p.goal}")
        lines.append(f"  sql: {' '.join(p.sql.split())}")
        lines.append(f"  rows: {json.dumps(p.rows[: settings.investigation_synthesis_rows], default=str)}")
    synth_prompt = f"QUESTION: {question}\n\n" + "\n".join(lines) + "\n\nJSON:"

    synth = await provider.complete(
        SYNTHESIS_SYSTEM,
        [{"role": "user", "content": synth_prompt}],
        settings.investigation_synthesis_tokens,
    )
    result.tokens_used += synth.tokens_used

    for item in _extract_json_array(synth.text):
        headline = str(item.get("headline") or "").strip()
        if not headline:
            continue
        severity = str(item.get("severity") or "notable").lower()
        if severity not in {"notable", "watch", "ok"}:
            severity = "notable"
        ev = item.get("evidence")
        evidence = ev if isinstance(ev, int) and 0 <= ev < len(result.probes) else None
        result.findings.append(
            Finding(
                headline=headline,
                detail=str(item.get("detail") or "").strip(),
                severity=severity,
                evidence=evidence,
            )
        )

    # Synthesis is the one step here that is not deterministic, and it occasionally
    # returns nothing parseable. Falling back to the single-query path in that case is
    # the wrong failure: the user asked an open question, gets a narrow answer to a
    # different one, and has no way to tell that five probes ran and were discarded.
    # Reporting the probes with a deterministic description keeps the work visible.
    if not result.findings:
        result.findings = _findings_from_probes(result.probes)
        result.synthesis_failed = True

    return result


def _findings_from_probes(probes: list[Probe]) -> list[Finding]:
    """Describe each successful probe from its own rows, with no model involved.

    Weaker than real synthesis — these are observations, not conclusions — but every
    figure is read straight off the result, so it is safe to show and still answers
    "what did you look at, and what did you see".
    """
    from app.validation.summary_validator import deterministic_summary

    findings: list[Finding] = []
    for i, p in enumerate(probes):
        if not p.ok or not p.rows:
            continue
        findings.append(
            Finding(
                headline=p.goal[:1].upper() + p.goal[1:] if p.goal else f"Probe {i}",
                detail=deterministic_summary(p.columns, p.rows, limit=4),
                severity="notable",
                evidence=i,
            )
        )
    return findings


def all_probe_rows(probes: list[Probe]) -> list[dict[str, Any]]:
    """Every returned row, for checking that findings only quote real numbers."""
    out: list[dict[str, Any]] = []
    for p in probes:
        if p.ok:
            out.extend(p.rows)
    return out
