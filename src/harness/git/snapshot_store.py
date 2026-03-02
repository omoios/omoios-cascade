"""SQLite-backed snapshot store for workspace file contents.

Replaces in-memory dict[str, str] snapshots that were consuming 16-20GB.
Content is deduplicated via content-addressable hashing — 7 workers sharing
the same base snapshot store one copy of each file, not seven.
"""

import hashlib
import logging
import os
import sqlite3
import time
from types import TracebackType

from harness.git.workspace import _hash_file, _read_file_text, _walk_files

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    workspace_path TEXT NOT NULL,
    created_at REAL NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS blobs (
    content_hash TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    size INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_files (
    snapshot_id TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, rel_path),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id) ON DELETE CASCADE,
    FOREIGN KEY (content_hash) REFERENCES blobs(content_hash)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_files_hash
    ON snapshot_files(content_hash);
"""


class SnapshotStore:
    """SQLite-backed workspace snapshot storage with content deduplication.

    Usage::

        with SnapshotStore(".harness/snapshots.db") as store:
            store.capture("base-worker-1", "/path/to/repo")
            # ... worker does work ...
            store.capture("current-worker-1", "/path/to/workspace")
            changed = store.changed_files("base-worker-1", "current-worker-1")
            diffs = store.get_diff_contents("base-worker-1", "current-worker-1", changed)

    All methods are synchronous. Callers should wrap with ``asyncio.to_thread``
    for async usage.
    """

    def __init__(self, db_path: str = ".harness/snapshots.db") -> None:
        """Open or create the SQLite DB. Uses WAL mode for concurrent reads."""
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def capture(self, snapshot_id: str, workspace_path: str) -> int:
        """Walk workspace, hash + store each file. Returns file count.

        Reuses existing ``_walk_files``, ``_hash_file``, and ``_read_file_text``
        helpers from ``harness.git.workspace``. Content is deduplicated in the
        ``blobs`` table via ``INSERT OR IGNORE``.
        """
        files = _walk_files(workspace_path)

        blob_rows: list[tuple[str, str, int]] = []
        file_rows: list[tuple[str, str, str]] = []

        for rel_path, full_path in files:
            content_hash = _hash_file(full_path)
            if content_hash is None:
                continue

            content = _read_file_text(full_path)
            if content is None:
                continue

            blob_rows.append((content_hash, content, len(content)))
            file_rows.append((snapshot_id, rel_path, content_hash))

        with self._conn:
            # Delete prior snapshot with same id (idempotent recapture)
            self._conn.execute("DELETE FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
            self._conn.execute("DELETE FROM snapshot_files WHERE snapshot_id = ?", (snapshot_id,))

            # Insert blobs (dedup via INSERT OR IGNORE)
            self._conn.executemany(
                "INSERT OR IGNORE INTO blobs (content_hash, content, size) VALUES (?, ?, ?)",
                blob_rows,
            )

            # Insert snapshot metadata
            self._conn.execute(
                "INSERT INTO snapshots (snapshot_id, workspace_path, created_at, file_count) VALUES (?, ?, ?, ?)",
                (snapshot_id, workspace_path, time.time(), len(file_rows)),
            )

            # Insert file entries
            self._conn.executemany(
                "INSERT INTO snapshot_files (snapshot_id, rel_path, content_hash) VALUES (?, ?, ?)",
                file_rows,
            )

        return len(file_rows)

    # ------------------------------------------------------------------
    # Single-file retrieval
    # ------------------------------------------------------------------

    def get_content(self, snapshot_id: str, rel_path: str) -> str | None:
        """Lazy single-file content retrieval from store."""
        row = self._conn.execute(
            "SELECT b.content FROM snapshot_files sf "
            "JOIN blobs b ON sf.content_hash = b.content_hash "
            "WHERE sf.snapshot_id = ? AND sf.rel_path = ?",
            (snapshot_id, rel_path),
        ).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------
    # Lightweight metadata queries (no content loaded)
    # ------------------------------------------------------------------

    def get_hashes(self, snapshot_id: str) -> dict[str, str]:
        """Return {rel_path: content_hash} for a snapshot. No content loaded."""
        rows = self._conn.execute(
            "SELECT rel_path, content_hash FROM snapshot_files WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        return {rel_path: content_hash for rel_path, content_hash in rows}

    def get_all_paths(self, snapshot_id: str) -> set[str]:
        """Return set of all rel_paths in a snapshot."""
        rows = self._conn.execute(
            "SELECT rel_path FROM snapshot_files WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        return {row[0] for row in rows}

    # ------------------------------------------------------------------
    # Diff operations
    # ------------------------------------------------------------------

    def changed_files(self, snapshot_a: str, snapshot_b: str) -> list[str]:
        """SQL-based diff: find paths where hash differs between two snapshots.

        Uses a single query with FULL OUTER JOIN (emulated via UNION).
        No content is loaded into memory — only hashes are compared.
        """
        rows = self._conn.execute(
            """
            SELECT COALESCE(a.rel_path, b.rel_path) AS path
            FROM snapshot_files a
            FULL OUTER JOIN snapshot_files b
                ON a.rel_path = b.rel_path AND b.snapshot_id = ?
            WHERE a.snapshot_id = ?
                AND COALESCE(a.content_hash, '') != COALESCE(b.content_hash, '')
            UNION
            SELECT b2.rel_path
            FROM snapshot_files b2
            LEFT JOIN snapshot_files a2
                ON b2.rel_path = a2.rel_path AND a2.snapshot_id = ?
            WHERE b2.snapshot_id = ? AND a2.rel_path IS NULL
            ORDER BY 1
            """,
            (snapshot_b, snapshot_a, snapshot_a, snapshot_b),
        ).fetchall()
        return [row[0] for row in rows]

    def get_diff_contents(self, snapshot_a: str, snapshot_b: str, paths: list[str]) -> list[dict[str, str | None]]:
        """For a list of changed paths, return diffs with content.

        Only loads content for the specific changed files, not the whole snapshot.
        Returns ``[{"path": str, "before": str | None, "after": str | None}]``.
        """
        if not paths:
            return []

        result: list[dict[str, str | None]] = []
        for rel_path in paths:
            before = self.get_content(snapshot_a, rel_path)
            after = self.get_content(snapshot_b, rel_path)
            result.append({"path": rel_path, "before": before, "after": after})
        return result

    # ------------------------------------------------------------------
    # Backwards-compatible full snapshot (DEPRECATED)
    # ------------------------------------------------------------------

    def get_snapshot_content(self, snapshot_id: str) -> dict[str, str]:
        """Return full {rel_path: content} dict.

        .. deprecated::
            This loads ALL file contents into memory — the exact problem
            SnapshotStore was built to avoid. Use ``get_content()`` for
            single files or ``changed_files()`` + ``get_diff_contents()``
            for diffs. This method exists only for migration compatibility.
        """
        logger.warning(
            "SnapshotStore.get_snapshot_content() loads all content into memory. "
            "Use get_content() or changed_files() + get_diff_contents() instead. "
            "snapshot_id=%s",
            snapshot_id,
        )
        rows = self._conn.execute(
            "SELECT sf.rel_path, b.content FROM snapshot_files sf "
            "JOIN blobs b ON sf.content_hash = b.content_hash "
            "WHERE sf.snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        return {rel_path: content for rel_path, content in rows}

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def delete_snapshot(self, snapshot_id: str) -> None:
        """Delete a snapshot and its file entries. Orphan blobs cleaned lazily."""
        with self._conn:
            self._conn.execute("DELETE FROM snapshot_files WHERE snapshot_id = ?", (snapshot_id,))
            self._conn.execute("DELETE FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))

    def cleanup_orphan_blobs(self) -> int:
        """Delete blobs not referenced by any snapshot_files. Returns count removed."""
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM blobs WHERE content_hash NOT IN (SELECT DISTINCT content_hash FROM snapshot_files)"
            )
            return cursor.rowcount

    def has_snapshot(self, snapshot_id: str) -> bool:
        """Check if a snapshot exists."""
        row = self._conn.execute("SELECT 1 FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the DB connection."""
        self._conn.close()

    def __enter__(self) -> "SnapshotStore":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
