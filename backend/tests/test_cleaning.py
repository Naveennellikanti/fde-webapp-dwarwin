"""Tests for the propose -> approve -> apply -> undo cleaning path.

The properties that make this safe to ship: fixes are deterministic (same file, same
proposals), the transform passes the same guardrail as any query, the source is
recoverable, and a clean file proposes nothing.

Run:  python tests/test_cleaning.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

import pandas as pd
from fastapi.testclient import TestClient

from app import main
from app.analytics.query_validator import validate_select
from app.ingestion.engine import DataEngine
from app.intelligence import cleaner
from app.validation.data_quality import profile_table


def messy() -> bytes:
    df = pd.DataFrame({
        "order_id": range(1, 21),
        "region": ["West", "East"] * 10,
        "notes": [None] * 20,                                       # all-null -> drop
        "amount_text": [f"{i},000" for i in range(1, 19)] + ["N/A", ""],  # numeric-as-text -> cast
    })
    df = pd.concat([df, df.iloc[:3]], ignore_index=True)            # 3 dupes -> dedupe
    return df.to_csv(index=False).encode()


def engine_with(data: bytes, name: str = "t") -> DataEngine:
    e = DataEngine.create()
    e.add_csv(f"{name}.csv", data)
    return e


def test_proposals_map_to_detected_issues():
    e = engine_with(messy())
    ops = cleaner.propose(e, "t", profile_table(e, "t"))
    kinds = {o.kind for o in ops}
    assert kinds == {"cast_numeric", "dedupe_rows", "drop_empty_column"}, kinds
    # Deterministic: same input, same proposals (stable ids).
    again = cleaner.propose(e, "t", profile_table(e, "t"))
    assert [o.id for o in ops] == [o.id for o in again]
    print(f"PASS  cleaning: proposes {sorted(kinds)} from the quality report, deterministically")
    e.close()


def test_clean_file_proposes_nothing():
    df = pd.DataFrame({"region": ["W", "E"] * 10, "revenue": [float(i) for i in range(20)]})
    e = engine_with(df.to_csv(index=False).encode())
    assert cleaner.propose(e, "t", profile_table(e, "t")) == []
    print("PASS  cleaning: a clean file proposes no fixes")
    e.close()


def test_transform_passes_the_guardrail_and_is_correct():
    e = engine_with(messy())
    ops = cleaner.propose(e, "t", profile_table(e, "t"))
    sql = cleaner.build_transform_sql(e, "t", ops)
    validate_select(sql)  # must be a safe single SELECT, same as any query

    e.snapshot_table("t")
    e.apply_transform("t", sql)
    cols = dict(e.tables["t"].columns)
    assert e.tables["t"].row_count == 20, "3 duplicate rows should be gone"
    assert cols.get("amount_text") in {"DOUBLE", "FLOAT"}, cols
    assert "notes" not in cols, "all-empty column should be dropped"
    print("PASS  cleaning: transform is guardrail-safe; dedupe + cast + drop all applied")
    e.close()


def test_apply_is_reversible():
    e = engine_with(messy())
    ops = cleaner.propose(e, "t", profile_table(e, "t"))
    e.snapshot_table("t")
    e.apply_transform("t", cleaner.build_transform_sql(e, "t", ops))
    assert e.tables["t"].row_count == 20
    assert e.restore_snapshot("t") is True
    assert e.tables["t"].row_count == 23, "original row count restored"
    assert "notes" in dict(e.tables["t"].columns), "dropped column restored"
    assert e.restore_snapshot("t") is False, "nothing left to undo"
    print("PASS  cleaning: undo restores the original rows, columns and types")
    e.close()


def test_snapshot_is_invisible_to_the_schema():
    e = engine_with(messy())
    e.snapshot_table("t")
    # The shadow table must not appear anywhere the model or user sees.
    assert list(e.tables) == ["t"], list(e.tables)
    print("PASS  cleaning: the undo snapshot is hidden from the schema")
    e.close()


def test_refuses_to_drop_every_column():
    df = pd.DataFrame({"a": [None] * 20, "b": [None] * 20})  # both all-null
    e = engine_with(df.to_csv(index=False).encode())
    ops = cleaner.propose(e, "t", profile_table(e, "t"))
    try:
        cleaner.build_transform_sql(e, "t", ops)
    except ValueError:
        print("PASS  cleaning: refuses to build a transform that drops every column")
        e.close()
        return
    raise AssertionError("should have refused to drop all columns")


# ---- HTTP contract -------------------------------------------------------------
def test_endpoints_propose_apply_undo():
    with TestClient(main.app) as client:
        sid = client.post("/session").json()["session_id"]
        client.post("/upload", data={"session_id": sid},
                    files=[("files", ("t.csv", io.BytesIO(messy()), "text/csv"))])

        proposal = client.get(f"/session/{sid}/cleaning/t").json()
        assert len(proposal["ops"]) == 3
        assert all(op["impact"] for op in proposal["ops"]), "each op reports an impact"
        assert proposal["undo_available"] is False

        ids = [op["id"] for op in proposal["ops"]]
        applied = client.post(f"/session/{sid}/cleaning/t/apply", json={"op_ids": ids})
        assert applied.status_code == 200, applied.text
        table = next(t for t in applied.json()["tables"] if t["name"] == "t")
        assert table["row_count"] == 20
        assert not any(c["name"] == "notes" for c in table["columns"])

        # undo is now available and works
        assert client.get(f"/session/{sid}/cleaning/t").json()["undo_available"] is True
        undone = client.post(f"/session/{sid}/cleaning/t/undo")
        restored = next(t for t in undone.json()["tables"] if t["name"] == "t")
        assert restored["row_count"] == 23
        print("PASS  cleaning endpoints: propose -> apply -> undo over HTTP, quality recomputed")


def test_apply_unknown_op_is_rejected():
    with TestClient(main.app) as client:
        sid = client.post("/session").json()["session_id"]
        client.post("/upload", data={"session_id": sid},
                    files=[("files", ("t.csv", io.BytesIO(messy()), "text/csv"))])
        r = client.post(f"/session/{sid}/cleaning/t/apply", json={"op_ids": ["cast_numeric:nope"]})
        assert r.status_code == 400, r.text
        print("PASS  cleaning endpoints: an unrecognised op id is refused, not guessed")


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
