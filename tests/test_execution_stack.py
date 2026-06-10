"""Tests for get_execution_stack — execution frame tracking."""

import json
import pytest

from task_orchestrator import engine, workspace


@pytest.fixture(autouse=True)
def workspace_config(tmp_db, tmp_path, monkeypatch):
    """Point workspace config to temp dir."""
    ws_path = str(tmp_path / "workspaces.json")
    monkeypatch.setenv("TASK_ORCHESTRATOR_WORKSPACES", ws_path)
    return ws_path


def _create(title="Test", **kw):
    return engine.create_item(title=title, **kw)


def test_empty_stack_returns_empty_list():
    """No items in work/blocked = empty stack."""
    # Only queue items
    _create("Queued task")
    stack = engine.get_execution_stack()
    assert stack == []


def test_single_work_item_is_top_frame():
    """One item in work = stack with 1 frame (active=True)."""
    item = _create("Active task")
    engine.advance_item(item["id"], "start")  # queue -> work
    stack = engine.get_execution_stack()
    assert len(stack) == 1
    assert stack[0]["item_id"] == item["id"]
    assert stack[0]["title"] == "Active task"
    assert stack[0]["status"] == "work"
    assert stack[0]["active"] is True
    assert stack[0]["execution_state"] is None


def test_held_item_shows_as_suspended():
    """Item in blocked with execution-state note shows as suspended frame."""
    item = _create("Blocked task")
    engine.advance_item(item["id"], "start")  # queue -> work
    engine.advance_item(item["id"], "block")  # work -> blocked
    stack = engine.get_execution_stack()
    assert len(stack) == 1
    assert stack[0]["item_id"] == item["id"]
    assert stack[0]["status"] == "blocked"
    assert stack[0]["active"] is False
    assert stack[0]["held_at"] is not None


def test_nested_frames_ordered_by_depth():
    """Parent blocked + child in work = stack [parent(suspended), child(active)]."""
    parent = _create("Parent feature")
    child = _create("Child lateral", parent_id=parent["id"])
    engine.advance_item(parent["id"], "start")  # queue -> work
    engine.advance_item(parent["id"], "block")  # work -> blocked
    engine.advance_item(child["id"], "start")  # queue -> work
    stack = engine.get_execution_stack()
    assert len(stack) == 2
    # Parent suspended at depth 0, child active at depth 1
    assert stack[0]["item_id"] == parent["id"]
    assert stack[0]["active"] is False
    assert stack[0]["depth"] == 0
    assert stack[1]["item_id"] == child["id"]
    assert stack[1]["active"] is True
    assert stack[1]["depth"] == 1


def test_includes_execution_state_note():
    """Frame includes execution-state note content if it exists."""
    item = _create("Stateful task")
    engine.advance_item(item["id"], "start")
    state = json.dumps({"last_action": "wrote tests", "next": "implement"})
    engine.upsert_note(item["id"], "execution-state", state, role="work")
    stack = engine.get_execution_stack()
    assert len(stack) == 1
    assert stack[0]["execution_state"] == state


def test_workspace_filter():
    """Filters by workspace tags."""
    workspace.create_workspace("myws", ["frontend"])
    item_in = _create("FE task", tags="frontend")
    item_out = _create("BE task", tags="backend")
    engine.advance_item(item_in["id"], "start")
    engine.advance_item(item_out["id"], "start")
    stack = engine.get_execution_stack(workspace="myws")
    assert len(stack) == 1
    assert stack[0]["item_id"] == item_in["id"]
