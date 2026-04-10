"""Workflow engine — status transitions, dependency checks, queries.

Status flow: queue → work → review → done
Any non-terminal status can go to: blocked (via block trigger) → resume → previous status
Terminal statuses: done, cancelled
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from .db import get_connection
from .schemas import check_gate, should_skip_review, can_cancel, get_schema_for_item, should_auto_reopen

VALID_STATUSES = {"queue", "work", "review", "done", "blocked", "cancelled"}
TERMINAL = {"done", "cancelled"}
PRIORITIES = {"critical", "high", "medium", "low"}
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

TRANSITIONS = {
    "start": {"queue": "work", "work": "review", "review": "done"},
    "complete": {"queue": "done", "work": "done", "review": "done"},
    "block": {"queue": "blocked", "work": "blocked", "review": "blocked"},
    "cancel": {"queue": "cancelled", "work": "cancelled", "review": "cancelled", "blocked": "cancelled"},
    "reopen": {"done": "queue", "cancelled": "queue"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _row_to_dict(row) -> dict | None:
    return dict(row) if row else None


def _validate_priority(priority: str):
    if priority and priority not in PRIORITIES:
        raise ValueError(f"Invalid priority: {priority}. Valid: {sorted(PRIORITIES)}")


# --- WorkItem CRUD ---

def create_item(title: str, description: str = "", parent_id: str | None = None,
                priority: str = "medium", item_type: str = "", tags: str = "") -> dict:
    _validate_priority(priority)
    conn = get_connection()
    try:
        item_id = _uid()
        now = _now()
        if parent_id:
            parent = conn.execute("SELECT id FROM work_items WHERE id=?", (parent_id,)).fetchone()
            if not parent:
                raise ValueError(f"Parent {parent_id} not found")
            depth = _get_depth(conn, parent_id)
            if depth >= 3:
                raise ValueError(f"Max depth 4 reached (parent at depth {depth})")
        conn.execute(
            "INSERT INTO work_items (id,parent_id,title,description,status,priority,item_type,tags,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (item_id, parent_id, title, description, "queue", priority, item_type, tags, now, now),
        )
        conn.commit()
        return _row_to_dict(conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone())
    finally:
        conn.close()


def update_item(item_id: str, **fields) -> dict:
    if "priority" in fields:
        _validate_priority(fields["priority"])
    conn = get_connection()
    try:
        allowed = {"title", "description", "priority", "item_type", "tags"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            raise ValueError("No valid fields to update")
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE work_items SET {set_clause} WHERE id=?", (*updates.values(), item_id))
        conn.commit()
        row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise ValueError(f"Item {item_id} not found")
        return _row_to_dict(row)
    finally:
        conn.close()


def delete_item(item_id: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM work_items WHERE id=?", (item_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_item(item_id: str) -> dict | None:
    conn = get_connection()
    try:
        return _row_to_dict(conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone())
    finally:
        conn.close()


def query_items(status: str | None = None, parent_id: str | None = None,
                priority: str | None = None, search: str | None = None,
                limit: int = 50, offset: int = 0) -> list[dict]:
    conn = get_connection()
    try:
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
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_children(parent_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM work_items WHERE parent_id=? ORDER BY created_at", (parent_id,)).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_ancestors(item_id: str) -> list[dict]:
    """Walk up the parent chain, returning ancestors from immediate parent to root."""
    conn = get_connection()
    try:
        ancestors = []
        current = item_id
        while current:
            row = conn.execute("SELECT * FROM work_items WHERE id=?", (current,)).fetchone()
            if not row or not row["parent_id"]:
                break
            parent = conn.execute("SELECT * FROM work_items WHERE id=?", (row["parent_id"],)).fetchone()
            if parent:
                ancestors.append(_row_to_dict(parent))
                current = parent["id"]
            else:
                break
        return ancestors
    finally:
        conn.close()


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
    if trigger not in TRANSITIONS and trigger != "resume":
        raise ValueError(f"Invalid trigger: {trigger}. Valid: {list(TRANSITIONS.keys()) + ['resume']}")
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise ValueError(f"Item {item_id} not found")
        current = row["status"]

        if trigger == "resume":
            if current != "blocked":
                raise ValueError(f"Can only resume blocked items, current: {current}")
            new_status = row["previous_status"] or "work"
        elif trigger == "block":
            if current in TERMINAL or current == "blocked":
                raise ValueError(f"Cannot block from {current}")
            new_status = "blocked"
            conn.execute("UPDATE work_items SET previous_status=? WHERE id=?", (current, item_id))
        else:
            if current not in TRANSITIONS[trigger]:
                raise ValueError(f"Cannot {trigger} from {current}")
            new_status = TRANSITIONS[trigger][current]

        # Check dependencies for advancing triggers
        if trigger in ("start", "complete") and current == "queue":
            blockers = _get_unsatisfied_blockers(conn, item_id)
            if blockers:
                titles = [b["title"] for b in blockers]
                raise ValueError(f"Blocked by unfinished items: {', '.join(titles)}")

        # Check note schema gates
        if trigger in ("start", "complete"):
            item_dict = _row_to_dict(row)
            notes = [_row_to_dict(r) for r in conn.execute(
                "SELECT * FROM notes WHERE item_id=?", (item_id,)).fetchall()]
            gate = check_gate(item_dict, notes, new_status)
            if not gate["can_advance"]:
                missing_keys = [m["key"] for m in gate["missing"]]
                raise ValueError(f"Gate check failed. Missing required notes: {', '.join(missing_keys)}"
                                 + (f". Hint: {gate['guidance']}" if gate["guidance"] else ""))

        # Check cancel permission (permanent lifecycle)
        if trigger == "cancel" and not can_cancel(_row_to_dict(row)):
            raise ValueError("Cannot cancel: item has permanent lifecycle")

        # Auto-skip review for 'auto' lifecycle
        if trigger == "start" and new_status == "review" and should_skip_review(_row_to_dict(row)):
            new_status = "done"

        now = _now()
        conn.execute("UPDATE work_items SET status=?, updated_at=? WHERE id=?", (new_status, now, item_id))
        conn.commit()
        result = _row_to_dict(conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone())

        # Find items unblocked by this transition
        unblocked = []
        if new_status in TERMINAL:
            unblocked = _find_newly_unblocked(conn, item_id)
        result["unblocked_items"] = unblocked
        return result
    finally:
        conn.close()


def get_next_status(item_id: str, trigger: str) -> dict:
    """Read-only preview of what would happen with a given trigger."""
    if trigger not in TRANSITIONS and trigger != "resume":
        return {"error": f"Invalid trigger: {trigger}"}
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return {"error": f"Item {item_id} not found"}
        current = row["status"]
        if trigger == "resume":
            if current != "blocked":
                return {"can_advance": False, "reason": f"Can only resume blocked items, current: {current}"}
            return {"can_advance": True, "current": current, "next": row["previous_status"] or "work", "trigger": trigger}
        if current not in TRANSITIONS.get(trigger, {}):
            return {"can_advance": False, "reason": f"Cannot {trigger} from {current}"}
        # Check deps
        blockers = []
        if trigger in ("start", "complete") and current == "queue":
            blockers = _get_unsatisfied_blockers(conn, item_id)
        if blockers:
            return {"can_advance": False, "reason": "Blocked by dependencies",
                    "blockers": [{"id": b["id"], "title": b["title"]} for b in blockers]}
        # Check gates
        if trigger in ("start", "complete"):
            item_dict = _row_to_dict(row)
            notes = [_row_to_dict(r) for r in conn.execute(
                "SELECT * FROM notes WHERE item_id=?", (item_id,)).fetchall()]
            gate = check_gate(item_dict, notes, TRANSITIONS[trigger][current])
            if not gate["can_advance"]:
                return {"can_advance": False, "reason": "Missing required notes",
                        "missing": gate["missing"], "guidance": gate["guidance"]}
        if trigger == "cancel" and not can_cancel(_row_to_dict(row)):
            return {"can_advance": False, "reason": "Item has permanent lifecycle"}
        return {"can_advance": True, "current": current, "next": TRANSITIONS[trigger][current], "trigger": trigger}
    finally:
        conn.close()


def _get_unsatisfied_blockers(conn, item_id: str) -> list[dict]:
    """Check blockers respecting unblock_at threshold.
    Status order: queue(0) < work(1) < review(2) < done(3). cancelled counts as done."""
    status_rank = {"queue": 0, "work": 1, "review": 2, "done": 3, "cancelled": 3, "blocked": 0}
    rows = conn.execute("""
        SELECT wi.*, d.unblock_at FROM dependencies d
        JOIN work_items wi ON wi.id = d.from_id
        WHERE d.to_id = ?
    """, (item_id,)).fetchall()
    unsatisfied = []
    for r in rows:
        unblock_at = r["unblock_at"] if "unblock_at" in r.keys() else "done"
        threshold = status_rank.get(unblock_at, 3)
        current_rank = status_rank.get(r["status"], 0)
        if current_rank < threshold:
            unsatisfied.append(_row_to_dict(r))
    return unsatisfied


def _find_newly_unblocked(conn, completed_id: str) -> list[dict]:
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
    try:
        rows = conn.execute(
            "SELECT * FROM work_items WHERE status IN ('queue','work') ORDER BY status ASC, created_at ASC",
        ).fetchall()
        candidates = []
        for r in rows:
            blockers = _get_unsatisfied_blockers(conn, r["id"])
            if not blockers:
                candidates.append(_row_to_dict(r))
        candidates.sort(key=lambda x: (0 if x["status"] == "work" else 1, PRIORITY_ORDER.get(x["priority"], 2)))
        return candidates[0] if candidates else None
    finally:
        conn.close()


def get_blocked_items() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM work_items WHERE status='blocked'").fetchall()
        result = [_row_to_dict(r) for r in rows]
        # Also find queue items with unsatisfied deps
        queue_rows = conn.execute("SELECT * FROM work_items WHERE status='queue'").fetchall()
        for r in queue_rows:
            blockers = _get_unsatisfied_blockers(conn, r["id"])
            if blockers:
                item = _row_to_dict(r)
                item["blocked_by"] = [_row_to_dict(b) for b in blockers]
                result.append(item)
        return result
    finally:
        conn.close()


def get_context(item_id: str | None = None, include_ancestors: bool = False) -> dict:
    conn = get_connection()
    try:
        if item_id:
            row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
            if not row:
                raise ValueError(f"Item {item_id} not found")
            item = _row_to_dict(row)
            children = [_row_to_dict(r) for r in conn.execute(
                "SELECT * FROM work_items WHERE parent_id=?", (item_id,)).fetchall()]
            notes = [_row_to_dict(r) for r in conn.execute(
                "SELECT * FROM notes WHERE item_id=?", (item_id,)).fetchall()]
            blockers = _get_unsatisfied_blockers(conn, item_id)
            result = {"item": item, "children": children, "notes": notes,
                      "blockers": [_row_to_dict(b) for b in blockers],
                      "can_advance": len(blockers) == 0 and item["status"] not in TERMINAL}
            if include_ancestors:
                result["ancestors"] = get_ancestors(item_id)
            # Add gate info if schema exists
            if result["can_advance"]:
                next_trigger = "start"
                next_status = TRANSITIONS.get(next_trigger, {}).get(item["status"])
                if next_status:
                    gate = check_gate(item, notes, next_status)
                    result["can_advance"] = gate["can_advance"]
                    result["missing_notes"] = gate["missing"]
                    result["guidance"] = gate["guidance"]
            return result
        # Global context
        counts = {}
        for row in conn.execute("SELECT status, COUNT(*) as cnt FROM work_items GROUP BY status").fetchall():
            counts[row["status"]] = row["cnt"]
        active = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM work_items WHERE status IN ('work','review') ORDER BY updated_at DESC LIMIT 10").fetchall()]
        recent = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM work_items WHERE status IN ('done','cancelled') ORDER BY updated_at DESC LIMIT 5").fetchall()]
        blocked = get_blocked_items()
        next_item = get_next_item()
        return {"counts": counts, "active": active, "blocked": blocked,
                "recent_completed": recent, "next_item": next_item}
    finally:
        conn.close()


# --- Notes ---

def upsert_note(item_id: str, key: str, body: str, role: str = "queue") -> dict:
    conn = get_connection()
    try:
        item = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        if not item:
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
        result = _row_to_dict(conn.execute("SELECT * FROM notes WHERE item_id=? AND key=?", (item_id, key)).fetchone())
        # Auto-reopen: if item is terminal and schema has auto-reopen lifecycle
        item_dict = _row_to_dict(item)
        if item_dict["status"] in TERMINAL and should_auto_reopen(item_dict):
            conn.execute("UPDATE work_items SET status='queue', updated_at=? WHERE id=?", (now, item_id))
            conn.commit()
            result["auto_reopened"] = True
        return result
    finally:
        conn.close()


def delete_note(item_id: str, key: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM notes WHERE item_id=? AND key=?", (item_id, key))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_notes(item_id: str, include_body: bool = True) -> list[dict]:
    conn = get_connection()
    try:
        if include_body:
            rows = conn.execute("SELECT * FROM notes WHERE item_id=? ORDER BY created_at", (item_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, item_id, key, role, created_at, updated_at FROM notes WHERE item_id=? ORDER BY created_at",
                (item_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# --- Dependencies ---

def add_dependency(from_id: str, to_id: str, dep_type: str = "blocks",
                   unblock_at: str = "done") -> dict:
    """Add dependency. unblock_at: status at which the blocker unblocks (default: done).
    Valid: done, review, work (unblocks when blocker reaches that status or beyond)."""
    if from_id == to_id:
        raise ValueError("Cannot depend on self")
    valid_unblock = {"done", "review", "work"}
    if unblock_at not in valid_unblock:
        raise ValueError(f"Invalid unblock_at: {unblock_at}. Valid: {sorted(valid_unblock)}")
    conn = get_connection()
    try:
        for fid in (from_id, to_id):
            if not conn.execute("SELECT id FROM work_items WHERE id=?", (fid,)).fetchone():
                raise ValueError(f"Item {fid} not found")
        if _would_create_cycle(conn, from_id, to_id):
            raise ValueError("Dependency would create a cycle")
        dep_id = _uid()
        now = _now()
        try:
            conn.execute("INSERT INTO dependencies (id,from_id,to_id,dep_type,unblock_at,created_at) VALUES (?,?,?,?,?,?)",
                          (dep_id, from_id, to_id, dep_type, unblock_at, now))
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"Dependency {from_id} → {to_id} already exists")
        return _row_to_dict(conn.execute("SELECT * FROM dependencies WHERE id=?", (dep_id,)).fetchone())
    finally:
        conn.close()


def add_dependency_pattern(item_ids: list[str], pattern: str = "linear") -> list[dict]:
    """Create dependencies using pattern shortcuts: linear, fan-out, fan-in."""
    if len(item_ids) < 2:
        raise ValueError("Need at least 2 items for a dependency pattern")
    results = []
    if pattern == "linear":
        for i in range(len(item_ids) - 1):
            results.append(add_dependency(item_ids[i], item_ids[i + 1]))
    elif pattern == "fan-out":
        source = item_ids[0]
        for target in item_ids[1:]:
            results.append(add_dependency(source, target))
    elif pattern == "fan-in":
        target = item_ids[-1]
        for source in item_ids[:-1]:
            results.append(add_dependency(source, target))
    else:
        raise ValueError(f"Invalid pattern: {pattern}. Valid: linear, fan-out, fan-in")
    return results


def remove_dependency(from_id: str, to_id: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM dependencies WHERE from_id=? AND to_id=?", (from_id, to_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_dependencies(item_id: str, direction: str = "both") -> dict:
    conn = get_connection()
    try:
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
        return {"blocks": blocks, "blocked_by": blocked_by}
    finally:
        conn.close()


def query_dependencies_bfs(item_id: str, direction: str = "outbound", max_depth: int = 10) -> list[dict]:
    """BFS traversal of dependency graph."""
    conn = get_connection()
    try:
        visited = set()
        result = []
        queue = [(item_id, 0)]
        while queue:
            current, depth = queue.pop(0)
            if current in visited or depth > max_depth:
                continue
            visited.add(current)
            if direction == "outbound":
                rows = conn.execute("""
                    SELECT d.*, wi.title, wi.status, wi.priority
                    FROM dependencies d JOIN work_items wi ON wi.id=d.to_id WHERE d.from_id=?
                """, (current,)).fetchall()
                for r in rows:
                    item = _row_to_dict(r)
                    item["depth"] = depth + 1
                    result.append(item)
                    queue.append((r["to_id"], depth + 1))
            else:
                rows = conn.execute("""
                    SELECT d.*, wi.title, wi.status, wi.priority
                    FROM dependencies d JOIN work_items wi ON wi.id=d.from_id WHERE d.to_id=?
                """, (current,)).fetchall()
                for r in rows:
                    item = _row_to_dict(r)
                    item["depth"] = depth + 1
                    result.append(item)
                    queue.append((r["from_id"], depth + 1))
        return result
    finally:
        conn.close()


def _would_create_cycle(conn, from_id: str, to_id: str) -> bool:
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


def complete_tree(parent_id: str) -> dict:
    """Batch-complete all non-terminal descendants in topological order."""
    conn = get_connection()
    try:
        # Get all descendants
        def _get_all_descendants(pid):
            items = []
            rows = conn.execute("SELECT * FROM work_items WHERE parent_id=?", (pid,)).fetchall()
            for r in rows:
                items.append(_row_to_dict(r))
                items.extend(_get_all_descendants(r["id"]))
            return items

        descendants = _get_all_descendants(parent_id)
        completed = []
        skipped = []
        for item in descendants:
            if item["status"] in TERMINAL:
                skipped.append({"id": item["id"], "title": item["title"], "status": item["status"]})
                continue
            try:
                result = advance_item(item["id"], "complete")
                completed.append({"id": item["id"], "title": item["title"], "new_status": result["status"]})
            except ValueError as e:
                skipped.append({"id": item["id"], "title": item["title"], "reason": str(e)})
        return {"completed": completed, "skipped": skipped}
    finally:
        conn.close()
