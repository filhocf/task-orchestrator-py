"""Comprehensive tests for task_orchestrator.engine."""

from datetime import datetime, timezone, timedelta

import pytest

from task_orchestrator import db, engine
from task_orchestrator.engine import ToolError


# --- Helpers ---


def _create(title="Test Item", **kw):
    return engine.create_item(title=title, **kw)


# --- CRUD ---


def test_create_item():
    item = _create("My Task", description="desc", priority="high")
    assert item["id"]
    assert item["title"] == "My Task"
    assert item["description"] == "desc"
    assert item["status"] == "queue"
    assert item["priority"] == "high"


def test_create_item_with_parent():
    parent = _create("Parent")
    child = _create("Child", parent_id=parent["id"])
    assert child["parent_id"] == parent["id"]
    children = engine.get_children(parent["id"])
    assert len(children) == 1
    assert children[0]["id"] == child["id"]


def test_create_item_max_depth():
    l1 = _create("L1")
    l2 = _create("L2", parent_id=l1["id"])
    l3 = _create("L3", parent_id=l2["id"])
    l4 = _create("L4", parent_id=l3["id"])
    # Depth 4 reached — L4 is at depth 3 (0-indexed), so creating child should fail
    with pytest.raises(ToolError, match="Max depth 4"):
        _create("L5", parent_id=l4["id"])


def test_update_item():
    item = _create("Original")
    updated = engine.update_item(
        item["id"], title="Updated", description="new desc", priority="critical"
    )
    assert updated["title"] == "Updated"
    assert updated["description"] == "new desc"
    assert updated["priority"] == "critical"


def test_delete_item():
    item = _create("To Delete")
    result = engine.delete_item(item["id"])
    assert result["deleted"] is True
    assert engine.get_item(item["id"]) is None


def test_delete_item_recursive():
    parent = _create("Parent")
    _create("Child1", parent_id=parent["id"])
    _create("Child2", parent_id=parent["id"])
    result = engine.delete_item(parent["id"], recursive=True)
    assert result["deleted"] is True
    assert result["descendants_deleted"] == 2
    assert engine.get_item(parent["id"]) is None


# --- Query ---


def test_query_items_by_status():
    a = _create("A")
    _create("B")
    engine.advance_item(a["id"], "start")  # queue -> work
    items = engine.query_items(status="work")
    assert len(items) == 1
    assert items[0]["id"] == a["id"]


def test_query_items_by_priority():
    _create("Low", priority="low")
    _create("High", priority="high")
    items = engine.query_items(priority="high")
    assert len(items) == 1
    assert items[0]["priority"] == "high"


def test_query_items_by_tags():
    _create("Tagged", tags="frontend,urgent")
    _create("Other", tags="backend")
    items = engine.query_items(tags="frontend")
    assert len(items) == 1
    assert "frontend" in items[0]["tags"]


def test_query_items_search():
    _create("Build the API")
    _create("Write docs")
    items = engine.query_items(search="API")
    assert len(items) == 1
    assert "API" in items[0]["title"]


# --- Workflow ---


def test_advance_item_workflow():
    item = _create("Flow")
    r = engine.advance_item(item["id"], "start")
    assert r["status"] == "work"
    r = engine.advance_item(item["id"], "start")
    assert r["status"] == "review"
    r = engine.advance_item(item["id"], "start")
    assert r["status"] == "done"


def test_advance_item_complete_shortcut():
    item = _create("Quick")
    r = engine.advance_item(item["id"], "complete")
    assert r["status"] == "done"


def test_advance_item_block_resume():
    item = _create("Blockable")
    engine.advance_item(item["id"], "start")  # -> work
    r = engine.advance_item(item["id"], "block")
    assert r["status"] == "blocked"
    r = engine.advance_item(item["id"], "resume")
    assert r["status"] == "work"


def test_advance_item_cancel_reopen():
    item = _create("Cancelable")
    r = engine.advance_item(item["id"], "cancel")
    assert r["status"] == "cancelled"
    r = engine.advance_item(item["id"], "reopen")
    assert r["status"] == "queue"


