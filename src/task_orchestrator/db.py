"""SQLite database layer for persistent work item storage."""

import sqlite3
import os
from pathlib import Path

DB_PATH = os.environ.get(
    "TASK_ORCHESTRATOR_DB",
    str(Path.home() / ".task-orchestrator" / "tasks.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS work_items (
    id TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES work_items(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queue',
    previous_status TEXT DEFAULT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    item_type TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'queue',
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(item_id, key)
);

CREATE TABLE IF NOT EXISTS dependencies (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    to_id TEXT NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    dep_type TEXT NOT NULL DEFAULT 'blocks',
    created_at TEXT NOT NULL,
    UNIQUE(from_id, to_id)
);

CREATE INDEX IF NOT EXISTS idx_items_parent ON work_items(parent_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON work_items(status);
CREATE INDEX IF NOT EXISTS idx_notes_item ON notes(item_id);
CREATE INDEX IF NOT EXISTS idx_deps_from ON dependencies(from_id);
CREATE INDEX IF NOT EXISTS idx_deps_to ON dependencies(to_id);
"""

MIGRATIONS = [
    ("previous_status",
     "ALTER TABLE work_items ADD COLUMN previous_status TEXT DEFAULT NULL"),
]


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    _run_migrations(conn)
    conn.close()


def _run_migrations(conn: sqlite3.Connection):
    """Apply additive migrations safely."""
    for name, sql in MIGRATIONS:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
