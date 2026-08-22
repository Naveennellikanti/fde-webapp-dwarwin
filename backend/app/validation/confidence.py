"""A confidence signal for an answer, derived from what actually happened.

This is not the model's opinion of itself — models are poorly calibrated about their own
output, and asking for a self-rating costs a round trip to get a number that means very
little. Every input here is an observed fact about how the answer was produced: how many
attempts the SQL took, whether the schema was narrowed, whether validation raised
caveats, how much of the data the question touched.

The point is to be *legible*. A score alone invites false precision, so the reasons are
carried alongside it and shown in the UI: "high, 1 attempt, no caveats" is a claim the
user can check, where "0.87" is not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.validation.result_validator import ValidationReport

Level = Literal["high", "medium", "low"]


@dataclass
class Confidence:
    level: Level
    score: float  # 0..1, exposed mainly for sorting and tests
    reasons: list[str] = field(default_factory=list)


def score_answer(
    *,
    attempts: int,
    validation: ValidationReport | None,
    schema_was_narrowed: bool,
    row_count: int,
    used_join: bool,
    status: str,
) -> Confidence:
    """Combine observations into a level. Deliberately coarse: three buckets, not a percentage."""
    if status != "ok":
        return Confidence("low", 0.0, ["The question could not be answered from this data."])

    score = 1.0
    reasons: list[str] = []

    # Retries mean the first SQL was wrong. It was corrected, but the model's grasp of
    # the schema was evidently imperfect, and that is worth surfacing.
    if attempts >= 3:
        score -= 0.40
        reasons.append(f"took {attempts} attempts to produce runnable SQL")
    elif attempts == 2:
        score -= 0.20
        reasons.append("first attempt failed and was corrected")
    else:
        reasons.append("SQL ran first time")

    warnings = validation.warnings if validation else []
    infos = [c for c in (validation.caveats if validation else []) if c.severity == "info"]
    if warnings:
        score -= 0.25 * min(len(warnings), 2)
        reasons.append(
            f"{len(warnings)} data caveat{'s' if len(warnings) > 1 else ''} on the result"
        )
    elif infos:
        score -= 0.05
    else:
        reasons.append("no caveats on the result")

    # A narrowed schema means the model did not see every table, so a relevant one may
    # have been left out of consideration entirely.
    if schema_was_narrowed:
        score -= 0.10
        reasons.append("only the tables judged relevant were shown to the model")

    # Joins rest on inferred relationships rather than declared foreign keys.
    if used_join:
        score -= 0.05
        reasons.append("relies on a detected relationship between files")

    if row_count == 0:
        score -= 0.30
        reasons.append("no rows returned")

    score = max(0.0, min(1.0, score))
    level: Level = "high" if score >= 0.8 else "medium" if score >= 0.5 else "low"
    return Confidence(level, round(score, 2), reasons)