def test_batch_transitions():
    a = _create("A")
    b = _create("B")
    result = engine.advance_items_batch(
        [
            {"item_id": a["id"], "trigger": "start"},
            {"item_id": b["id"], "trigger": "complete"},
        ]
    )
    assert result["summary"]["succeeded"] == 2
    assert result["summary"]["failed"] == 0
    assert result["results"][0]["new_status"] == "work"
    assert result["results"][1]["new_status"] == "done"


# --- Dependencies ---


def test_dependencies_add_query():
    a = _create("A")
    b = _create("B")
    dep = engine.add_dependency(a["id"], b["id"])
    assert dep["from_id"] == a["id"]
    assert dep["to_id"] == b["id"]
    deps = engine.get_dependencies(b["id"], direction="inbound")
    assert len(deps["blocked_by"]) == 1
    deps = engine.get_dependencies(a["id"], direction="outbound")
    assert len(deps["blocks"]) == 1


def test_dependencies_linear_pattern():
    items = [_create(f"Item{i}") for i in range(3)]
    ids = [it["id"] for it in items]
    deps = engine.add_dependency_pattern(ids, "linear")
    assert len(deps) == 2
    assert deps[0]["from_id"] == ids[0]
    assert deps[0]["to_id"] == ids[1]
    assert deps[1]["from_id"] == ids[1]
    assert deps[1]["to_id"] == ids[2]


def test_dependencies_fan_out():
    items = [_create(f"Item{i}") for i in range(3)]
    ids = [it["id"] for it in items]
    deps = engine.add_dependency_pattern(ids, "fan-out")
    assert len(deps) == 2
    assert all(d["from_id"] == ids[0] for d in deps)


def test_dependencies_block_advance():
    a = _create("Blocker")
    b = _create("Blocked")
    engine.add_dependency(a["id"], b["id"])
    with pytest.raises(ToolError, match="Blocked by unfinished"):
        engine.advance_item(b["id"], "start")


def test_dependencies_unblock_at():
    a = _create("Blocker")
    b = _create("Blocked")
    engine.add_dependency(a["id"], b["id"], unblock_at="work")
    # a is in queue, b can't advance
    with pytest.raises(ToolError, match="Blocked by unfinished"):
        engine.advance_item(b["id"], "start")
    # Move a to work — now b should be unblocked
    engine.advance_item(a["id"], "start")
    r = engine.advance_item(b["id"], "start")
    assert r["status"] == "work"


# --- Notes ---


def test_notes_upsert_query():
    item = _create("Noted")
    note = engine.upsert_note(item["id"], "requirements", "Must do X", role="queue")
    assert note["key"] == "requirements"
    assert note["body"] == "Must do X"
    notes = engine.get_notes(item["id"])
    assert len(notes) == 1
    assert notes[0]["key"] == "requirements"


def test_notes_delete():
    item = _create("Noted")
    engine.upsert_note(item["id"], "temp", "temporary")
    assert engine.delete_note(item["id"], "temp") is True
    assert len(engine.get_notes(item["id"])) == 0


# --- Work Tree ---


def test_create_work_tree():
    result = engine.create_work_tree(
        root={"title": "Root"},
        children=[
            {"ref": "a", "title": "Child A"},
            {"ref": "b", "title": "Child B"},
        ],
        deps=[{"from": "a", "to": "b"}],
    )
    assert result["root"]["title"] == "Root"
    assert len(result["children"]) == 2
    assert len(result["dependencies"]) == 1
    assert "a" in result["ref_map"]
    assert "b" in result["ref_map"]


def test_complete_tree():
    parent = _create("Parent")
    c1 = _create("C1", parent_id=parent["id"])
    c2 = _create("C2", parent_id=parent["id"])
    result = engine.complete_tree(parent["id"])
    assert len(result["completed"]) == 2
    assert engine.get_item(c1["id"])["status"] == "done"
    assert engine.get_item(c2["id"])["status"] == "done"


# --- Context ---


