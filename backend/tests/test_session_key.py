"""HTTP-level tests for the bring-your-own-key path.

The security properties live in the API contract, not in a helper, so these drive the
real app through FastAPI's TestClient:

  - a key is never echoed back by any endpoint
  - one session's key is invisible to another session
  - a key that the provider rejects is not stored
  - clearing works, and falls back to the server environment

Run:  python tests/test_session_key.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from fastapi.testclient import TestClient

from app import main
from app.intelligence.llm.groq_provider import GroqProvider

FAKE_KEY = "gsk_test_key_that_must_never_be_echoed_0123456789"
CSV = b"region,revenue\nWest,100.5\nEast,200.25\n"
REGIONS_CSV = b"region,head\nWest,Ann\nEast,Bo\n"


def _accept_any_key(monkey: bool) -> None:
    """Make key verification deterministic — no network in tests.

    Patches `verify_key`, which is what the endpoint calls. An earlier version of this
    helper patched `available()` instead, and so passed against an endpoint that was
    not verifying anything: `available()` only reports whether a key is configured.
    """
    async def result(self) -> bool:  # noqa: ANN001
        return monkey
    GroqProvider.verify_key = result  # type: ignore[method-assign]


def new_session(client: TestClient) -> str:
    sid = client.post("/session").json()["session_id"]
    client.post(
        "/upload",
        data={"session_id": sid},
        files=[("files", ("sales.csv", io.BytesIO(CSV), "text/csv"))],
    )
    return sid


def test_key_is_never_echoed() -> None:
    _accept_any_key(True)
    with TestClient(main.app) as client:
        sid = new_session(client)

        r = client.put(f"/session/{sid}/key", json={"api_key": FAKE_KEY})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["has_key"] is True
        assert body.get("verified") is True

        # No endpoint may contain the key, anywhere in its serialised body.
        for label, resp in {
            "PUT /key": r,
            "GET /config": client.get("/config"),
            "GET /schema": client.get(f"/schema/{sid}"),
        }.items():
            assert FAKE_KEY not in resp.text, f"{label} leaked the key"
            assert "api_key" not in resp.text, f"{label} exposed an api_key field"

        print("PASS  key never echoed by PUT /key, /config or /schema")


def test_key_does_not_leak_across_sessions() -> None:
    _accept_any_key(True)
    with TestClient(main.app) as client:
        a = new_session(client)
        b = new_session(client)
        client.put(f"/session/{a}/key", json={"api_key": FAKE_KEY})

        # Session B never had a key set.
        rb = client.delete(f"/session/{b}/key")
        assert rb.json()["has_key"] is False, "session B saw session A's key"

        # And A still has its own.
        session_a = main.store.get(a)
        session_b = main.store.get(b)
        assert session_a is not None and session_b is not None
        assert session_a.api_key == FAKE_KEY
        assert session_b.api_key is None
        print("PASS  a session key is invisible to other sessions")


def test_rejected_key_is_not_stored() -> None:
    _accept_any_key(False)  # provider rejects everything
    with TestClient(main.app) as client:
        sid = new_session(client)
        r = client.put(f"/session/{sid}/key", json={"api_key": "gsk_bogus"})
        assert r.status_code == 400, r.text
        assert FAKE_KEY not in r.text
        session = main.store.get(sid)
        assert session is not None and session.api_key is None, "a rejected key was stored"
        print("PASS  a key the provider rejects is verified, refused and not stored")


def test_clearing_restores_server_config() -> None:
    _accept_any_key(True)
    with TestClient(main.app) as client:
        sid = new_session(client)
        client.put(f"/session/{sid}/key", json={"api_key": FAKE_KEY})
        assert main.store.get(sid).api_key == FAKE_KEY  # type: ignore[union-attr]

        r = client.delete(f"/session/{sid}/key")
        assert r.status_code == 200
        assert r.json()["has_key"] is False
        assert main.store.get(sid).api_key is None  # type: ignore[union-attr]

        # An empty value clears it too, without erroring.
        client.put(f"/session/{sid}/key", json={"api_key": FAKE_KEY})
        r = client.put(f"/session/{sid}/key", json={"api_key": "   "})
        assert r.json()["has_key"] is False
        print("PASS  clearing a key works, via DELETE and via an empty value")


def test_key_on_unknown_session_is_404() -> None:
    _accept_any_key(True)
    with TestClient(main.app) as client:
        r = client.put("/session/deadbeef/key", json={"api_key": FAKE_KEY})
        assert r.status_code == 404, r.text
        print("PASS  setting a key on an unknown session is a 404")


def test_session_repr_does_not_expose_the_key() -> None:
    """A stray log line or traceback must not print the key."""
    _accept_any_key(True)
    with TestClient(main.app) as client:
        sid = new_session(client)
        client.put(f"/session/{sid}/key", json={"api_key": FAKE_KEY})
        session = main.store.get(sid)
        assert session is not None
        assert FAKE_KEY not in repr(session), "repr(Session) leaked the key"
        assert FAKE_KEY not in str(session.redacted())
        print("PASS  repr(Session) and redacted() both omit the key")


def test_drop_table_removes_data_and_stale_context() -> None:
    """Removing a table must also clear what described it.

    A cached quality profile and a conversation history full of SQL against a table that
    no longer exists would both feed the model a schema it cannot query — the profile
    silently, the history by producing SQL that fails on every retry.
    """
    _accept_any_key(True)
    with TestClient(main.app) as client:
        sid = client.post("/session").json()["session_id"]
        client.post(
            "/upload",
            data={"session_id": sid},
            files=[
                ("files", ("sales.csv", io.BytesIO(CSV), "text/csv")),
                ("files", ("regions.csv", io.BytesIO(REGIONS_CSV), "text/csv")),
            ],
        )
        session = main.store.get(sid)
        assert session is not None
        assert set(session.engine.tables) == {"sales", "regions"}
        assert len(session.quality) == 2

        # A prior turn that references the table about to be removed, plus one that does not.
        session.history = [
            main.Turn(question="total", sql='SELECT SUM(revenue) FROM "sales"'),
            main.Turn(question="heads", sql='SELECT head FROM "regions"'),
        ]

        r = client.delete(f"/session/{sid}/table/sales")
        assert r.status_code == 200, r.text
        body = r.json()
        assert [t["name"] for t in body["tables"]] == ["regions"]

        assert "sales" not in session.engine.tables
        assert [q["table"] for q in body["quality"]] == ["regions"], body["quality"]
        assert [t.question for t in session.history] == ["heads"], session.history

        # The name is released, so re-uploading the same file is not renamed to sales_2.
        client.post(
            "/upload", data={"session_id": sid},
            files=[("files", ("sales.csv", io.BytesIO(CSV), "text/csv"))],
        )
        assert "sales" in session.engine.tables, list(session.engine.tables)
        print("PASS  drop table: data, profile and stale history all cleared; name reusable")


def test_drop_unknown_table_is_404() -> None:
    _accept_any_key(True)
    with TestClient(main.app) as client:
        sid = new_session(client)
        r = client.delete(f"/session/{sid}/table/nope")
        assert r.status_code == 404, r.text
        r2 = client.delete("/session/deadbeef/table/sales")
        assert r2.status_code == 404, r2.text
        print("PASS  drop table: unknown table and unknown session both 404")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    original = GroqProvider.verify_key
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {t.__name__}: {e}")
    GroqProvider.verify_key = original  # type: ignore[method-assign]
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
