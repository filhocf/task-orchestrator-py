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


class TestWorkspaceExtendedFields:
    def test_create_with_all_fields(self):
        workspace.create_workspace(
            "dtp",
            ["mir", "rer"],
            memory_tags=["mir", "dtp"],
            repos=["~/git/mir"],
            conventions="Python 3.11+, pytest",
            description="Work projects",
        )
        result = workspace.list_workspaces()
        assert result["dtp"]["repos"] == ["~/git/mir"]
        assert result["dtp"]["conventions"] == "Python 3.11+, pytest"
        assert result["dtp"]["description"] == "Work projects"

    def test_create_minimal_omits_optional(self):
        workspace.create_workspace("minimal", ["tag1"])
        result = workspace.list_workspaces()
        assert "repos" not in result["minimal"]
        assert "conventions" not in result["minimal"]
        assert "description" not in result["minimal"]

    def test_update_description(self):
        workspace.create_workspace("dtp", ["mir"])
        workspace.update_workspace("dtp", description="Updated")
        result = workspace.list_workspaces()
        assert result["dtp"]["description"] == "Updated"

    def test_update_repos(self):
        workspace.create_workspace("dtp", ["mir"])
        workspace.update_workspace("dtp", repos=["~/git/a", "~/git/b"])
        result = workspace.list_workspaces()
        assert result["dtp"]["repos"] == ["~/git/a", "~/git/b"]

    def test_get_workspace_context(self):
        workspace.create_workspace(
            "dtp",
            ["mir"],
            memory_tags=["mir"],
            description="Work",
        )
        ctx = workspace.get_workspace_context("dtp")
        assert ctx is not None
        assert ctx["tags"] == ["mir"]
        assert ctx["memory_tags"] == ["mir"]
        assert ctx["description"] == "Work"

    def test_get_workspace_context_not_found(self):
        assert workspace.get_workspace_context("nope") is None


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


class TestGetWorkspaceContext:
    def _setup(self):
        workspace.create_workspace(
            "mir",
            ["mir", "roma"],
            memory_tags=["mir", "spring-boot"],
            description="MIR - Sistema gov.br",
        )
        engine.create_item(title="API endpoint", tags="mir", priority="high")
        engine.create_item(title="DB migration", tags="roma", priority="medium")
        engine.create_item(title="Unrelated", tags="other")

    def test_minimal_verbosity(self):
        self._setup()
        ctx = engine.get_workspace_context("mir", verbosity="minimal")
        assert ctx["workspace"] == "mir"
        assert ctx["brief"] == "MIR - Sistema gov.br"
        assert ctx["status_counts"]["queue"] == 2
        assert ctx["memory_tags"] == ["mir", "spring-boot"]
        assert ctx["next_item"] is not None
        assert "active_items" not in ctx
        assert "blocked_items" not in ctx
        assert "recent_decisions" not in ctx

    def test_standard_verbosity(self):
        self._setup()
        # Move one item to work
        items = engine.query_items(tags="mir")
        engine.advance_item(items[0]["id"], "start")
        ctx = engine.get_workspace_context("mir", verbosity="standard")
        assert "active_items" in ctx
        assert "blocked_items" in ctx
        assert "recent_decisions" not in ctx
        assert len(ctx["active_items"]) == 1
        assert ctx["active_items"][0]["status"] == "work"

    def test_full_verbosity_with_decisions(self):
        self._setup()
        items = engine.query_items(tags="mir")
        engine.advance_item(items[0]["id"], "start")
        engine.upsert_note(items[0]["id"], "decision-arch", "Use REST", role="review")
        ctx = engine.get_workspace_context("mir", verbosity="full")
        assert "recent_decisions" in ctx
        assert len(ctx["recent_decisions"]) == 1
        assert ctx["recent_decisions"][0]["key"] == "decision-arch"

    def test_workspace_not_found_raises(self):
        with pytest.raises(engine.ToolError, match="not found"):
            engine.get_workspace_context("nonexistent")

    def test_invalid_verbosity_raises(self):
        workspace.create_workspace("x", ["x"])
        with pytest.raises(engine.ToolError, match="Invalid verbosity"):
            engine.get_workspace_context("x", verbosity="invalid")

    def test_blocked_items_included_in_standard(self):
        workspace.create_workspace("mir", ["mir"], description="MIR")
        item1 = engine.create_item(title="Blocker", tags="mir")
        item2 = engine.create_item(title="Blocked", tags="mir")
        engine.add_dependency(item1["id"], item2["id"])
        ctx = engine.get_workspace_context("mir", verbosity="standard")
        blocked_ids = [b["id"] for b in ctx["blocked_items"]]
        assert item2["id"] in blocked_ids

    def test_output_is_json_serializable(self):
        import json

        self._setup()
        ctx = engine.get_workspace_context("mir", verbosity="full")
        # Should not raise
        serialized = json.dumps(ctx, default=str)
        assert len(serialized) > 0