def test_get_context_global():
    _create("A")
    _create("B")
    ctx = engine.get_context()
    assert "counts" in ctx
    assert ctx["counts"].get("queue", 0) >= 2
    assert "active" in ctx
    assert "blocked" in ctx
    assert "stale_items" in ctx


def test_get_context_item():
    parent = _create("Parent")
    _create("Child", parent_id=parent["id"])
    engine.upsert_note(parent["id"], "note1", "body")
    ctx = engine.get_context(item_id=parent["id"])
    assert ctx["item"]["id"] == parent["id"]
    assert len(ctx["children"]) == 1
    assert len(ctx["notes"]) == 1
    assert "can_advance" in ctx


# --- Next Item / Blocked ---


def test_get_next_item():
    _create("Low", priority="low")
    _create("Critical", priority="critical")
    nxt = engine.get_next_item()
    assert nxt is not None
    assert nxt["priority"] == "critical"


def test_get_blocked_items():
    a = _create("Blocker")
    b = _create("Blocked")
    engine.add_dependency(a["id"], b["id"])
    blocked = engine.get_blocked_items()
    blocked_ids = [it["id"] for it in blocked]
    assert b["id"] in blocked_ids


# --- Short Hex ID ---


def test_short_hex_id():
    item = _create("Resolvable")
    prefix = item["id"][:8]
    resolved = engine.resolve_short_id(prefix)
    assert resolved == item["id"]


def test_short_hex_id_ambiguous():
    # Create two items and try a 1-char prefix (too short anyway)
    # But for ambiguity, we need 4+ chars matching multiple items.
    # Since UUIDs are random, we test the validation path instead.
    with pytest.raises(ToolError, match="at least 4 characters"):
        engine.resolve_short_id("ab")


def test_short_hex_id_not_found():
    with pytest.raises(ToolError, match="No item matching"):
        engine.resolve_short_id("zzzzzzzz")


# --- ToolError ---


def test_tool_error():
    err = ToolError("VALIDATION", "bad input", field="title")
    assert err.code == "VALIDATION"
    assert err.field == "title"
    assert err.message == "bad input"
    d = err.to_dict()
    assert d["error"]["code"] == "VALIDATION"
    assert d["error"]["field"] == "title"
    assert d["error"]["message"] == "bad input"


# --- Stale Detection ---


def test_stale_detection():
    item = _create("Old Item")
    # Manually backdate updated_at to 10 days ago
    conn = db.get_connection()
    try:
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        conn.execute(
            "UPDATE work_items SET updated_at=? WHERE id=?", (old_date, item["id"])
        )
        conn.commit()
    finally:
        conn.close()
    ctx = engine.get_context()
    stale_ids = [s["id"] for s in ctx["stale_items"]]
    assert item["id"] in stale_ids


# --- Additional edge cases ---


def test_delete_item_with_children_no_recursive():
    parent = _create("Parent")
    _create("Child", parent_id=parent["id"])
    with pytest.raises(ToolError, match="Use recursive=true"):
        engine.delete_item(parent["id"], recursive=False)


def test_advance_invalid_trigger():
    item = _create("Item")
    with pytest.raises(ToolError, match="Invalid trigger"):
        engine.advance_item(item["id"], "invalid_trigger")


def test_dependencies_self_reference():
    item = _create("Self")
    with pytest.raises(ToolError, match="Cannot depend on self"):
        engine.add_dependency(item["id"], item["id"])


def test_get_ancestors():
    l1 = _create("L1")
    l2 = _create("L2", parent_id=l1["id"])
    l3 = _create("L3", parent_id=l2["id"])
    ancestors = engine.get_ancestors(l3["id"])
    assert len(ancestors) == 2
    assert ancestors[0]["id"] == l2["id"]
    assert ancestors[1]["id"] == l1["id"]


def test_notes_upsert_update():
    item = _create("Noted")
    engine.upsert_note(item["id"], "key1", "v1")
    updated = engine.upsert_note(item["id"], "key1", "v2")
    assert updated["body"] == "v2"
    assert len(engine.get_notes(item["id"])) == 1


# --- Due Dates ---


def test_create_item_with_due_date():
    due = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    item = _create("Due Soon", due_at=due)
    assert item["due_at"] == due


