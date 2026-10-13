"""SQLite access layer: one shared connection, explicit transactions, versioned schema."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE people (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('elder', 'caregiver', 'family')),
    language         TEXT NOT NULL DEFAULT 'en',
    timezone         TEXT NOT NULL,
    telegram_chat_id TEXT,
    created_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_people_name ON people (lower(name));

CREATE TABLE care_links (
    elder_id  INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
    relation  TEXT,
    PRIMARY KEY (elder_id, member_id),
    CHECK (elder_id <> member_id)
);

CREATE TABLE checkins (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
    ts        TEXT NOT NULL,
    note      TEXT NOT NULL DEFAULT '',
    mood      INTEGER CHECK (mood BETWEEN 1 AND 5),
    severity  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_checkins_person_ts ON checkins (person_id, ts);

CREATE TABLE reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    at_time    TEXT NOT NULL,
    days       TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
    created_by INTEGER REFERENCES people (id) ON DELETE SET NULL,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE reminder_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id  INTEGER NOT NULL REFERENCES reminders (id) ON DELETE CASCADE,
    person_id    INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
    due_at       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'taken', 'skipped', 'missed')),
    responded_at TEXT,
    UNIQUE (reminder_id, due_at)
);
CREATE INDEX idx_events_person_due ON reminder_events (person_id, due_at);

CREATE TABLE messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id      INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
    to_id        INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    delivered_at TEXT,
    private      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_messages_to ON messages (to_id, delivered_at);

CREATE TABLE alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id       INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
    severity        INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    detail          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    notified_at     TEXT,
    acknowledged_at TEXT,
    dedupe_key      TEXT
);
CREATE UNIQUE INDEX idx_alerts_dedupe ON alerts (person_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;
CREATE INDEX idx_alerts_person_created ON alerts (person_id, created_at);
"""

_MIGRATIONS: dict[int, str] = {1: _SCHEMA_V1}


class Database:
    """Thread-safe wrapper around a single SQLite connection."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(
            self._path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self._path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.RLock()
        self._depth = 0
        self._migrate()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate(self) -> None:
        with self._lock:
            current = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for version in range(current + 1, SCHEMA_VERSION + 1):
                self._conn.executescript(
                    f"BEGIN;\n{_MIGRATIONS[version]}\nPRAGMA user_version = {version};\nCOMMIT;"
                )

    # -- transactions ------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Re-entrant transaction: only the outermost block commits or rolls back."""
        with self._lock:
            outermost = self._depth == 0
            if outermost:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outermost:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outermost:
                    self._conn.execute("COMMIT")

    # -- queries -----------------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            return int(cursor.lastrowid)
