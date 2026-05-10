"""Tests for get_workspace_context and extended workspace config."""

import pytest

from task_orchestrator import engine, workspace


@pytest.fixture(autouse=True)
def workspace_config(tmp_db, tmp_path, monkeypatch):
    ws_path = str(tmp_path / "workspaces.json")
    monkeypatch.setenv("TASK_ORCHESTRATOR_WORKSPACES", ws_path)
    return ws_path


class TestExtendedWorkspaceConfig:
    def test_create_with_all_fields(self):
        workspace.create_workspace(
            "proj",
            tags=["api", "web"],
            memory_tags=["proj-mem"],
            description="Main project",
            repos=["~/git/proj"],
            conventions=["PEP8", "type hints"],
        )
        result = workspace.list_workspaces()
        assert result["proj"]["description"] == "Main project"
        assert result["proj"]["repos"] == ["~/git/proj"]
        assert result["proj"]["conventions"] == ["PEP8", "type hints"]

    def test_create_defaults_empty(self):
        workspace.create_workspace("minimal", tags=["x"])
        ws = workspace.list_workspaces()["minimal"]
        assert ws["description"] == ""
        assert ws["repos"] == []
        assert ws["conventions"] == []

    def test_update_extended_fields(self):
        workspace.create_workspace("proj", tags=["api"])
        workspace.update_workspace(
            "proj", description="Updated desc", repos=["~/new-repo"]
        )
        ws = workspace.list_workspaces()["proj"]
        assert ws["description"] == "Updated desc"
        assert ws["repos"] == ["~/new-repo"]
        assert ws["tags"] == ["api"]  # unchanged

    def test_get_workspace_config(self):
        workspace.create_workspace(
            "proj", tags=["api"], description="Desc", memory_tags=["m1"]
        )
        config = workspace.get_workspace_config("proj")
        assert config["description"] == "Desc"
        assert config["memory_tags"] == ["m1"]

    def test_get_workspace_config_not_found(self):
        assert workspace.get_workspace_config("nope") is None


class TestGetWorkspaceContext:
    def _setup(self):
        workspace.create_workspace(
            "dtp",
            tags=["mir", "rer"],
            memory_tags=["dtp-mem"],
            description="Dataprev projects",
        )
        engine.create_item(title="Task A", tags="mir")
        engine.create_item(title="Task B", tags="rer")
        engine.create_item(title="Task C", tags="other")

    def test_minimal_verbosity(self):
        self._setup()
        ctx = engine.get_workspace_context("dtp", verbosity="minimal")
        assert ctx["workspace"] == "dtp"
        assert ctx["brief"] == "Dataprev projects"
        assert ctx["status_counts"]["queue"] == 2
        assert ctx["memory_tags"] == ["dtp-mem"]
        assert ctx["next_item"] is not None
        assert "active_items" not in ctx
        assert "blocked_items" not in ctx
        assert "recent_decisions" not in ctx

    def test_standard_verbosity(self):
        self._setup()
        # Move one item to work
        item_id = engine.get_next_item(workspace="dtp")["id"]
        engine.advance_item(item_id, "start")

        ctx = engine.get_workspace_context("dtp", verbosity="standard")
        assert "active_items" in ctx
        assert len(ctx["active_items"]) == 1
        assert "blocked_items" in ctx
        assert "recent_decisions" not in ctx

    def test_full_verbosity_with_decisions(self):
        self._setup()
        item_id = engine.get_next_item(workspace="dtp")["id"]
        engine.upsert_note(item_id, "decision-arch", "Use microservices", "work")

        ctx = engine.get_workspace_context("dtp", verbosity="full")
        assert "recent_decisions" in ctx
        assert len(ctx["recent_decisions"]) == 1
        assert ctx["recent_decisions"][0]["key"] == "decision-arch"

    def test_full_verbosity_no_decisions(self):
        self._setup()
        ctx = engine.get_workspace_context("dtp", verbosity="full")
        assert ctx["recent_decisions"] == []

    def test_workspace_not_found(self):
        with pytest.raises(engine.ToolError, match="not found"):
            engine.get_workspace_context("nonexistent")

    def test_invalid_verbosity(self):
        workspace.create_workspace("x", tags=["t"])
        with pytest.raises(engine.ToolError, match="Invalid verbosity"):
            engine.get_workspace_context("x", verbosity="invalid")
