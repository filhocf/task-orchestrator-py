"""Tests for resilience features: filtered export, checkpoints, integrity check."""

import os


from task_orchestrator import db, engine, checkpoints, workspace


# --- Helpers ---


def _create(title="Test Item", **kw):
    return engine.create_item(title=title, **kw)


def _setup_workspace(name, tags):
    try:
        workspace.create_workspace(name, tags=tags)
    except ValueError:
        pass


# --- Filtered Export ---


def test_export_all_no_filter():
    _create("Item A", tags="ws1")
    _create("Item B", tags="ws2")
    result = engine.export_graph()
    assert len(result["items"]) == 2
    assert result["version"] == "0.8.0"


def test_export_workspace_filter():
    _setup_workspace("dtp", ["dtp"])
    _create("Item A", tags="dtp,backend")
    _create("Item B", tags="mir,frontend")
    _create("Item C", tags="dtp,frontend")
    result = engine.export_graph(workspace="dtp")
    assert len(result["items"]) == 2
    titles = {i["title"] for i in result["items"]}
    assert titles == {"Item A", "Item C"}


def test_export_tags_filter():
    _create("Item A", tags="dtp,backend")
    _create("Item B", tags="mir,frontend")
    _create("Item C", tags="other")
    result = engine.export_graph(tags=["frontend"])
    assert len(result["items"]) == 1
    assert result["items"][0]["title"] == "Item B"


def test_export_workspace_filter_notes_and_deps():
    _setup_workspace("dtp", ["dtp"])
    a = _create("A", tags="dtp")
    b = _create("B", tags="dtp")
    c = _create("C", tags="mir")
    engine.upsert_note(a["id"], key="spec", body="hello", role="queue")
    engine.upsert_note(c["id"], key="spec", body="other", role="queue")
    engine.add_dependency(a["id"], b["id"])
    engine.add_dependency(a["id"], c["id"])
    result = engine.export_graph(workspace="dtp")
    assert len(result["notes"]) == 1
    assert result["notes"][0]["item_id"] == a["id"]
    assert len(result["dependencies"]) == 1
    assert result["dependencies"][0]["to_id"] == b["id"]


# --- Checkpoints ---


def test_create_checkpoint(tmp_path):
    _create("Item A")
    path = checkpoints.create_checkpoint(output_dir=str(tmp_path))
    assert os.path.exists(path)
    assert path.endswith(".json")
    assert "checkpoint-" in path


def test_list_checkpoints(tmp_path):
    _create("Item A")
    checkpoints.create_checkpoint(output_dir=str(tmp_path))
    checkpoints.create_checkpoint(output_dir=str(tmp_path))
    listed = checkpoints.list_checkpoints(output_dir=str(tmp_path))
    assert len(listed) == 2
    # Newest first (reverse sorted)
    assert listed[0] >= listed[1]


def test_list_checkpoints_empty(tmp_path):
    listed = checkpoints.list_checkpoints(output_dir=str(tmp_path / "nonexistent"))
    assert listed == []


def test_restore_checkpoint(tmp_path):
    _create("Item A")
    path = checkpoints.create_checkpoint(output_dir=str(tmp_path))
    # Clear DB
    conn = db.get_connection()
    conn.execute("DELETE FROM work_items")
    conn.commit()
    conn.close()
    assert engine.export_graph()["items"] == []
    # Restore
    result = checkpoints.restore_checkpoint(path)
    assert result is True
    items = engine.export_graph()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Item A"


# --- Integrity ---


def test_verify_integrity():
    result = checkpoints.verify_db_integrity()
    assert result is True
