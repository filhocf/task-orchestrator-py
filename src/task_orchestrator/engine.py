"""Workflow engine — status transitions, dependency checks, queries.

Status flow: queue → work → review → done
Any non-terminal status can go to: blocked (via block trigger) → resume → previous status
Terminal statuses: done, cancelled
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from .db import get_connection

VALID_STATUSES = {"queue", "work", "review", "done", "blocked", "cancelled"}
TERMINAL = {"done", "cancelled"}
PRIORITIES = {"critical", "high", "medium", "low"}

TRANSITIONS = {
    "start": {"queue": "work", "work": "review", "review": "done"},
    "complete": {"queue": "done", "work": "done", "review": "done"},
    "block": {"queue": "blocked", "work": "blocked", "review": "blocked"},
    "cancel": {"queue": "cancelled", "work": "cancelled", "review": "cancelled", "blocked": "cancelled"},
    "reopen": {"done": "queue", "cancelled": "queue"},
}

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _row_to_dict(row) -> dict:
    return dict(row) if row else None


# --- WorkItem CRUD ---

def create_item(title: str, description: str = "", parent_id: str | None = None,
                priority: str = "medium", item_type: str = "", tags: str = "") -> dict:
    conn = get_connection()
    item_id = _uid()
    now = _now()
    if parent_id:
        parent = conn.execute("SELECT id FROM work_items WHERE id=?", (parent_id,)).fetchone()
        if not parent:
            conn.close()
            raise ValueError(f"Parent {parent_id} not found")
        depth = _get_depth(conn, parent_id)
        if depth >= 3:
            conn.close()
            raise ValueError(f"Max depth 4 reached (parent at depth {depth})")
    conn.execute(
        "INSERT INTO work_items (id,parent_id,title,description,status,priority,item_type,tags,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (item_id, parent_id, title, description, "queue", priority, item_type, tags, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def update_item(item_id: str, **fields) -> dict:
    conn = get_connection()
    allowed = {"title", "description", "priority", "item_type", "tags"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        conn.close()
        raise ValueError("No valid fields to update")
    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn.execute(f"UPDATE work_items SET {set_clause} WHERE id=?", (*updates.values(), item_id))
    conn.commit()
    row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Item {item_id} not found")
    return _row_to_dict(row)


def delete_item(item_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM work_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_item(item_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def query_items(status: str | None = None, parent_id: str | None = None,
                priority: str | None = None, search: str | None = None,
                limit: int = 50, offset: int = 0) -> list[dict]:
    conn = get_connection()
    clauses, params = [], []
    if status:
        clauses.append("status=?")
        params.append(status)
    if parent_id:
        clauses.append("parent_id=?")
        params.append(parent_id)
    if priority:
        clauses.append("priority=?")
        params.append(priority)
    if search:
        clauses.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM work_items {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_children(parent_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM work_items WHERE parent_id=? ORDER BY created_at", (parent_id,)).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def _get_depth(conn, item_id: str) -> int:
    depth = 0
    current = item_id
    while current:
        row = conn.execute("SELECT parent_id FROM work_items WHERE id=?", (current,)).fetchone()
        if not row or not row["parent_id"]:
            break
        current = row["parent_id"]
        depth += 1
    return depth


# --- Workflow ---

def advance_item(item_id: str, trigger: str) -> dict:
    if trigger not in TRANSITIONS:
        raise ValueError(f"Invalid trigger: {trigger}. Valid: {list(TRANSITIONS.keys())}")
    conn = get_connection()
    row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Item {item_id} not found")
    current = row["status"]
    if trigger == "resume":
        # Resume from blocked — go back to work
        if current != "blocked":
            conn.close()
            raise ValueError(f"Can only resume blocked items, current: {current}")
        new_status = "work"
    else:
        if current not in TRANSITIONS[trigger]:
            conn.close()
            raise ValueError(f"Cannot {trigger} from {current}")
        new_status = TRANSITIONS[trigger][current]
    # Check dependencies for start/complete triggers
    if trigger in ("start", "complete") and current == "queue":
        blockers = _get_unsatisfied_blockers(conn, item_id)
        if blockers:
            conn.close()
            titles = [b["title"] for b in blockers]
            raise ValueError(f"Blocked by unfinished items: {', '.join(titles)}")
    now = _now()
    conn.execute("UPDATE work_items SET status=?, updated_at=? WHERE id=?", (new_status, now, item_id))
    conn.commit()
    result = _row_to_dict(conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone())
    # Find items unblocked by this transition
    unblocked = []
    if new_status in TERMINAL:
        unblocked = _find_newly_unblocked(conn, item_id)
    conn.close()
    result["unblocked_items"] = unblocked
    return result


def _get_unsatisfied_blockers(conn, item_id: str) -> list[dict]:
    rows = conn.execute("""
        SELECT wi.* FROM dependencies d
        JOIN work_items wi ON wi.id = d.from_id
        WHERE d.to_id = ? AND wi.status NOT IN ('done', 'cancelled')
    """, (item_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def _find_newly_unblocked(conn, completed_id: str) -> list[dict]:
    """Find items that were waiting on completed_id and now have all deps satisfied."""
    dependents = conn.execute(
        "SELECT to_id FROM dependencies WHERE from_id=?", (completed_id,)
    ).fetchall()
    unblocked = []
    for dep in dependents:
        blockers = _get_unsatisfied_blockers(conn, dep["to_id"])
        if not blockers:
            row = conn.execute("SELECT * FROM work_items WHERE id=?", (dep["to_id"],)).fetchone()
            if row and row["status"] not in TERMINAL:
                unblocked.append(_row_to_dict(row))
    return unblocked


def get_next_item() -> dict | None:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM work_items WHERE status IN ('queue','work') ORDER BY status ASC, created_at ASC",
    ).fetchall()
    conn.close()
    # Sort by priority, filter out blocked
    candidates = []
    for r in rows:
        item = _row_to_dict(r)
        conn2 = get_connection()
        blockers = _get_unsatisfied_blockers(conn2, item["id"])
        conn2.close()
        if not blockers:
            candidates.append(item)
    candidates.sort(key=lambda x: (0 if x["status"] == "work" else 1, PRIORITY_ORDER.get(x["priority"], 2)))
    return candidates[0] if candidates else None


def get_blocked_items() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM work_items WHERE status='blocked'").fetchall()
    # Also find items in queue with unsatisfied deps
    queue_rows = conn.execute("SELECT * FROM work_items WHERE status='queue'").fetchall()
    result = [_row_to_dict(r) for r in rows]
    for r in queue_rows:
        blockers = _get_unsatisfied_blockers(conn, r["id"])
        if blockers:
            item = _row_to_dict(r)
            item["blocked_by"] = [_row_to_dict(b) for b in blockers]
            result.append(item)
    conn.close()
    return result


def get_context(item_id: str | None = None) -> dict:
    conn = get_connection()
    if item_id:
        row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Item {item_id} not found")
        item = _row_to_dict(row)
        children = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM work_items WHERE parent_id=?", (item_id,)).fetchall()]
        notes = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM notes WHERE item_id=?", (item_id,)).fetchall()]
        blockers = _get_unsatisfied_blockers(conn, item_id)
        conn.close()
        return {"item": item, "children": children, "notes": notes,
                "blockers": [_row_to_dict(b) for b in blockers],
                "can_advance": len(blockers) == 0 and item["status"] not in TERMINAL}
    # Global context
    counts = {}
    for row in conn.execute("SELECT status, COUNT(*) as cnt FROM work_items GROUP BY status").fetchall():
        counts[row["status"]] = row["cnt"]
    active = [_row_to_dict(r) for r in conn.execute(
        "SELECT * FROM work_items WHERE status IN ('work','review') ORDER BY updated_at DESC LIMIT 10").fetchall()]
    recent = [_row_to_dict(r) for r in conn.execute(
        "SELECT * FROM work_items WHERE status IN ('done','cancelled') ORDER BY updated_at DESC LIMIT 5").fetchall()]
    conn.close()
    blocked = get_blocked_items()
    next_item = get_next_item()
    return {"counts": counts, "active": active, "blocked": blocked,
            "recent_completed": recent, "next_item": next_item}


# --- Notes ---

def upsert_note(item_id: str, key: str, body: str, role: str = "queue") -> dict:
    conn = get_connection()
    item = conn.execute("SELECT id FROM work_items WHERE id=?", (item_id,)).fetchone()
    if not item:
        conn.close()
        raise ValueError(f"Item {item_id} not found")
    now = _now()
    existing = conn.execute("SELECT id FROM notes WHERE item_id=? AND key=?", (item_id, key)).fetchone()
    if existing:
        conn.execute("UPDATE notes SET body=?, role=?, updated_at=? WHERE id=?",
                      (body, role, now, existing["id"]))
    else:
        conn.execute("INSERT INTO notes (id,item_id,key,role,body,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                      (_uid(), item_id, key, role, body, now, now))
    conn.commit()
    row = conn.execute("SELECT * FROM notes WHERE item_id=? AND key=?", (item_id, key)).fetchone()
    conn.close()
    return _row_to_dict(row)


def delete_note(item_id: str, key: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM notes WHERE item_id=? AND key=?", (item_id, key))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_notes(item_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM notes WHERE item_id=? ORDER BY created_at", (item_id,)).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


# --- Dependencies ---

def add_dependency(from_id: str, to_id: str, dep_type: str = "blocks") -> dict:
    if from_id == to_id:
        raise ValueError("Cannot depend on self")
    conn = get_connection()
    for fid in (from_id, to_id):
        if not conn.execute("SELECT id FROM work_items WHERE id=?", (fid,)).fetchone():
            conn.close()
            raise ValueError(f"Item {fid} not found")
    # Cycle detection
    if _would_create_cycle(conn, from_id, to_id):
        conn.close()
        raise ValueError("Dependency would create a cycle")
    dep_id = _uid()
    now = _now()
    try:
        conn.execute("INSERT INTO dependencies (id,from_id,to_id,dep_type,created_at) VALUES (?,?,?,?,?)",
                      (dep_id, from_id, to_id, dep_type, now))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"Dependency {from_id} → {to_id} already exists")
    row = conn.execute("SELECT * FROM dependencies WHERE id=?", (dep_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def remove_dependency(from_id: str, to_id: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM dependencies WHERE from_id=? AND to_id=?", (from_id, to_id))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_dependencies(item_id: str, direction: str = "both") -> dict:
    conn = get_connection()
    blocks = []
    blocked_by = []
    if direction in ("outbound", "both"):
        rows = conn.execute("""
            SELECT d.*, wi.title as to_title, wi.status as to_status
            FROM dependencies d JOIN work_items wi ON wi.id=d.to_id WHERE d.from_id=?
        """, (item_id,)).fetchall()
        blocks = [_row_to_dict(r) for r in rows]
    if direction in ("inbound", "both"):
        rows = conn.execute("""
            SELECT d.*, wi.title as from_title, wi.status as from_status
            FROM dependencies d JOIN work_items wi ON wi.id=d.from_id WHERE d.to_id=?
        """, (item_id,)).fetchall()
        blocked_by = [_row_to_dict(r) for r in rows]
    conn.close()
    return {"blocks": blocks, "blocked_by": blocked_by}


def _would_create_cycle(conn, from_id: str, to_id: str) -> bool:
    """BFS from to_id following outbound deps — if we reach from_id, it's a cycle."""
    visited = set()
    queue = [to_id]
    while queue:
        current = queue.pop(0)
        if current == from_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        rows = conn.execute("SELECT to_id FROM dependencies WHERE from_id=?", (current,)).fetchall()
        queue.extend(r["to_id"] for r in rows)
    return False


# --- Bulk ---

import sqlite3

def create_work_tree(root: dict, children: list[dict] | None = None,
                     deps: list[dict] | None = None) -> dict:
    root_item = create_item(**root)
    ref_map = {"root": root_item["id"]}
    created = [root_item]
    for child in (children or []):
        ref = child.pop("ref", None)
        child["parent_id"] = root_item["id"]
        item = create_item(**child)
        if ref:
            ref_map[ref] = item["id"]
        created.append(item)
    dep_results = []
    for dep in (deps or []):
        fid = ref_map.get(dep["from"], dep["from"])
        tid = ref_map.get(dep["to"], dep["to"])
        dep_results.append(add_dependency(fid, tid))
    return {"root": root_item, "children": created[1:], "dependencies": dep_results, "ref_map": ref_map}
