"""In-process session store.

Each session owns one DuckDB engine, its cached schema/join map, a bounded
conversation history and a token budget. Sessions are ephemeral by design: they live
in memory, expire on TTL, and are destroyed on demand (nothing is written to disk).

Caching note: schema + join detection are computed ONCE at upload and reused for every
subsequent question, so repeated questions never re-derive them.

Scale caveat (documented in the README): this is per-process state, so run the backend
single-worker for the prototype. Swapping this class for Redis + file-backed DuckDB is
the production path.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from app.config import Settings
from app.ingestion.engine import DataEngine
from app.analytics.pipeline import Turn
from app.validation.data_quality import TableQuality


@dataclass
class Session:
    id: str
    engine: DataEngine
    created_at: float
    last_seen: float
    history: list[Turn] = field(default_factory=list)
    tokens_used: int = 0
    message_count: int = 0
    # Profiled once per upload and reused for every question, like the schema and the
    # join map — the checks are aggregate scans, so re-running them per question would
    # be pure waste.
    quality: list[TableQuality] = field(default_factory=list)

    # Optional bring-your-own key, scoped to THIS session only.
    #
    # Deliberately per-session rather than global: a global key set over HTTP would let
    # any visitor to a deployed instance overwrite the key everyone else's questions are
    # billed to. Held in memory only — never written to disk, never returned by the API
    # (endpoints expose `has_key: true` and nothing more), and discarded when the
    # session expires or the process restarts.
    api_key: str | None = field(default=None, repr=False)

    def touch(self) -> None:
        self.last_seen = time.time()

    def redacted(self) -> dict[str, object]:
        """Session facts that are safe to serialise. Never includes the key itself."""
        return {
            "session_id": self.id,
            "has_key": self.api_key is not None,
            "tokens_used": self.tokens_used,
        }


class SessionStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        self._evict_expired()
        sid = uuid.uuid4().hex
        now = time.time()
        s = Session(
            id=sid,
            engine=DataEngine.create(self.settings.sql_statement_timeout_s),
            created_at=now,
            last_seen=now,
        )
        self._sessions[sid] = s
        return s

    def get(self, session_id: str) -> Session | None:
        self._evict_expired()
        s = self._sessions.get(session_id)
        if s:
            s.touch()
        return s

    def delete(self, session_id: str) -> bool:
        s = self._sessions.pop(session_id, None)
        if s:
            s.engine.close()
            return True
        return False

    def _evict_expired(self) -> None:
        ttl = self.settings.session_ttl_minutes * 60
        now = time.time()
        for sid in [s.id for s in self._sessions.values() if now - s.last_seen > ttl]:
            self.delete(sid)
