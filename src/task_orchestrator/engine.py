"""Workflow engine — status transitions, dependency checks, queries.

Status flow: queue → work → review → done
Any non-terminal status can go to: blocked (via block trigger) → resume → previous status
Terminal statuses: done, cancelled
"""

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta

from .db import get_connection
from .schemas import (
    check_gate,
    should_skip_review,
    can_cancel,
    get_schema_for_item,
    should_auto_reopen,
)

from croniter import croniter, CroniterBadCronError

from .workspace import get_workspace_tags

VALID_STATUSES = {"queue", "work", "review", "done", "blocked", "cancelled"}


class ToolError(Exception):
    """Structured error with code, field, and message."""

    CODES = {
        "NOT_FOUND",
        "VALIDATION",
        "CONFLICT",
        "DEPENDENCY_UNSATISFIED",
        "GATE_BLOCKED",
    }

    def __init__(self, code: str, message: str, field: str = ""):
        self.code = code
        self.field = field
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        d = {"error": {"code": self.code, "message": self.message}}
        if self.field:
            d["error"]["field"] = self.field
        return d


def resolve_short_id(prefix: str) -> str:
    """Resolve a 4+ char hex prefix to a full item ID."""
    if len(prefix) < 4:
        raise ToolError("VALIDATION", "Short ID must be at least 4 characters", "id")
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM work_items WHERE id LIKE ?", (f"{prefix}%",)
        ).fetchall()
        if len(rows) == 0:
            raise ToolError("NOT_FOUND", f"No item matching prefix '{prefix}'", "id")
        if len(rows) > 1:
            ids = [r["id"] for r in rows]
            raise ToolError(
                "CONFLICT", f"Prefix '{prefix}' matches {len(ids)} items: {ids}", "id"
            )
        return rows[0]["id"]
    finally:
        conn.close()


TERMINAL = {"done", "cancelled"}
PRIORITIES = {"critical", "high", "medium", "low"}
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

TRANSITIONS = {
    "start": {"queue": "work", "work": "review", "review": "done"},
    "complete": {"queue": "done", "work": "done", "review": "done"},
    "block": {"queue": "blocked", "work": "blocked", "review": "blocked"},
    "cancel": {
        "queue": "cancelled",
        "work": "cancelled",
        "review": "cancelled",
        "blocked": "cancelled",
    },
    "reopen": {"done": "queue", "cancelled": "queue"},
}


def _parse_dt(s: str) -> datetime:
    """Parse ISO datetime string, assuming UTC if no timezone info."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


def _row_to_dict(row) -> dict | None:
    return dict(row) if row else None


def _validate_priority(priority: str):
    if priority and priority not in PRIORITIES:
        raise ToolError(
            "VALIDATION",
            f"Invalid priority: {priority}. Valid: {sorted(PRIORITIES)}",
            "priority",
        )


def _validate_due_at(due_at: str | None):
    if due_at is not None:
        try:
            datetime.fromisoformat(due_at)
        except (ValueError, TypeError):
            raise ToolError(
                "VALIDATION",
                f"Invalid due_at: {due_at}. Must be ISO 8601 datetime string.",
                "due_at",
            )


def _workspace_tag_filter(workspace: str | None) -> tuple[str, list[str]]:
    """Return (SQL clause, params) to filter items by workspace tags. Empty if no workspace."""
    if not workspace:
        return "", []
    tags = get_workspace_tags(workspace)
    if tags is None:
        raise ToolError("NOT_FOUND", f"Workspace '{workspace}' not found", "workspace")
    clauses = " OR ".join("tags LIKE ?" for _ in tags)
    return f"({clauses})", [f"%{t}%" for t in tags]


# --- WorkItem CRUD ---


def create_item(
    title: str,
    description: str = "",
    summary: str = "",
    parent_id: str | None = None,
    priority: str = "medium",
    complexity: int | None = None,
    item_type: str = "",
    tags: str = "",
    metadata: str | None = None,
    properties: str | None = None,
    due_at: str | None = None,
    schedule: str | None = None,
) -> dict:
    _validate_priority(priority)
    _validate_due_at(due_at)
    if complexity is not None and not (1 <= complexity <= 10):
        raise ToolError(
            "VALIDATION", f"Complexity must be 1-10, got {complexity}", "complexity"
        )
    conn = get_connection()
    try:
        item_id = _uid()
        now = _now()
        if parent_id:
            parent = conn.execute(
                "SELECT id FROM work_items WHERE id=?", (parent_id,)
            ).fetchone()
            if not parent:
                raise ToolError(
                    "NOT_FOUND", f"Parent {parent_id} not found", "parent_id"
                )
            depth = _get_depth(conn, parent_id)
            if depth >= 3:
                raise ToolError(
                    "VALIDATION",
                    f"Max depth 4 reached (parent at depth {depth})",
                    "parent_id",
                )
        next_run_at = None
        if schedule:
            try:
                next_run_at = (
                    croniter(schedule, datetime.now(timezone.utc))
                    .get_next(datetime)
                    .isoformat()
                )
            except CroniterBadCronError:
                raise ToolError(
                    "VALIDATION", f"Invalid cron expression: {schedule}", "schedule"
                )
        conn.execute(
            """INSERT INTO work_items (id,parent_id,title,description,summary,status,priority,
               complexity,item_type,tags,metadata,properties,role_changed_at,due_at,schedule,next_run_at,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item_id,
                parent_id,
                title,
                description,
                summary,
                "queue",
                priority,
                complexity,
                item_type,
                tags,
                metadata,
                properties,
                now,
                due_at,
                schedule,
                next_run_at,
                now,
                now,
            ),
        )
        conn.commit()
        return _row_to_dict(
            conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        )
    finally:
        conn.close()


