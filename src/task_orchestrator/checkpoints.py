"""Checkpoint management — export snapshots and DB integrity verification."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db as _db
from . import engine


def _default_output_dir() -> str:
    """Default checkpoint dir: same directory as the SQLite DB file."""
    return str(Path(_db.DB_PATH).parent)


def create_checkpoint(output_dir: str | None = None) -> str:
    """Export graph and save to checkpoint-{ISO-timestamp}.json. Returns file path."""
    out = output_dir or _default_output_dir()
    os.makedirs(out, exist_ok=True)
    data = engine.export_graph()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"checkpoint-{ts}.json"
    filepath = os.path.join(out, filename)
    with open(filepath, "w") as f:
        json.dump(data, f, default=str)
    return filepath


def list_checkpoints(output_dir: str | None = None) -> list[str]:
    """List .json checkpoint files in output dir sorted by date (newest first)."""
    out = output_dir or _default_output_dir()
    if not os.path.isdir(out):
        return []
    files = sorted(
        (
            os.path.join(out, name)
            for name in os.listdir(out)
            if name.startswith("checkpoint-") and name.endswith(".json")
        ),
        reverse=True,
    )
    return files


def restore_checkpoint(path: str) -> bool:
    """Restore graph from a checkpoint file using import_graph(replace). Returns True on success."""
    with open(path) as f:
        data = json.load(f)
    engine.import_graph(data, mode="replace")
    return True


def verify_db_integrity() -> bool:
    """Run PRAGMA integrity_check on the DB. Returns True if healthy."""
    try:
        conn = sqlite3.connect(_db.DB_PATH)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        return result[0] == "ok"
    except (sqlite3.DatabaseError, sqlite3.OperationalError):
        return False
