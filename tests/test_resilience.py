"""Tests for resilience features: filtered export, checkpoints, corruption recovery."""

import json
import os

import pytest

from task_orchestrator import db, engine
from task_orchestrator import checkpoints
from task_orchestrator import workspace


# --- Helpers ---


def _create(title="Test Item", **kw):
    return engine.create_item(title=title, **kw)


def _setup_workspace(name, tags):
    """Create a workspace config for testing (idempotent)."""
    try:
        workspace.create_workspace(name, tags=tags)
    except ValueError:
        pass  # already exists


# --- Filtered Export ---


class TestFilteredExport:
    def test_export_all_no_filter(self):
        _create("Item A", tags="workspace1")
        _create("Item B", tags="workspace2")
        result = engine.export_graph()
        assert len(result["items"]) == 2

    def test_export_workspace_filter(self):
        _setup_workspace("dtp", ["dtp"])
        _create("Item A", tags="dtp,backend")
        _create("Item B", tags="mir,frontend")
        _create("Item C", tags="dtp,frontend")
        result = engine.export_graph(workspace="dtp")
        assert len(result["items"]) == 2
        titles = {i["title"] for i in result["items"]}
        assert titles == {"Item A", "Item C"}

    def test_export_tags_filter(self):
        _create("Item A", tags="dtp,backend")
        _create("Item B", tags="mir,frontend")
        result = engine.export_graph(tags=["frontend"])
        assert len(result["items"]) == 1
        assert result["items"][0]["title"] == "Item B"

    def test_export_filter_includes_notes(self):
        _setup_workspace("dtp", ["dtp"])
        item = _create("Item A", tags="dtp")
        _create("Item B", tags="mir")
        engine.upsert_note(item["id"], key="spec", body="hello", role="queue")
        result = engine.export_graph(workspace="dtp")
        assert len(result["notes"]) == 1
        assert result["notes"][0]["key"] == "spec"

    def test_export_filter_includes_deps_between_filtered_items(self):
        _setup_workspace("dtp", ["dtp"])
        a = _create("A", tags="dtp")
        b = _create("B", tags="dtp")
        c = _create("C", tags="mir")
        engine.add_dependency(a["id"], b["id"])
        engine.add_dependency(a["id"], c["id"])
        result = engine.export_graph(workspace="dtp")
        assert len(result["dependencies"]) == 1
        assert result["dependencies"][0]["from_id"] == a["id"]
        assert result["dependencies"][0]["to_id"] == b["id"]


# --- Import with Note Merge ---


class TestImportMergeNotes:
    def test_import_merge_skips_existing_items(self):
        item = _create("Existing")
        data = engine.export_graph()
        # Modify title in export data
        data["items"][0]["title"] = "Modified"
        engine.import_graph(data, mode="merge")
        # Should NOT overwrite existing item
        refreshed = engine.get_item(item["id"])
        assert refreshed["title"] == "Existing"

    def test_import_merge_updates_newer_notes(self):
        item = _create("Item")
        engine.upsert_note(item["id"], key="spec", body="old body", role="queue")
        data = engine.export_graph()
        # Simulate a newer note from another machine
        data["notes"][0]["body"] = "new body"
        data["notes"][0]["updated_at"] = "2099-01-01T00:00:00+00:00"
        engine.import_graph(data, mode="merge")
        notes = engine.get_notes(item["id"])
        assert notes[0]["body"] == "new body"

    def test_import_merge_keeps_older_notes(self):
        item = _create("Item")
        engine.upsert_note(item["id"], key="spec", body="current body", role="queue")
        data = engine.export_graph()
        # Simulate an older note
        data["notes"][0]["body"] = "stale body"
        data["notes"][0]["updated_at"] = "2000-01-01T00:00:00+00:00"
        engine.import_graph(data, mode="merge")
        notes = engine.get_notes(item["id"])
        assert notes[0]["body"] == "current body"


# --- Checkpoints ---


class TestCheckpoints:
    @pytest.fixture(autouse=True)
    def _setup_checkpoint_dir(self, tmp_path):
        checkpoints.configure(output_path=str(tmp_path / "checkpoints"))
        yield

    def test_create_checkpoint(self):
        _create("Item A")
        data = engine.export_graph()
        result = checkpoints.create_checkpoint(data)
        assert result["created"].endswith(".json")
        assert os.path.exists(result["created"])

    def test_list_checkpoints(self):
        data = engine.export_graph()
        checkpoints.create_checkpoint(data)
        checkpoints.create_checkpoint(data)
        listed = checkpoints.list_checkpoints()
        assert len(listed) == 2
        # Newest first
        assert listed[0]["filename"] >= listed[1]["filename"]

    def test_load_checkpoint(self):
        _create("Item A")
        data = engine.export_graph()
        result = checkpoints.create_checkpoint(data)
        loaded = checkpoints.load_checkpoint(result["created"])
        assert len(loaded["items"]) == 1
        assert loaded["items"][0]["title"] == "Item A"

    def test_configure(self):
        result = checkpoints.configure(interval_minutes=15)
        assert result["interval_minutes"] == 15

    def test_list_empty(self, tmp_path):
        checkpoints.configure(output_path=str(tmp_path / "nonexistent"))
        assert checkpoints.list_checkpoints() == []


# --- Corruption Detection ---


class TestCorruptionDetection:
    def test_verify_healthy_db(self):
        result = checkpoints.verify_db_integrity()
        assert result["ok"] is True

    def test_auto_recover_healthy_returns_none(self):
        result = checkpoints.auto_recover()
        assert result is None

    def test_auto_recover_from_corrupt_db(self, tmp_path):
        # Create an item and checkpoint
        _create("Important Item")
        data = engine.export_graph()
        checkpoints.configure(output_path=str(tmp_path / "checkpoints"))
        checkpoints.create_checkpoint(data)

        # Corrupt the DB
        with open(db.DB_PATH, "wb") as f:
            f.write(b"corrupted data here")

        # Auto-recover should restore
        result = checkpoints.auto_recover()
        assert result is not None
        assert result["recovered"] is True

        # Verify data is back
        items = engine.export_graph()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "Important Item"
