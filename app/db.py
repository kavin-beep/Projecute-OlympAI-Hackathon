"""SQLite storage for Projecute.

All reads go through helpers that take the *requesting* user id so privacy is
enforced in the backend, not in the UI (deck slide 12).
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterable
from typing import Any

DB_PATH = os.environ.get(
    "PROJECUTE_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "projecute.db"),
)

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    accent TEXT NOT NULL DEFAULT '#6b8afd',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL
);

-- ---------- Individual chat (private) ----------
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    title TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    surface TEXT NOT NULL DEFAULT 'chat'   -- 'chat' | 'workspace'
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                    -- 'user' | 'assistant'
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);

-- ---------- Groups ----------
CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    host_user_id TEXT NOT NULL REFERENCES users(id),
    allow_public_ai INTEGER NOT NULL DEFAULT 1,
    allow_private_ai INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS group_members (
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL DEFAULT 'member',   -- 'host' | 'member'
    PRIMARY KEY (group_id, user_id)
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS group_messages (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id),
    kind TEXT NOT NULL DEFAULT 'user',     -- 'user' | 'ai_public' | 'notice'
    content TEXT NOT NULL,
    reply_to_id TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reactions (
    message_id TEXT NOT NULL REFERENCES group_messages(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    emoji TEXT NOT NULL,
    PRIMARY KEY (message_id, user_id, emoji)
);

-- Private AI help inside a group: readable only by the asker.
CREATE TABLE IF NOT EXISTS private_help (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    prompt TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at REAL NOT NULL
);

-- ---------- Workspaces ----------
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),     -- NULL for a group project
    group_id TEXT REFERENCES groups(id),   -- NULL for a personal project
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL REFERENCES users(id),
    project_id TEXT REFERENCES projects(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL,                    -- content | email | code | image | audio
    body TEXT NOT NULL DEFAULT '',
    language TEXT,
    data_url TEXT,
    source_chat_id TEXT REFERENCES chats(id),
    shared_group_id TEXT REFERENCES groups(id),   -- NULL until explicitly shared
    generator TEXT NOT NULL DEFAULT 'live',       -- live | mock
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- ---------- Group workspace ----------
CREATE TABLE IF NOT EXISTS briefs (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',  -- draft | approved
    approved_by TEXT REFERENCES users(id),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'Medium',
    estimated_hours REAL NOT NULL DEFAULT 0,
    hours_confirmed INTEGER NOT NULL DEFAULT 0,
    owner_user_id TEXT REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'proposed',  -- proposed | approved | blocked | done
    acceptance_criteria TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    alert_id TEXT,
    decided_by TEXT REFERENCES users(id),
    created_at REAL NOT NULL
);

-- Sources the team adds for the agents to cross-check: PRDs, bug tickets and
-- meeting summaries. Each is split into statements ("claims") for retrieval.
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                   -- prd | bug | meeting
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    user_id TEXT REFERENCES users(id),
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS document_claims (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                   -- duplicate | contradiction | assumption | unclear | blocker
    severity TEXT NOT NULL DEFAULT 'medium',
    headline TEXT NOT NULL,
    explanation TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- open | resolved | dismissed
    resolution TEXT,
    resolved_by TEXT REFERENCES users(id),
    options TEXT,                         -- JSON list of plain-language resolution options
    created_at REAL NOT NULL,
    resolved_at REAL
);

CREATE TABLE IF NOT EXISTS alert_sources (
    alert_id TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    message_id TEXT NOT NULL REFERENCES group_messages(id) ON DELETE CASCADE,
    PRIMARY KEY (alert_id, message_id)
);

-- Evidence that is not a chat message: a statement from a source document,
-- or an existing task that a bug ticket duplicates.
CREATE TABLE IF NOT EXISTS alert_evidence (
    alert_id TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    ref_kind TEXT NOT NULL,               -- claim | ticket
    ref_id TEXT NOT NULL,
    PRIMARY KEY (alert_id, ref_kind, ref_id)
);

CREATE TABLE IF NOT EXISTS alert_tickets (
    alert_id TEXT NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    PRIMARY KEY (alert_id, ticket_id)
);

CREATE TABLE IF NOT EXISTS activity (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    actor TEXT NOT NULL,                  -- agent name or user display name
    actor_kind TEXT NOT NULL DEFAULT 'agent',
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    ref_kind TEXT,
    ref_id TEXT,
    created_at REAL NOT NULL
);

-- ---------- Innovations ----------
CREATE TABLE IF NOT EXISTS futures (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    scenario TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- open | compared
    comparison TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS future_answers (
    id TEXT PRIMARY KEY,
    future_id TEXT NOT NULL REFERENCES futures(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    answer TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS unit_tests (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    creator_user_id TEXT NOT NULL REFERENCES users(id),
    assignee_user_id TEXT REFERENCES users(id),
    creator_desc TEXT,
    assignee_desc TEXT,
    verdict TEXT,                         -- match | mismatch
    comparison TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gm_channel ON group_messages(channel_id, created_at);
CREATE INDEX IF NOT EXISTS idx_items_owner ON items(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_activity_group ON activity(group_id, created_at);
"""


