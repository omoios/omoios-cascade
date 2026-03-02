"""Consolidated SQLite storage for harness runtime state.

Replaces in-memory dicts/lists for: events, watchdog activities, handoffs,
and agent messages. Each table is append-only with indexed lookups.

All methods are synchronous. Callers wrap with ``asyncio.to_thread`` for async.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    event_type TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent_id);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    files_touched TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_activities_agent ON activities(agent_id);

CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '',
    narrative TEXT NOT NULL DEFAULT '',
    diffs TEXT NOT NULL DEFAULT '[]',
    tokens_used INTEGER NOT NULL DEFAULT 0,
    turns INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent_seq ON messages(agent_id, seq);
"""


class HarnessDB:
    """Single SQLite database for all harness runtime state.

    Usage::

        db = HarnessDB(".harness/harness.db")
        db.insert_event(1.0, "worker_spawned", "w-1", {"task_id": "t1"})
        events = db.get_events(event_type="worker_spawned")
        db.close()
    """

    def __init__(self, db_path: str = ".harness/harness.db") -> None:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Events (replaces EventBus._history)
    # ------------------------------------------------------------------

    def insert_event(
        self,
        timestamp: float,
        event_type: str,
        agent_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> int:
        """Insert an event. Returns the row id."""
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO events (timestamp, event_type, agent_id, payload) VALUES (?, ?, ?, ?)",
                (timestamp, event_type, agent_id, json.dumps(payload or {})),
            )
            return cursor.lastrowid or 0

    def get_events(
        self,
        event_type: str | None = None,
        agent_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query events with optional filters."""
        clauses: list[str] = []
        params: list[Any] = []
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if agent_id is not None:
            clauses.append("agent_id = ?")
            params.append(agent_id)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        order = " ORDER BY id ASC"
        limit_clause = f" LIMIT {limit}" if limit else ""
        sql = f"SELECT id, timestamp, event_type, agent_id, payload FROM events{where}{order}{limit_clause}"

        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "id": row[0],
                "timestamp": row[1],
                "event_type": row[2],
                "agent_id": row[3],
                "payload": json.loads(row[4]),
            }
            for row in rows
        ]

    def event_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Watchdog Activities (replaces Watchdog._activities)
    # ------------------------------------------------------------------

    def insert_activity(
        self,
        agent_id: str,
        event_type: str,
        timestamp: float,
        tokens_used: int = 0,
        files_touched: list[str] | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO activities (agent_id, event_type, timestamp, tokens_used, files_touched) "
                "VALUES (?, ?, ?, ?, ?)",
                (agent_id, event_type, timestamp, tokens_used, json.dumps(files_touched or [])),
            )

    def get_activities(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        """Get activities, optionally filtered by agent."""
        if agent_id is not None:
            rows = self._conn.execute(
                "SELECT agent_id, event_type, timestamp, tokens_used, files_touched "
                "FROM activities WHERE agent_id = ? ORDER BY id ASC",
                (agent_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT agent_id, event_type, timestamp, tokens_used, files_touched FROM activities ORDER BY id ASC"
            ).fetchall()

        return [
            {
                "agent_id": row[0],
                "event_type": row[1],
                "timestamp": row[2],
                "tokens_used": row[3],
                "files_touched": json.loads(row[4]),
            }
            for row in rows
        ]

    def get_activity_agent_ids(self) -> list[str]:
        """Return distinct agent IDs that have activity records."""
        rows = self._conn.execute("SELECT DISTINCT agent_id FROM activities").fetchall()
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # Handoffs (replaces runner._handoffs)
    # ------------------------------------------------------------------

    def insert_handoff(self, handoff_id: str, handoff: dict[str, Any]) -> None:
        """Upsert a handoff record."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO handoffs "
                "(handoff_id, worker_id, task_id, status, narrative, diffs, tokens_used, turns, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    handoff_id,
                    handoff.get("worker_id", ""),
                    handoff.get("task_id", ""),
                    handoff.get("status", ""),
                    handoff.get("narrative", ""),
                    json.dumps(handoff.get("diffs", [])),
                    handoff.get("tokens_used", 0),
                    handoff.get("turns", 0),
                    time.time(),
                ),
            )

    def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        """Get a single handoff by ID."""
        row = self._conn.execute(
            "SELECT handoff_id, worker_id, task_id, status, narrative, diffs, tokens_used, turns "
            "FROM handoffs WHERE handoff_id = ?",
            (handoff_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "worker_id": row[1],
            "task_id": row[2],
            "status": row[3],
            "narrative": row[4],
            "diffs": json.loads(row[5]),
            "tokens_used": row[6],
            "turns": row[7],
        }

    def delete_handoff(self, handoff_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM handoffs WHERE handoff_id = ?", (handoff_id,))

    def has_handoff(self, handoff_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM handoffs WHERE handoff_id = ?", (handoff_id,)).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Messages (replaces BaseAgent.messages list)
    # ------------------------------------------------------------------

    def append_message(self, agent_id: str, seq: int, role: str, content: Any) -> None:
        """Append a message for an agent. Content is JSON-serialized."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO messages (agent_id, seq, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (agent_id, seq, role, json.dumps(content, default=str), time.time()),
            )

    def get_messages(self, agent_id: str) -> list[dict[str, Any]]:
        """Get all messages for an agent, ordered by sequence."""
        rows = self._conn.execute(
            "SELECT seq, role, content FROM messages WHERE agent_id = ? ORDER BY seq ASC",
            (agent_id,),
        ).fetchall()
        return [{"role": row[1], "content": json.loads(row[2])} for row in rows]

    def get_messages_count(self, agent_id: str) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM messages WHERE agent_id = ?", (agent_id,)).fetchone()
        return row[0] if row else 0

    def replace_messages(self, agent_id: str, messages: list[dict[str, Any]]) -> None:
        """Replace all messages for an agent (used after compression)."""
        with self._conn:
            self._conn.execute("DELETE FROM messages WHERE agent_id = ?", (agent_id,))
            for seq, msg in enumerate(messages):
                self._conn.execute(
                    "INSERT INTO messages (agent_id, seq, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (agent_id, seq, msg.get("role", ""), json.dumps(msg.get("content", ""), default=str), time.time()),
                )

    def delete_messages(self, agent_id: str) -> None:
        """Delete all messages for an agent."""
        with self._conn:
            self._conn.execute("DELETE FROM messages WHERE agent_id = ?", (agent_id,))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def clear_all(self) -> None:
        """Drop all rows from every table. Called at harness startup to prevent stale data."""
        with self._conn:
            for table in ("events", "activities", "handoffs", "messages"):
                self._conn.execute(f"DELETE FROM {table}")

    def __enter__(self) -> HarnessDB:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