def test_due_soon_detection():
    due = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
    item = _create("Due Soon", due_at=due)
    ctx = engine.get_context()
    due_soon_ids = [i["id"] for i in ctx["due_soon"]]
    assert item["id"] in due_soon_ids


def test_overdue_detection():
    due = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    item = _create("Overdue", due_at=due)
    ctx = engine.get_context()
    overdue_ids = [i["id"] for i in ctx["overdue"]]
    assert item["id"] in overdue_ids


# --- Export / Import ---


def test_export_graph():
    a = _create("A")
    b = _create("B")
    engine.upsert_note(a["id"], "req", "requirement body", role="queue")
    engine.add_dependency(a["id"], b["id"])
    data = engine.export_graph()
    assert data["version"] == "0.7.0"
    assert "exported_at" in data
    assert len(data["items"]) >= 2
    assert len(data["notes"]) >= 1
    assert len(data["dependencies"]) >= 1
    ids = [i["id"] for i in data["items"]]
    assert a["id"] in ids
    assert b["id"] in ids


def test_import_merge():
    a = _create("A")
    b = _create("B")
    engine.upsert_note(a["id"], "req", "body")
    engine.add_dependency(a["id"], b["id"])
    data = engine.export_graph()
    # Delete item b (cascade removes dep too)
    engine.delete_item(b["id"])
    assert engine.get_item(b["id"]) is None
    # Merge import should restore b and the dependency
    result = engine.import_graph(data, mode="merge")
    assert result["imported"] is True
    assert result["mode"] == "merge"
    assert engine.get_item(b["id"]) is not None
    assert result["counts"]["items"] >= 2
    assert result["counts"]["dependencies"] >= 1


def test_import_replace():
    a = _create("A")
    b = _create("B")
    engine.upsert_note(a["id"], "req", "body")
    data = engine.export_graph()
    # Create extra item not in export
    c = _create("C")
    result = engine.import_graph(data, mode="replace")
    assert result["imported"] is True
    assert result["mode"] == "replace"
    # C should be gone, only A and B remain
    assert engine.get_item(c["id"]) is None
    assert engine.get_item(a["id"]) is not None
    assert engine.get_item(b["id"]) is not None
    assert result["counts"]["items"] == 2


# --- FTS Search ---


def test_fts_search_description():
    """FTS5 finds items by description content."""
    _create("Generic Title", description="quantum entanglement research")
    items = engine.query_items(search="entanglement")
    assert len(items) == 1
    assert "entanglement" in items[0]["description"]


def test_fts_search_notes():
    """Search finds items via notes body content."""
    item = _create("Plain Item")
    engine.upsert_note(item["id"], "details", "flux capacitor specs")
    items = engine.query_items(search="capacitor")
    assert len(items) == 1
    assert items[0]["id"] == item["id"]


def test_fts_search_partial():
    """FTS5 prefix search matches partial terms."""
    _create("Implement authentication module")
    items = engine.query_items(search="authent")
    assert len(items) == 1
    assert "authentication" in items[0]["title"]


# --- Scheduled Items ---


def test_scheduled_item_create():
    item = _create("Daily Standup", schedule="0 9 * * *")
    assert item["schedule"] == "0 9 * * *"
    assert item["next_run_at"] is not None


def test_scheduled_item_requeues():
    item = _create("Recurring", schedule="0 9 * * *")
    r = engine.advance_item(item["id"], "complete")
    assert r["status"] == "queue"
    assert r["next_run_at"] is not None
    assert r["previous_status"] is None


def test_non_scheduled_stays_done():
    item = _create("One-off")
    r = engine.advance_item(item["id"], "complete")
    assert r["status"] == "done"


def test_scheduled_upcoming():
    item = _create("Soon", schedule="* * * * *")
    ctx = engine.get_context()
    upcoming_ids = [i["id"] for i in ctx["scheduled_upcoming"]]
    assert item["id"] in upcoming_ids


