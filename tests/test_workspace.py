"""Tests for workspace entity and scoped queries."""

import json
import pytest

from task_orchestrator import db
from task_orchestrator import engine
from task_orchestrator import workspace


@pytest.fixture(autouse=True)
def workspace_config(tmp_db, tmp_path, monkeypatch):
    """Point workspace config to temp dir."""
    ws_path = str(tmp_path / "workspaces.json")
    monkeypatch.setenv("TASK_ORCHESTRATOR_WORKSPACES", ws_path)
    return ws_path


class TestWorkspaceCRUD:
    def test_create_and_list(self):
        workspace.create_workspace("dtp", ["mir", "rer"], ["mir"])
        result = workspace.list_workspaces()
        assert "dtp" in result
        assert result["dtp"]["tags"] == ["mir", "rer"]
        assert result["dtp"]["memory_tags"] == ["mir"]

    def test_create_duplicate_raises(self):
        workspace.create_workspace("dtp", ["mir"])
        with pytest.raises(ValueError, match="already exists"):
            workspace.create_workspace("dtp", ["rer"])

    def test_update(self):
        workspace.create_workspace("dtp", ["mir"])
        workspace.update_workspace("dtp", tags=["mir", "rer"])
        result = workspace.list_workspaces()
        assert result["dtp"]["tags"] == ["mir", "rer"]

    def test_update_nonexistent_raises(self):
        with pytest.raises(ValueError, match="not found"):
            workspace.update_workspace("nope", tags=["x"])

    def test_delete(self):
        workspace.create_workspace("dtp", ["mir"])
        workspace.delete_workspace("dtp")
        assert workspace.list_workspaces() == {}

    def test_delete_nonexistent_raises(self):
        with pytest.raises(ValueError, match="not found"):
            workspace.delete_workspace("nope")

    def test_get_workspace_tags(self):
        workspace.create_workspace("dtp", ["mir", "rer"])
        assert workspace.get_workspace_tags("dtp") == ["mir", "rer"]
        assert workspace.get_workspace_tags("nope") is None


class TestScopedQueries:
    def _create_items(self):
        """Create items in different workspaces."""
        workspace.create_workspace("dtp", ["mir", "rer"])
        workspace.create_workspace("pessoal", ["papo-saude"])

        engine.create_item(title="MIR task", tags="mir")
        engine.create_item(title="RER task", tags="rer")
        engine.create_item(title="Personal task", tags="papo-saude")
        engine.create_item(title="Untagged task")

    def test_get_context_no_workspace_returns_all(self):
        self._create_items()
        ctx = engine.get_context()
        assert ctx["counts"]["queue"] == 4

    def test_get_context_with_workspace_filters(self):
        self._create_items()
        ctx = engine.get_context(workspace="dtp")
        assert ctx["counts"]["queue"] == 2

    def test_get_context_workspace_not_found(self):
        with pytest.raises(engine.ToolError, match="not found"):
            engine.get_context(workspace="nonexistent")

    def test_get_next_item_no_workspace(self):
        self._create_items()
        item = engine.get_next_item()
        assert item is not None

    def test_get_next_item_with_workspace(self):
        self._create_items()
        item = engine.get_next_item(workspace="pessoal")
        assert item is not None
        assert "papo-saude" in item["tags"]

    def test_get_next_item_workspace_empty(self):
        workspace.create_workspace("empty", ["no-such-tag"])
        engine.create_item(title="Some task", tags="other")
        item = engine.get_next_item(workspace="empty")
        assert item is None

    def test_get_metrics_no_workspace(self):
        self._create_items()
        metrics = engine.get_metrics()
        assert metrics["total_items"] == 4

    def test_get_metrics_with_workspace(self):
        self._create_items()
        metrics = engine.get_metrics(workspace="dtp")
        assert metrics["total_items"] == 2

    def test_get_metrics_workspace_not_found(self):
        with pytest.raises(engine.ToolError, match="not found"):
            engine.get_metrics(workspace="nonexistent")
