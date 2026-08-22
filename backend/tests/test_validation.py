"""Tests for the validation and ambiguity layers.

These cover the checks that decide what a user is *told* about an answer, so the
failure mode they guard against is a confidently-presented wrong number — the thing
the whole app is built to avoid.

Run:  python tests/test_validation.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

import pandas as pd

from app.ingestion.engine import DataEngine
from app.intelligence import ambiguity_detector
from app.validation.confidence import score_answer
from app.validation.data_quality import profile_table, quality_notes_for_prompt
from app.validation.result_validator import ValidationReport, validate_result


def engine_from(frames: dict[str, pd.DataFrame]) -> DataEngine:
    e = DataEngine.create()
    for name, df in frames.items():
        e.add_csv(f"{name}.csv", df.to_csv(index=False).encode())
    return e


# ------------------------------------------------------------ data quality ------
def test_quality_finds_the_problems_that_corrupt_answers():
    df = pd.DataFrame({
        "order_id": range(1, 21),
        "region": ["West"] * 20,                      # constant
        "notes": [None] * 20,                         # all null
        "discount": [1.0, None] + [None] * 18,        # 95% null
        "revenue_text": [f"{i},000" for i in range(1, 19)] + ["N/A", ""],  # numeric-as-text
        "ref": [f"REF-{i:04d}" for i in range(20)],   # identifier-like
    })
    e = engine_from({"orders": df})
    report = profile_table(e, "orders")
    kinds = {i.kind for i in report.issues}

    for expected in ("constant", "all_null", "high_nulls", "numeric_stored_as_text", "identifier_like"):
        assert expected in kinds, f"missed {expected}; found {sorted(kinds)}"

    # Only the serious ones are worth prompt tokens.
    notes = quality_notes_for_prompt([report])
    assert "high_nulls" not in notes  # kinds are not leaked, messages are
    assert any(w in notes for w in ("empty", "text")), notes
    assert "constant" not in notes.lower() or "single value" in notes.lower()
    print(f"PASS  data quality: found {len(kinds)} issue kinds incl. {sorted(kinds)[:3]}")
    e.close()


def test_quality_does_not_call_dates_or_numeric_text_identifiers():
    """Two false positives found by running this on a real messy file.

    A date column is near-unique by nature and grouping by it is the whole point of a
    trend question, so calling it an identifier is advice against the most common
    question there is. And a numbers-stored-as-text column collected both findings;
    the specific one already says what to do.
    """
    df = pd.DataFrame({
        "order_date": pd.date_range("2024-01-01", periods=40, freq="D").strftime("%Y-%m-%d"),
        "amount_text": [f"{i},000" for i in range(1, 39)] + ["N/A", ""],
        "region": ["West", "East"] * 20,
    })
    e = engine_from({"t": df})
    report = profile_table(e, "t")
    flagged = {i.column for i in report.issues if i.kind == "identifier_like"}
    assert "order_date" not in flagged, "a date column is not an identifier"
    assert "amount_text" not in flagged, "numeric-as-text already has a better finding"
    assert any(i.kind == "numeric_stored_as_text" for i in report.issues)
    print("PASS  data quality: dates and numeric-text are not mislabelled as identifiers")
    e.close()


def test_quality_flags_duplicate_rows():
    df = pd.DataFrame({"a": [1, 1, 2, 3], "b": ["x", "x", "y", "z"]})
    e = engine_from({"t": df})
    report = profile_table(e, "t")
    assert report.duplicate_rows == 1, report.duplicate_rows
    assert any(i.kind == "duplicate_rows" for i in report.issues)
    print("PASS  data quality: duplicate rows counted (1 of 4)")
    e.close()


def test_quality_is_quiet_on_clean_data():
    """A clean file must not produce noise, or the warnings stop meaning anything."""
    df = pd.DataFrame({
        "order_id": range(1, 51),
        "region": ["West", "East"] * 25,
        "revenue": [100.0 + i for i in range(50)],
    })
    e = engine_from({"clean": df})
    report = profile_table(e, "clean")
    assert report.warnings == [], [i.message for i in report.warnings]
    assert quality_notes_for_prompt([report]) == ""
    print("PASS  data quality: clean data produces no warnings")
    e.close()


# -------------------------------------------------------- result validation -----
def test_empty_result_with_filter_is_explained():
    r = validate_result(
        question="revenue for region Westt", sql="SELECT SUM(revenue) FROM s WHERE region='Westt'",
        columns=["x"], rows=[],
    )
    kinds = {c.kind for c in r.caveats}
    assert "empty_filtered" in kinds, kinds
    print("PASS  result validation: empty filtered result blames the filter, not the data")


def test_average_over_sparse_column_is_flagged():
    df = pd.DataFrame({"discount": [1.0] + [None] * 19, "region": ["W"] * 20})
    e = engine_from({"t": df})
    quality = [profile_table(e, "t")]
    r = validate_result(
        question="average discount", sql='SELECT AVG("discount") AS a FROM "t"',
        columns=["a"], rows=[{"a": 1.0}], quality=quality,
    )
    assert any(c.kind == "aggregate_over_sparse_column" for c in r.caveats), r.caveats
    assert r.warnings, "should be a warning, not an aside"
    print("PASS  result validation: AVG over a 95%-empty column is flagged")
    e.close()


def test_top_n_short_and_negative_counts():
    r = validate_result(
        question="top 5 reps", sql="SELECT rep, SUM(x) FROM t GROUP BY rep LIMIT 5",
        columns=["rep", "total"], rows=[{"rep": "a", "total": 1}, {"rep": "b", "total": 2}],
    )
    assert any(c.kind == "fewer_rows_than_requested" for c in r.caveats), r.caveats

    r2 = validate_result(
        question="orders per region", sql="SELECT region, x AS order_count FROM t",
        columns=["region", "order_count"], rows=[{"region": "W", "order_count": -3}],
    )
    assert any(c.kind == "negative_count" for c in r2.caveats), r2.caveats
    print("PASS  result validation: short top-N and impossible counts both caught")


def test_clean_result_has_no_caveats():
    r = validate_result(
        question="total revenue by region",
        sql="SELECT region, SUM(revenue) AS total FROM s GROUP BY region",
        columns=["region", "total"],
        rows=[{"region": "W", "total": 1.0}, {"region": "E", "total": 2.0}],
    )
    assert r.caveats == [], [c.message for c in r.caveats]
    print("PASS  result validation: a clean result is reported clean")


# ---------------------------------------------------------------- confidence ----
def test_confidence_reflects_what_happened():
    clean = score_answer(attempts=1, validation=ValidationReport(), schema_was_narrowed=False,
                         row_count=4, used_join=False, status="ok")
    assert clean.level == "high", clean

    retried = score_answer(attempts=3, validation=ValidationReport(), schema_was_narrowed=False,
                           row_count=4, used_join=False, status="ok")
    assert retried.level in {"medium", "low"} and retried.score < clean.score

    warned = validate_result(question="q", sql="SELECT 1", columns=["a"], rows=[])
    with_warnings = score_answer(attempts=1, validation=warned, schema_was_narrowed=True,
                                 row_count=0, used_join=True, status="ok")
    assert with_warnings.level == "low", with_warnings

    failed = score_answer(attempts=1, validation=None, schema_was_narrowed=False,
                          row_count=0, used_join=False, status="cannot_answer")
    assert failed.level == "low" and failed.score == 0.0

    # Every level must carry reasons — a bare score invites false precision.
    for c in (clean, retried, with_warnings, failed):
        assert c.reasons, c
    print(f"PASS  confidence: clean={clean.level}({clean.score}) "
          f"retried={retried.level}({retried.score}) degraded={with_warnings.level}")


# ----------------------------------------------------------------- ambiguity ----
def test_superlative_without_measure_asks_when_several_apply():
    df = pd.DataFrame({"region": ["W"], "revenue": [1.0], "units": [2], "profit": [3.0]})
    e = engine_from({"sales": df})
    found = ambiguity_detector.detect("which region is best?", e)
    ask = ambiguity_detector.blocking(found)
    assert ask is not None, found
    assert len(ask.options) >= 2, ask.options
    print(f"PASS  ambiguity: 'best' with {len(ask.options)} measures asks -> {ask.options[:3]}")
    e.close()


def test_superlative_assumes_when_only_one_measure_exists():
    df = pd.DataFrame({"region": ["W"], "revenue": [1.0]})
    e = engine_from({"sales": df})
    found = ambiguity_detector.detect("which region is best?", e)
    assert ambiguity_detector.blocking(found) is None, "should assume, not interrogate"
    assert any(a.action == "assume" for a in found), found
    assert "revenue" in ambiguity_detector.prompt_addendum(found)
    print("PASS  ambiguity: one candidate measure -> answered with the assumption stated")
    e.close()


def test_specific_question_is_not_flagged():
    """The common case must stay silent, or the feature becomes an irritation."""
    df = pd.DataFrame({"region": ["W"], "revenue": [1.0], "units": [2]})
    e = engine_from({"sales": df})
    for q in ("total revenue by region", "which region has the highest revenue?",
              "how many units were sold in the West?"):
        found = ambiguity_detector.detect(q, e)
        assert ambiguity_detector.blocking(found) is None, (q, found)
    print("PASS  ambiguity: specific questions are not second-guessed")
    e.close()


def test_column_in_two_tables_is_surfaced():
    a = pd.DataFrame({"region": ["W"], "revenue": [1.0]})
    b = pd.DataFrame({"region": ["W"], "target": [5.0]})
    e = engine_from({"sales": a, "targets": b})
    found = ambiguity_detector.detect("revenue by region", e)
    assert any(x.kind == "column_in_multiple_tables" for x in found), found
    assert ambiguity_detector.blocking(found) is None, "ambiguous columns are assumed, not asked"
    print("PASS  ambiguity: a column present in two tables is reported as an assumption")
    e.close()


def test_relative_time_anchors_to_the_data():
    df = pd.DataFrame({"order_date": ["2024-01-01"], "revenue": [1.0]})
    e = engine_from({"sales": df})
    found = ambiguity_detector.detect("what were recent sales?", e)
    hint = ambiguity_detector.prompt_addendum(found)
    assert "MAX()" in hint and "current date" in hint, hint
    print("PASS  ambiguity: relative dates anchor to the data, not today")
    e.close()


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