def test_scheduled_item_waits_for_next_run():
    """Completed scheduled item should NOT be returned by get_next_item immediately."""
    item = _create("Recurring", schedule="0 9 * * *")
    r = engine.advance_item(item["id"], "complete")
    assert r["status"] == "queue"
    assert r["next_run_at"] is not None
    nxt = engine.get_next_item()
    assert nxt is None or nxt["id"] != item["id"]


def test_invalid_cron_expression():
    """Invalid cron expression should raise VALIDATION error."""
    with pytest.raises(ToolError, match="Invalid cron expression"):
        _create("Bad Cron", schedule="not a cron")


# --- Metrics ---


def test_metrics_basic():
    """Create items in various states, verify metric counts."""
    # done items
    for p in ("critical", "high", "medium"):
        item = _create(f"Done-{p}", priority=p, tags="frontend,api")
        engine.advance_item(item["id"], "complete")
    # work item (WIP)
    wip = _create("WIP", tags="backend")
    engine.advance_item(wip["id"], "start")
    # queue item (stale — backdate)
    stale = _create("Stale")
    conn = db.get_connection()
    try:
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        conn.execute(
            "UPDATE work_items SET updated_at=? WHERE id=?", (old, stale["id"])
        )
        conn.commit()
    finally:
        conn.close()

    m = engine.get_metrics(days=30)
    assert m["period_days"] == 30
    assert m["total_items"] == 5
    assert m["wip"] == 1
    assert m["by_priority"]["critical"] == 1
    assert m["by_priority"]["high"] == 1
    assert m["by_priority"]["medium"] == 1
    assert m["by_priority"]["low"] == 0
    assert m["lead_time_avg_seconds"] >= 0
    assert m["stale_ratio"] > 0  # 1 stale out of 2 non-terminal
    # by_tag: backend and frontend should appear (from non-terminal items)
    assert "backend" in m["by_tag"]


def test_metrics_throughput():
    """Create done items, verify weekly breakdown."""
    now = datetime.now(timezone.utc)
    conn = db.get_connection()
    try:
        for i in range(3):
            item = _create(f"T-{i}")
            engine.advance_item(item["id"], "complete")
            # Ensure all land in the same ISO week (now)
    finally:
        conn.close()

    m = engine.get_metrics(days=30)
    assert len(m["throughput_per_week"]) >= 1
    total_throughput = sum(w["count"] for w in m["throughput_per_week"])
    assert total_throughput >= 3
    # Verify week format
    for entry in m["throughput_per_week"]:
        assert entry["week"].startswith(str(now.year))
        assert "-W" in entry["week"]
        assert isinstance(entry["count"], int)


# --- _parse_dt helper ---


def test_parse_dt_aware():
    dt = engine._parse_dt("2026-05-03T12:00:00+00:00")
    assert dt.tzinfo is not None


def test_parse_dt_naive_assumes_utc():
    dt = engine._parse_dt("2026-05-03 12:00:00")
    assert dt.tzinfo == timezone.utc


def test_get_context_with_naive_timestamps():
    """get_context should not crash when items have naive datetime strings."""
    item = _create("Naive TS item")
    # Manually set created_at/updated_at to naive format (simulating old/imported data)
    conn = db.get_connection()
    conn.execute(
        "UPDATE work_items SET created_at='2026-01-01 00:00:00', updated_at='2026-01-01 00:00:00' WHERE id=?",
        (item["id"],),
    )
    conn.commit()
    conn.close()
    # Should not raise "can't subtract offset-naive and offset-aware datetimes"
    ctx = engine.get_context()
    assert "counts" in ctx


def test_get_metrics_with_naive_timestamps():
    """get_metrics should not crash when done items have naive datetime strings."""
    item = _create("Naive metrics item")
    engine.advance_item(item["id"], "complete")
    conn = db.get_connection()
    conn.execute(
        "UPDATE work_items SET created_at='2026-01-01 00:00:00', updated_at='2026-05-03 00:00:00' WHERE id=?",
        (item["id"],),
    )
    conn.commit()
    conn.close()
    metrics = engine.get_metrics(days=365)
    assert metrics["lead_time_avg_seconds"] > 0