def create_items_batch(items: list[dict], parent_id: str | None = None) -> dict:
    """Batch create multiple items. Returns created items and failure count."""
    created = []
    failed = 0
    for item in items:
        try:
            pid = item.pop("parent_id", None) or parent_id
            result = create_item(parent_id=pid, **item)
            created.append(result)
        except Exception:
            failed += 1
    return {"items": created, "created": len(created), "failed": failed}


def update_item(item_id: str, **fields) -> dict:
    if "priority" in fields:
        _validate_priority(fields["priority"])
    if "due_at" in fields:
        _validate_due_at(fields["due_at"])
    if "complexity" in fields and fields["complexity"] is not None:
        if not (1 <= fields["complexity"] <= 10):
            raise ToolError(
                "VALIDATION",
                f"Complexity must be 1-10, got {fields['complexity']}",
                "complexity",
            )
    conn = get_connection()
    try:
        allowed = {
            "title",
            "description",
            "summary",
            "priority",
            "complexity",
            "item_type",
            "tags",
            "metadata",
            "properties",
            "due_at",
            "schedule",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            raise ToolError("VALIDATION", "No valid fields to update")
        if "schedule" in updates:
            try:
                updates["next_run_at"] = (
                    croniter(updates["schedule"], datetime.now(timezone.utc))
                    .get_next(datetime)
                    .isoformat()
                )
            except CroniterBadCronError:
                raise ToolError(
                    "VALIDATION",
                    f"Invalid cron expression: {updates['schedule']}",
                    "schedule",
                )
        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE work_items SET {set_clause} WHERE id=?",
            (*updates.values(), item_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise ToolError("NOT_FOUND", f"Item {item_id} not found", "item_id")
        return _row_to_dict(row)
    finally:
        conn.close()


def delete_item(item_id: str, recursive: bool = False) -> dict:
    conn = get_connection()
    try:
        descendants_deleted = 0
        if recursive:
            descendants_deleted = _delete_descendants(conn, item_id)
        else:
            child_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM work_items WHERE parent_id=?", (item_id,)
            ).fetchone()["cnt"]
            if child_count > 0:
                raise ToolError(
                    "VALIDATION",
                    f"Item has {child_count} children. Use recursive=true to delete them.",
                    "item_id",
                )
        cur = conn.execute("DELETE FROM work_items WHERE id=?", (item_id,))
        conn.commit()
        result = {"deleted": cur.rowcount > 0}
        if recursive:
            result["descendants_deleted"] = descendants_deleted
        return result
    finally:
        conn.close()


def delete_items_batch(ids: list[str], recursive: bool = False) -> dict:
    """Batch delete multiple items."""
    total_deleted = 0
    total_descendants = 0
    failed = 0
    for item_id in ids:
        try:
            result = delete_item(item_id, recursive=recursive)
            if result.get("deleted"):
                total_deleted += 1
            total_descendants += result.get("descendants_deleted", 0)
        except Exception:
            failed += 1
    result = {"deleted": total_deleted, "failed": failed}
    if recursive:
        result["descendants_deleted"] = total_descendants
    return result


def _delete_descendants(conn, parent_id: str) -> int:
    """Recursively delete all descendants, returns count deleted."""
    children = conn.execute(
        "SELECT id FROM work_items WHERE parent_id=?", (parent_id,)
    ).fetchall()
    count = 0
    for child in children:
        count += _delete_descendants(conn, child["id"])
    cur = conn.execute("DELETE FROM work_items WHERE parent_id=?", (parent_id,))
    count += cur.rowcount
    return count


def get_item(item_id: str) -> dict | None:
    conn = get_connection()
    try:
        return _row_to_dict(
            conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        )
    finally:
        conn.close()


def query_items(
    status: str | None = None,
    parent_id: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    tags: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
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
        if tags:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            tag_clauses = ["tags LIKE ?" for _ in tag_list]
            clauses.append(f"({' OR '.join(tag_clauses)})")
            params.extend([f"%{t}%" for t in tag_list])

        if search:
            # FTS5 match on title/description + LIKE on notes body, deduplicated
            fts_ids = _fts_search(conn, search)
            note_rows = conn.execute(
                "SELECT DISTINCT item_id FROM notes WHERE body LIKE ?",
                (f"%{search}%",),
            ).fetchall()
            matched_ids = list(fts_ids | {r["item_id"] for r in note_rows})
            if not matched_ids:
                return []
            # Batch IN clause in chunks of 500 to avoid SQLITE_LIMIT_VARIABLE_NUMBER
            id_clauses = []
            for i in range(0, len(matched_ids), 500):
                chunk = matched_ids[i : i + 500]
                id_clauses.append(f"id IN ({','.join('?' for _ in chunk)})")
                params.extend(chunk)
            clauses.append(f"({' OR '.join(id_clauses)})")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM work_items {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _fts_search(conn, search: str) -> set[str]:
    """Search FTS5 index with MATCH, fallback to LIKE on failure."""
    try:
        fts_term = search.replace('"', '""')
        rows = conn.execute(
            "SELECT id FROM items_fts WHERE items_fts MATCH ?",
            (f'"{fts_term}" OR {fts_term}*',),
        ).fetchall()
        return {r["id"] for r in rows}
    except Exception:
        rows = conn.execute(
            "SELECT id FROM work_items WHERE title LIKE ? OR description LIKE ?",
            (f"%{search}%", f"%{search}%"),
        ).fetchall()
        return {r["id"] for r in rows}


def get_children(parent_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM work_items WHERE parent_id=? ORDER BY created_at",
            (parent_id,),
        ).fetchall()
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
            row = conn.execute(
                "SELECT * FROM work_items WHERE id=?", (current,)
            ).fetchone()
            if not row or not row["parent_id"]:
                break
            parent = conn.execute(
                "SELECT * FROM work_items WHERE id=?", (row["parent_id"],)
            ).fetchone()
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
        row = conn.execute(
            "SELECT parent_id FROM work_items WHERE id=?", (current,)
        ).fetchone()
        if not row or not row["parent_id"]:
            break
        current = row["parent_id"]
        depth += 1
    return depth


# --- Workflow ---


def advance_item(item_id: str, trigger: str) -> dict:
    if trigger not in TRANSITIONS and trigger not in ("resume", "hold"):
        raise ToolError(
            "VALIDATION",
            f"Invalid trigger: {trigger}. Valid: {list(TRANSITIONS.keys()) + ['resume', 'hold']}",
            "trigger",
        )
    # hold is alias for block
    if trigger == "hold":
        trigger = "block"
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise ToolError("NOT_FOUND", f"Item {item_id} not found", "item_id")
        current = row["status"]

        if trigger == "resume":
            if current != "blocked":
                raise ToolError(
                    "CONFLICT",
                    f"Can only resume blocked items, current: {current}",
                    "trigger",
                )
            new_status = row["previous_status"] or "work"
        elif trigger == "block":
            if current in TERMINAL or current == "blocked":
                raise ToolError("CONFLICT", f"Cannot block from {current}", "trigger")
            new_status = "blocked"
            conn.execute(
                "UPDATE work_items SET previous_status=? WHERE id=?", (current, item_id)
            )
        else:
            if current not in TRANSITIONS[trigger]:
                raise ToolError(
                    "CONFLICT", f"Cannot {trigger} from {current}", "trigger"
                )
            new_status = TRANSITIONS[trigger][current]

        # Check dependencies for advancing triggers
        if trigger in ("start", "complete") and current == "queue":
            blockers = _get_unsatisfied_blockers(conn, item_id)
            if blockers:
                titles = [b["title"] for b in blockers]
                raise ToolError(
                    "DEPENDENCY_UNSATISFIED",
                    f"Blocked by unfinished items: {', '.join(titles)}",
                    "item_id",
                )

        # Check note schema gates
        if trigger in ("start", "complete"):
            item_dict = _row_to_dict(row)
            notes = [
                _row_to_dict(r)
                for r in conn.execute(
                    "SELECT * FROM notes WHERE item_id=?", (item_id,)
                ).fetchall()
            ]
            gate = check_gate(item_dict, notes, new_status)
            if not gate["can_advance"]:
                missing_keys = [m["key"] for m in gate["missing"]]
                raise ToolError(
                    "GATE_BLOCKED",
                    f"Missing required notes: {', '.join(missing_keys)}"
                    + (f". Hint: {gate['guidance']}" if gate["guidance"] else ""),
                    "item_id",
                )

        # Check cancel permission (permanent lifecycle)
        if trigger == "cancel" and not can_cancel(_row_to_dict(row)):
            raise ToolError(
                "CONFLICT", "Cannot cancel: item has permanent lifecycle", "trigger"
            )

        # Auto-skip review for 'auto' lifecycle
        if (
            trigger == "start"
            and new_status == "review"
            and should_skip_review(_row_to_dict(row))
        ):
            new_status = "done"

        now = _now()
        status_label = "cancelled" if trigger == "cancel" else None
        conn.execute(
            "UPDATE work_items SET status=?, status_label=?, role_changed_at=?, updated_at=? WHERE id=?",
            (new_status, status_label, now, now, item_id),
        )
        conn.commit()

        # Scheduled item requeue: if completing and item has a schedule, requeue it
        if new_status == "done" and row["schedule"]:
            new_next_run = (
                croniter(row["schedule"], datetime.now(timezone.utc))
                .get_next(datetime)
                .isoformat()
            )
            conn.execute(
                "UPDATE work_items SET status='queue', previous_status=NULL, next_run_at=?, updated_at=? WHERE id=?",
                (new_next_run, now, item_id),
            )
            conn.commit()

        result = _row_to_dict(
            conn.execute("SELECT * FROM work_items WHERE id=?", (item_id,)).fetchone()
        )

        # Find items unblocked by this transition
        unblocked = []
        if new_status in TERMINAL:
            unblocked = _find_newly_unblocked(conn, item_id)

        # Reopen cascade: if reopening, cascade parent from terminal to work
        if trigger == "reopen" and row["parent_id"]:
            parent = conn.execute(
                "SELECT * FROM work_items WHERE id=?", (row["parent_id"],)
            ).fetchone()
            if parent and parent["status"] in TERMINAL:
                conn.execute(
                    "UPDATE work_items SET status='work', status_label=NULL, role_changed_at=?, updated_at=? WHERE id=?",
                    (now, now, parent["id"]),
                )
                conn.commit()
                result["parent_reopened"] = True

        result["unblocked_items"] = unblocked
        return result
    finally:
        conn.close()


def advance_items_batch(transitions: list[dict]) -> dict:
    """Batch advance multiple items. Each entry: {item_id, trigger}."""
    results = []
    all_unblocked = []
    succeeded = 0
    failed = 0
    for t in transitions:
        try:
            result = advance_item(t["item_id"], t["trigger"])
            results.append(
                {
                    "item_id": t["item_id"],
                    "trigger": t["trigger"],
                    "applied": True,
                    "new_status": result["status"],
                }
            )
            all_unblocked.extend(result.get("unblocked_items", []))
            succeeded += 1
        except (ValueError, ToolError) as e:
            results.append(
                {
                    "item_id": t["item_id"],
                    "trigger": t["trigger"],
                    "applied": False,
                    "error": str(e),
                }
            )
            failed += 1
    return {
        "results": results,
        "summary": {
            "total": len(transitions),
            "succeeded": succeeded,
            "failed": failed,
        },
        "all_unblocked_items": all_unblocked,
    }


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
                return {
                    "can_advance": False,
                    "reason": f"Can only resume blocked items, current: {current}",
                }
            return {
                "can_advance": True,
                "current": current,
                "next": row["previous_status"] or "work",
                "trigger": trigger,
            }
        if current not in TRANSITIONS.get(trigger, {}):
            return {"can_advance": False, "reason": f"Cannot {trigger} from {current}"}
        # Check deps
        blockers = []
        if trigger in ("start", "complete") and current == "queue":
            blockers = _get_unsatisfied_blockers(conn, item_id)
        if blockers:
            return {
                "can_advance": False,
                "reason": "Blocked by dependencies",
                "blockers": [{"id": b["id"], "title": b["title"]} for b in blockers],
            }
        # Check gates
        if trigger in ("start", "complete"):
            item_dict = _row_to_dict(row)
            notes = [
                _row_to_dict(r)
                for r in conn.execute(
                    "SELECT * FROM notes WHERE item_id=?", (item_id,)
                ).fetchall()
            ]
            gate = check_gate(item_dict, notes, TRANSITIONS[trigger][current])
            if not gate["can_advance"]:
                return {
                    "can_advance": False,
                    "reason": "Missing required notes",
                    "missing": gate["missing"],
                    "guidance": gate["guidance"],
                }
        if trigger == "cancel" and not can_cancel(_row_to_dict(row)):
            return {"can_advance": False, "reason": "Item has permanent lifecycle"}
        return {
            "can_advance": True,
            "current": current,
            "next": TRANSITIONS[trigger][current],
            "trigger": trigger,
        }
    finally:
        conn.close()


def _get_unsatisfied_blockers(conn, item_id: str) -> list[dict]:
    """Check blockers respecting unblock_at threshold. Ignores relates_to deps.
    Status order: queue(0) < work(1) < review(2) < done(3). cancelled counts as done."""
    status_rank = {
        "queue": 0,
        "work": 1,
        "review": 2,
        "done": 3,
        "cancelled": 3,
        "blocked": 0,
    }
    rows = conn.execute(
        """
        SELECT wi.*, d.unblock_at, d.dep_type FROM dependencies d
        JOIN work_items wi ON wi.id = d.from_id
        WHERE d.to_id = ?
    """,
        (item_id,),
    ).fetchall()
    unsatisfied = []
    for r in rows:
        dep_type = r["dep_type"] if "dep_type" in r.keys() else "blocks"
        if dep_type == "relates_to":
            continue
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
            row = conn.execute(
                "SELECT * FROM work_items WHERE id=?", (dep["to_id"],)
            ).fetchone()
            if row and row["status"] not in TERMINAL:
                unblocked.append(_row_to_dict(row))
    return unblocked


def _get_items_by_due_date(conn, mode: str, now_dt: datetime) -> list[dict]:
    """Get items by due date. mode: 'due_soon' (next 24h) or 'overdue' (past due)."""
    now_iso = now_dt.isoformat()
    if mode == "due_soon":
        cutoff = (now_dt + timedelta(hours=24)).isoformat()
        rows = conn.execute(
            "SELECT * FROM work_items WHERE due_at IS NOT NULL AND due_at > ? AND due_at <= ? AND status NOT IN ('done','cancelled')",
            (now_iso, cutoff),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM work_items WHERE due_at IS NOT NULL AND due_at <= ? AND status NOT IN ('done','cancelled')",
            (now_iso,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _get_scheduled_upcoming(conn, now_dt: datetime) -> list[dict]:
    """Items with next_run_at within next 24h."""
    cutoff = (now_dt + timedelta(hours=24)).isoformat()
    rows = conn.execute(
        "SELECT * FROM work_items WHERE next_run_at IS NOT NULL AND next_run_at <= ?",
        (cutoff,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_next_item(workspace: str | None = None) -> dict | None:
    conn = get_connection()
    try:
        ws_clause, ws_params = _workspace_tag_filter(workspace)
        where = "WHERE status IN ('queue','work')"
        if ws_clause:
            where += f" AND {ws_clause}"
        rows = conn.execute(
            f"SELECT * FROM work_items {where} ORDER BY status ASC, created_at ASC",
            ws_params,
        ).fetchall()
        now_iso = _now()
        candidates = []
        for r in rows:
            blockers = _get_unsatisfied_blockers(conn, r["id"])
            if not blockers:
                item = _row_to_dict(r)
                # Skip scheduled items whose next_run_at is in the future
                if item.get("next_run_at") and item["next_run_at"] > now_iso:
                    continue
                candidates.append(item)

        def _sort_key(x):
            overdue = 1
            if x.get("due_at") and x["due_at"] <= now_iso:
                overdue = 0
            return (
                overdue,
                0 if x["status"] == "work" else 1,
                PRIORITY_ORDER.get(x["priority"], 2),
            )

        candidates.sort(key=_sort_key)
        return candidates[0] if candidates else None
    finally:
        conn.close()


def get_blocked_items() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM work_items WHERE status='blocked'"
        ).fetchall()
        result = [_row_to_dict(r) for r in rows]
        # Also find queue items with unsatisfied deps
        queue_rows = conn.execute(
            "SELECT * FROM work_items WHERE status='queue'"
        ).fetchall()
        for r in queue_rows:
            blockers = _get_unsatisfied_blockers(conn, r["id"])
            if blockers:
                item = _row_to_dict(r)
                item["blocked_by"] = [_row_to_dict(b) for b in blockers]
                result.append(item)
        return result
    finally:
        conn.close()


def get_context(
    item_id: str | None = None,
    include_ancestors: bool = False,
    workspace: str | None = None,
) -> dict:
    conn = get_connection()
    try:
        if item_id:
            row = conn.execute(
                "SELECT * FROM work_items WHERE id=?", (item_id,)
            ).fetchone()
            if not row:
                raise ToolError("NOT_FOUND", f"Item {item_id} not found", "item_id")
            item = _row_to_dict(row)
            children = [
                _row_to_dict(r)
                for r in conn.execute(
                    "SELECT * FROM work_items WHERE parent_id=?", (item_id,)
                ).fetchall()
            ]
            notes = [
                _row_to_dict(r)
                for r in conn.execute(
                    "SELECT * FROM notes WHERE item_id=?", (item_id,)
                ).fetchall()
            ]
            blockers = _get_unsatisfied_blockers(conn, item_id)
            result = {
                "item": item,
                "children": children,
                "notes": notes,
                "blockers": [_row_to_dict(b) for b in blockers],
                "can_advance": len(blockers) == 0 and item["status"] not in TERMINAL,
            }
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
        ws_clause, ws_params = _workspace_tag_filter(workspace)
        ws_where = f"WHERE {ws_clause}" if ws_clause else ""
        ws_and = f"AND {ws_clause}" if ws_clause else ""

        counts = {}
        for row in conn.execute(
            f"SELECT status, COUNT(*) as cnt FROM work_items {ws_where} GROUP BY status",
            ws_params,
        ).fetchall():
            counts[row["status"]] = row["cnt"]
        active = [
            _row_to_dict(r)
            for r in conn.execute(
                f"SELECT * FROM work_items WHERE status IN ('work','review') {ws_and} ORDER BY updated_at DESC LIMIT 10",
                ws_params,
            ).fetchall()
        ]
        recent = [
            _row_to_dict(r)
            for r in conn.execute(
                f"SELECT * FROM work_items WHERE status IN ('done','cancelled') {ws_and} ORDER BY updated_at DESC LIMIT 5",
                ws_params,
            ).fetchall()
        ]
        blocked = get_blocked_items()
        next_item = get_next_item(workspace=workspace)
        # Stale item detection
        now_dt = datetime.now(timezone.utc)
        stale_items = []
        for row in conn.execute(
            f"SELECT * FROM work_items WHERE status IN ('queue','work') {ws_and}",
            ws_params,
        ).fetchall():
            item = _row_to_dict(row)
            updated = _parse_dt(item["updated_at"])
            days = (now_dt - updated).days
            if (item["status"] == "queue" and days > 7) or (
                item["status"] == "work" and days > 3
            ):
                item["stale_days"] = days
                stale_items.append(item)
        return {
            "counts": counts,
            "active": active,
            "blocked": blocked,
            "recent_completed": recent,
            "next_item": next_item,
            "stale_items": stale_items,
            "due_soon": _get_items_by_due_date(conn, "due_soon", now_dt),
            "overdue": _get_items_by_due_date(conn, "overdue", now_dt),
            "scheduled_upcoming": _get_scheduled_upcoming(conn, now_dt),
        }
    finally:
        conn.close()


# --- Notes ---


def upsert_note(item_id: str, key: str, body: str, role: str = "queue") -> dict:
    conn = get_connection()
    try:
        item = conn.execute(
            "SELECT * FROM work_items WHERE id=?", (item_id,)
        ).fetchone()
        if not item:
            raise ToolError("NOT_FOUND", f"Item {item_id} not found", "item_id")
        now = _now()
        existing = conn.execute(
            "SELECT id FROM notes WHERE item_id=? AND key=?", (item_id, key)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE notes SET body=?, role=?, updated_at=? WHERE id=?",
                (body, role, now, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO notes (id,item_id,key,role,body,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (_uid(), item_id, key, role, body, now, now),
            )
        conn.commit()
        result = _row_to_dict(
            conn.execute(
                "SELECT * FROM notes WHERE item_id=? AND key=?", (item_id, key)
            ).fetchone()
        )
        # Auto-reopen: if item is terminal and schema has auto-reopen lifecycle
        item_dict = _row_to_dict(item)
        if item_dict["status"] in TERMINAL and should_auto_reopen(item_dict):
            conn.execute(
                "UPDATE work_items SET status='queue', updated_at=? WHERE id=?",
                (now, item_id),
            )
            conn.commit()
            result["auto_reopened"] = True
        return result
    finally:
        conn.close()


def delete_note(item_id: str, key: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM notes WHERE item_id=? AND key=?", (item_id, key)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_notes(item_id: str, include_body: bool = True) -> list[dict]:
    conn = get_connection()
    try:
        if include_body:
            rows = conn.execute(
                "SELECT * FROM notes WHERE item_id=? ORDER BY created_at", (item_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, item_id, key, role, created_at, updated_at FROM notes WHERE item_id=? ORDER BY created_at",
                (item_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# --- Dependencies ---


def add_dependency(
    from_id: str, to_id: str, dep_type: str = "blocks", unblock_at: str = "done"
) -> dict:
    """Add dependency. dep_type: blocks, is_blocked_by, relates_to.
    unblock_at: status at which the blocker unblocks (default: done).
    Valid: done, review, work. RELATES_TO deps cannot have unblock_at."""
    if from_id == to_id:
        raise ToolError("VALIDATION", "Cannot depend on self", "from_id")
    valid_types = {"blocks", "is_blocked_by", "relates_to"}
    dep_type = dep_type.lower().replace("-", "_")
    if dep_type not in valid_types:
        raise ToolError(
            "VALIDATION",
            f"Invalid dep_type: {dep_type}. Valid: {sorted(valid_types)}",
            "dep_type",
        )
    if dep_type == "relates_to" and unblock_at != "done":
        raise ToolError(
            "VALIDATION",
            "RELATES_TO dependencies cannot have unblock_at threshold",
            "unblock_at",
        )
    valid_unblock = {"done", "review", "work"}
    if unblock_at not in valid_unblock:
        raise ToolError(
            "VALIDATION",
            f"Invalid unblock_at: {unblock_at}. Valid: {sorted(valid_unblock)}",
            "unblock_at",
        )
    # IS_BLOCKED_BY is stored as BLOCKS with swapped direction
    if dep_type == "is_blocked_by":
        from_id, to_id = to_id, from_id
        dep_type = "blocks"
    conn = get_connection()
    try:
        for fid in (from_id, to_id):
            if not conn.execute(
                "SELECT id FROM work_items WHERE id=?", (fid,)
            ).fetchone():
                raise ToolError("NOT_FOUND", f"Item {fid} not found", "from_id")
        if dep_type != "relates_to" and _would_create_cycle(conn, from_id, to_id):
            raise ToolError("CONFLICT", "Dependency would create a cycle", "from_id")
        dep_id = _uid()
        now = _now()
        try:
            conn.execute(
                "INSERT INTO dependencies (id,from_id,to_id,dep_type,unblock_at,created_at) VALUES (?,?,?,?,?,?)",
                (dep_id, from_id, to_id, dep_type, unblock_at, now),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ToolError(
                "CONFLICT", f"Dependency {from_id} → {to_id} already exists", "from_id"
            )
        return _row_to_dict(
            conn.execute("SELECT * FROM dependencies WHERE id=?", (dep_id,)).fetchone()
        )
    finally:
        conn.close()


def add_dependency_pattern(item_ids: list[str], pattern: str = "linear") -> list[dict]:
    """Create dependencies using pattern shortcuts: linear, fan-out, fan-in."""
    if len(item_ids) < 2:
        raise ToolError(
            "VALIDATION", "Need at least 2 items for a dependency pattern", "item_ids"
        )
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
        raise ToolError(
            "VALIDATION",
            f"Invalid pattern: {pattern}. Valid: linear, fan-out, fan-in",
            "pattern",
        )
    return results


def remove_dependency(from_id: str, to_id: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM dependencies WHERE from_id=? AND to_id=?", (from_id, to_id)
        )
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
            rows = conn.execute(
                """
                SELECT d.*, wi.title as to_title, wi.status as to_status
                FROM dependencies d JOIN work_items wi ON wi.id=d.to_id WHERE d.from_id=?
            """,
                (item_id,),
            ).fetchall()
            blocks = [_row_to_dict(r) for r in rows]
        if direction in ("inbound", "both"):
            rows = conn.execute(
                """
                SELECT d.*, wi.title as from_title, wi.status as from_status
                FROM dependencies d JOIN work_items wi ON wi.id=d.from_id WHERE d.to_id=?
            """,
                (item_id,),
            ).fetchall()
            blocked_by = [_row_to_dict(r) for r in rows]
        return {"blocks": blocks, "blocked_by": blocked_by}
    finally:
        conn.close()


def query_dependencies_bfs(
    item_id: str, direction: str = "outbound", max_depth: int = 10
) -> list[dict]:
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
                rows = conn.execute(
                    """
                    SELECT d.*, wi.title, wi.status, wi.priority
                    FROM dependencies d JOIN work_items wi ON wi.id=d.to_id WHERE d.from_id=?
                """,
                    (current,),
                ).fetchall()
                for r in rows:
                    item = _row_to_dict(r)
                    item["depth"] = depth + 1
                    result.append(item)
                    queue.append((r["to_id"], depth + 1))
            else:
                rows = conn.execute(
                    """
                    SELECT d.*, wi.title, wi.status, wi.priority
                    FROM dependencies d JOIN work_items wi ON wi.id=d.from_id WHERE d.to_id=?
                """,
                    (current,),
                ).fetchall()
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
        rows = conn.execute(
            "SELECT to_id FROM dependencies WHERE from_id=?", (current,)
        ).fetchall()
        queue.extend(r["to_id"] for r in rows)
    return False


# --- Bulk ---


def create_work_tree(
    root: dict,
    children: list[dict] | None = None,
    deps: list[dict] | None = None,
    create_notes: bool = False,
) -> dict:
    root_item = create_item(**root)
    ref_map = {"root": root_item["id"]}
    created = [root_item]
    for child in children or []:
        ref = child.pop("ref", None)
        child["parent_id"] = root_item["id"]
        item = create_item(**child)
        if ref:
            ref_map[ref] = item["id"]
        created.append(item)
    dep_results = []
    for dep in deps or []:
        fid = ref_map.get(dep["from"], dep["from"])
        tid = ref_map.get(dep["to"], dep["to"])
        dep_results.append(
            add_dependency(
                fid,
                tid,
                dep_type=dep.get("type", "blocks"),
                unblock_at=dep.get("unblock_at", "done"),
            )
        )
    # Auto-create blank notes from schemas
    notes_created = []
    if create_notes:
        for item in created:
            schema = get_schema_for_item(
                item.get("item_type", ""), item.get("tags", "")
            )
            if schema:
                for note_def in schema["notes"]:
                    note = upsert_note(
                        item["id"], note_def["key"], "", note_def["role"]
                    )
                    notes_created.append(
                        {
                            "item_id": item["id"],
                            "key": note_def["key"],
                            "role": note_def["role"],
                            "id": note["id"],
                        }
                    )
    return {
        "root": root_item,
        "children": created[1:],
        "dependencies": dep_results,
        "ref_map": ref_map,
        "notes": notes_created,
    }


def complete_tree(parent_id: str) -> dict:
    """Batch-complete all non-terminal descendants in topological order."""
    conn = get_connection()
    try:
        # Get all descendants
        def _get_all_descendants(pid):
            items = []
            rows = conn.execute(
                "SELECT * FROM work_items WHERE parent_id=?", (pid,)
            ).fetchall()
            for r in rows:
                items.append(_row_to_dict(r))
                items.extend(_get_all_descendants(r["id"]))
            return items

        descendants = _get_all_descendants(parent_id)
        completed = []
        skipped = []
        for item in descendants:
            if item["status"] in TERMINAL:
                skipped.append(
                    {"id": item["id"], "title": item["title"], "status": item["status"]}
                )
                continue
            try:
                result = advance_item(item["id"], "complete")
                completed.append(
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "new_status": result["status"],
                    }
                )
            except ValueError as e:
                skipped.append(
                    {"id": item["id"], "title": item["title"], "reason": str(e)}
                )
        return {"completed": completed, "skipped": skipped}
    finally:
        conn.close()


# --- Metrics ---


def get_metrics(days: int = 30, workspace: str | None = None) -> dict:
    """Work metrics: throughput, lead time, WIP, stale ratio, breakdowns."""
    conn = get_connection()
    try:
        ws_clause, ws_params = _workspace_tag_filter(workspace)
        ws_and = f"AND {ws_clause}" if ws_clause else ""

        now_dt = datetime.now(timezone.utc)
        cutoff = (now_dt - timedelta(days=days)).isoformat()
        stale_cutoff = (now_dt - timedelta(days=7)).isoformat()

        # Throughput per week (done items in period, grouped by ISO week)
        rows = conn.execute(
            f"SELECT updated_at FROM work_items WHERE status='done' AND updated_at >= ? {ws_and}",
            [cutoff] + ws_params,
        ).fetchall()
        week_counts: dict[str, int] = {}
        for r in rows:
            dt = _parse_dt(r["updated_at"])
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
            week_counts[key] = week_counts.get(key, 0) + 1
        throughput = [{"week": w, "count": c} for w, c in sorted(week_counts.items())]

        # Lead time avg (done items in period)
        lt_rows = conn.execute(
            f"SELECT created_at, updated_at FROM work_items WHERE status='done' AND updated_at >= ? {ws_and}",
            [cutoff] + ws_params,
        ).fetchall()
        if lt_rows:
            total_secs = sum(
                (
                    _parse_dt(r["updated_at"]) - _parse_dt(r["created_at"])
                ).total_seconds()
                for r in lt_rows
            )
            lead_time_avg = total_secs / len(lt_rows)
        else:
            lead_time_avg = 0.0

        # WIP
        wip = conn.execute(
            f"SELECT COUNT(*) as cnt FROM work_items WHERE status='work' {ws_and}",
            ws_params,
        ).fetchone()["cnt"]

        # Stale ratio
        non_terminal = conn.execute(
            f"SELECT COUNT(*) as cnt FROM work_items WHERE status NOT IN ('done','cancelled') {ws_and}",
            ws_params,
        ).fetchone()["cnt"]
        stale = conn.execute(
            f"SELECT COUNT(*) as cnt FROM work_items WHERE status NOT IN ('done','cancelled') AND updated_at < ? {ws_and}",
            [stale_cutoff] + ws_params,
        ).fetchone()["cnt"]
        stale_ratio = (stale / non_terminal * 100) if non_terminal else 0.0

        # By priority (done in period)
        by_priority = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for r in conn.execute(
            f"SELECT priority, COUNT(*) as cnt FROM work_items WHERE status='done' AND updated_at >= ? {ws_and} GROUP BY priority",
            [cutoff] + ws_params,
        ).fetchall():
            if r["priority"] in by_priority:
                by_priority[r["priority"]] = r["cnt"]

        # By tag (top 10 tags across non-terminal items)
        tag_counts: dict[str, int] = {}
        for r in conn.execute(
            f"SELECT tags FROM work_items WHERE status NOT IN ('done','cancelled') AND tags != '' {ws_and}",
            ws_params,
        ).fetchall():
            for tag in r["tags"].split(","):
                tag = tag.strip()
                if tag:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
        by_tag = dict(sorted(tag_counts.items(), key=lambda x: -x[1])[:10])

        # Total items
        ws_where = f"WHERE {ws_clause}" if ws_clause else ""
        total = conn.execute(
            f"SELECT COUNT(*) as cnt FROM work_items {ws_where}", ws_params
        ).fetchone()["cnt"]

        return {
            "throughput_per_week": throughput,
            "lead_time_avg_seconds": lead_time_avg,
            "wip": wip,
            "stale_ratio": stale_ratio,
            "by_priority": by_priority,
            "by_tag": by_tag,
            "total_items": total,
            "period_days": days,
        }
    finally:
        conn.close()


# --- Export / Import ---


def export_graph(workspace: str | None = None, tags: list[str] | None = None) -> dict:
    """Export items, notes, and dependencies as a JSON-serializable dict.

    If workspace or tags are provided, only items matching those tags are exported
    (along with their notes and dependencies between them).
    No filter = export all (backward compatible).
    """
    conn = get_connection()
    try:
        if tags:
            # Direct tag filter
            all_items = [
                _row_to_dict(r)
                for r in conn.execute("SELECT * FROM work_items").fetchall()
            ]
            items = [
                i
                for i in all_items
                if i.get("tags") and any(t in i["tags"].split(",") for t in tags)
            ]
        elif workspace:
            # Use same _workspace_tag_filter pattern as get_context
            ws_clause, ws_params = _workspace_tag_filter(workspace)
            items = [
                _row_to_dict(r)
                for r in conn.execute(
                    f"SELECT * FROM work_items WHERE {ws_clause}", ws_params
                ).fetchall()
            ]
        else:
            items = None

        if items is not None:
            item_ids = {i["id"] for i in items}
            notes = [
                _row_to_dict(r)
                for r in conn.execute("SELECT * FROM notes").fetchall()
                if r["item_id"] in item_ids
            ]
            deps = [
                _row_to_dict(r)
                for r in conn.execute("SELECT * FROM dependencies").fetchall()
                if r["from_id"] in item_ids and r["to_id"] in item_ids
            ]
        else:
            items = [
                _row_to_dict(r)
                for r in conn.execute("SELECT * FROM work_items").fetchall()
            ]
            notes = [
                _row_to_dict(r) for r in conn.execute("SELECT * FROM notes").fetchall()
            ]
            deps = [
                _row_to_dict(r)
                for r in conn.execute("SELECT * FROM dependencies").fetchall()
            ]
        return {
            "items": items,
            "notes": notes,
            "dependencies": deps,
            "exported_at": _now(),
            "version": "0.8.0",
        }
    finally:
        conn.close()


def _get_table_columns(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _insert_rows(conn, table: str, rows: list[dict]):
    if not rows:
        return
    columns = _get_table_columns(conn, table)
    cols = [c for c in columns if c in rows[0]]
    placeholders = ",".join("?" for _ in cols)
    col_names = ",".join(cols)
    values = [tuple(row.get(c) for c in cols) for row in rows]
    conn.executemany(
        f"INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})", values
    )


def _sort_items_by_depth(items: list[dict]) -> list[dict]:
    """Sort items so parents come before children (parent_id=NULL first)."""
    parents = [i for i in items if not i.get("parent_id")]
    children = [i for i in items if i.get("parent_id")]
    return parents + children


def import_graph(data: dict, mode: str = "merge") -> dict:
    """Import items, notes, and dependencies from an exported dict.

    mode='merge': insert rows that don't exist (skip on conflict).
                  For notes, updates body if incoming note is newer.
    mode='replace': delete everything first, then insert all.
    """
    if mode not in ("merge", "replace"):
        raise ToolError(
            "VALIDATION", f"Invalid mode: {mode}. Valid: merge, replace", "mode"
        )
    conn = get_connection()
    try:
        if mode == "replace":
            conn.execute("DELETE FROM dependencies")
            conn.execute("DELETE FROM notes")
            conn.execute("DELETE FROM work_items")
            conn.commit()
        # Sort items: parents first, then children (topological order)
        sorted_items = _sort_items_by_depth(data.get("items", []))
        _insert_rows(conn, "work_items", sorted_items)

        # Notes: merge if newer
        if mode == "merge":
            _merge_notes(conn, data.get("notes", []))
        else:
            _insert_rows(conn, "notes", data.get("notes", []))

        _insert_rows(conn, "dependencies", data.get("dependencies", []))
        conn.commit()
        counts = {
            "items": conn.execute("SELECT COUNT(*) as c FROM work_items").fetchone()[
                "c"
            ],
            "notes": conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"],
            "dependencies": conn.execute(
                "SELECT COUNT(*) as c FROM dependencies"
            ).fetchone()["c"],
        }
        return {"imported": True, "mode": mode, "counts": counts}
    finally:
        conn.close()


def _merge_notes(conn, notes: list[dict]):
    """Insert new notes, update existing ones if incoming is newer."""
    columns = _get_table_columns(conn, "notes")
    for note in notes:
        existing = conn.execute(
            "SELECT updated_at FROM notes WHERE item_id = ? AND key = ?",
            (note.get("item_id"), note.get("key")),
        ).fetchone()
        if existing is None:
            # Insert new note
            cols = [c for c in columns if c in note]
            placeholders = ",".join("?" for _ in cols)
            col_names = ",".join(cols)
            conn.execute(
                f"INSERT OR IGNORE INTO notes ({col_names}) VALUES ({placeholders})",
                tuple(note.get(c) for c in cols),
            )
        elif note.get("updated_at", "") > (existing["updated_at"] or ""):
            # Update if incoming is newer
            conn.execute(
                "UPDATE notes SET body = ?, updated_at = ? WHERE item_id = ? AND key = ?",
                (
                    note.get("body", ""),
                    note.get("updated_at"),
                    note.get("item_id"),
                    note.get("key"),
                ),
            )