def now() -> float:
    """Current time as a Unix timestamp (seconds)."""
    return time.time()


def new_id(prefix: str = "") -> str:
    """A new random id for any row."""
    return (prefix + uuid.uuid4().hex[:12]) if prefix else uuid.uuid4().hex[:16]


def connect() -> sqlite3.Connection:
    """Open (once) the shared SQLite connection for this process."""
    global _conn
    with _lock:
        if _conn is None:
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SCHEMA)
            _conn.commit()
        return _conn


def init_db() -> None:
    """Create every table that does not exist yet."""
    connect()


def reset_db() -> None:
    """Drop every table and recreate the schema, in place.

    The tables are dropped inside the existing database file rather than
    deleting it, so a server already running against this file sees the fresh
    data instead of holding a handle to a deleted one.
    """
    with _lock:
        c = connect()
        c.execute("PRAGMA foreign_keys=OFF")
        names = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for name in names:
            c.execute(f'DROP TABLE IF EXISTS "{name}"')
        c.commit()
        c.executescript(SCHEMA)
        c.commit()


def q(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    """Run a SELECT and return all rows."""
    with _lock:
        return connect().execute(sql, tuple(params)).fetchall()


def q1(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    """Run a SELECT and return the first row, or None."""
    rows = q(sql, params)
    return rows[0] if rows else None


def ex(sql: str, params: Iterable[Any] = ()) -> None:
    """Run one INSERT/UPDATE/DELETE and commit."""
    with _lock:
        c = connect()
        c.execute(sql, tuple(params))
        c.commit()


def exmany(sql: str, seq: Iterable[Iterable[Any]]) -> None:
    """Run one statement for many parameter tuples and commit."""
    with _lock:
        c = connect()
        c.executemany(sql, [tuple(s) for s in seq])
        c.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """Convert a sqlite3.Row to a plain dict (None stays None)."""
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    """Convert a list of sqlite3.Row objects to plain dicts."""
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Membership / permission helpers — every group read goes through these.
# --------------------------------------------------------------------------

def is_member(group_id: str, user_id: str) -> bool:
    """True if the user belongs to the group."""
    return q1("SELECT 1 FROM group_members WHERE group_id=? AND user_id=?", (group_id, user_id)) is not None


def is_host(group_id: str, user_id: str) -> bool:
    """True if the user is the group's host."""
    row = q1("SELECT host_user_id FROM groups WHERE id=?", (group_id,))
    return bool(row) and row["host_user_id"] == user_id


def log_activity(group_id: str, actor: str, action: str, detail: str = "",
                 actor_kind: str = "agent", ref_kind: str | None = None,
                 ref_id: str | None = None) -> dict:
    """Record an entry in the group's activity stream and return it."""
    aid = new_id()
    ts = now()
    ex(
        "INSERT INTO activity (id, group_id, actor, actor_kind, action, detail, ref_kind, ref_id, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, group_id, actor, actor_kind, action, detail, ref_kind, ref_id, ts),
    )
    return {
        "id": aid, "group_id": group_id, "actor": actor, "actor_kind": actor_kind,
        "action": action, "detail": detail, "ref_kind": ref_kind, "ref_id": ref_id,
        "created_at": ts,
    }
