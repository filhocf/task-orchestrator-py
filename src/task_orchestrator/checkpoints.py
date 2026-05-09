"""Checkpoint management — periodic JSON export and corruption recovery."""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db as _db

logger = logging.getLogger(__name__)

DEFAULT_CHECKPOINT_DIR = str(Path.home() / ".task-orchestrator" / "checkpoints")

_config = {
    "interval_minutes": 30,
    "output_path": os.environ.get("TASK_ORCHESTRATOR_CHECKPOINT_DIR", DEFAULT_CHECKPOINT_DIR),
}


def get_config() -> dict:
    return dict(_config)


def configure(interval_minutes: int | None = None, output_path: str | None = None) -> dict:
    if interval_minutes is not None:
        _config["interval_minutes"] = interval_minutes
    if output_path is not None:
        _config["output_path"] = output_path
    return get_config()


def create_checkpoint(data: dict) -> dict:
    """Write export data to a timestamped JSON checkpoint file."""
    out_dir = _config["output_path"]
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"checkpoint-{ts}.json"
    filepath = os.path.join(out_dir, filename)
    with open(filepath, "w") as f:
        json.dump(data, f, default=str)
    return {"created": filepath, "size_bytes": os.path.getsize(filepath)}


def list_checkpoints() -> list[dict]:
    """List available checkpoint files sorted by newest first."""
    out_dir = _config["output_path"]
    if not os.path.isdir(out_dir):
        return []
    files = []
    for name in sorted(os.listdir(out_dir), reverse=True):
        if name.startswith("checkpoint-") and name.endswith(".json"):
            path = os.path.join(out_dir, name)
            files.append({
                "filename": name,
                "path": path,
                "size_bytes": os.path.getsize(path),
                "modified_at": datetime.fromtimestamp(
                    os.path.getmtime(path), tz=timezone.utc
                ).isoformat(),
            })
    return files


def load_checkpoint(filepath: str) -> dict:
    """Load a checkpoint file and return its data."""
    with open(filepath) as f:
        return json.load(f)


def verify_db_integrity() -> dict:
    """Check SQLite database integrity. Returns status and details."""
    try:
        conn = _db.get_connection()
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        ok = result[0] == "ok"
        return {"ok": ok, "detail": result[0]}
    except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
        return {"ok": False, "detail": str(e)}


def auto_recover() -> dict | None:
    """If DB is corrupt, restore from latest checkpoint. Returns recovery info or None."""
    status = verify_db_integrity()
    if status["ok"]:
        return None

    logger.warning("Database corruption detected: %s", status["detail"])
    checkpoints = list_checkpoints()
    if not checkpoints:
        logger.error("No checkpoints available for recovery")
        return {"recovered": False, "reason": "no checkpoints available"}

    latest = checkpoints[0]
    logger.info("Recovering from checkpoint: %s", latest["filename"])

    # Remove corrupt DB and WAL/SHM files
    db_path = _db.DB_PATH
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        for suffix in ("-wal", "-shm"):
            p = db_path + suffix
            if os.path.exists(p):
                os.remove(p)
    except OSError as e:
        logger.error("Failed to remove corrupt DB files: %s", e)
        return {"recovered": False, "reason": f"file removal failed: {e}"}

    # Re-init and import
    _db.init_db()

    data = load_checkpoint(latest["path"])
    from .engine import import_graph
    import_graph(data, mode="replace")

    return {"recovered": True, "from_checkpoint": latest["filename"]}
