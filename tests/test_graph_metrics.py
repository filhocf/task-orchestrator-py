"""RED tests for get_project_graph_metrics — function does NOT exist yet."""

import pytest

from task_orchestrator import engine, workspace
from task_orchestrator.engine import get_project_graph_metrics


@pytest.fixture(autouse=True)
def workspace_config(tmp_db, tmp_path, monkeypatch):
    ws_path = str(tmp_path / "workspaces.json")
    monkeypatch.setenv("TASK_ORCHESTRATOR_WORKSPACES", ws_path)
    return ws_path


def _create(title="Task", **kw):
    return engine.create_item(title=title, **kw)


def _dep(from_id, to_id):
    """A blocks B (A must finish before B can start)."""
    return engine.add_dependency(from_id, to_id, dep_type="blocks")


class TestGetProjectGraphMetrics:

    def test_empty_graph_returns_defaults(self):
        """No items → zeros and empty lists."""
        result = get_project_graph_metrics()
        assert result["critical_path"] == []
        assert result["critical_path_length"] == 0
        assert result["next_on_critical_path"] is None
        assert result["impact_scores"] == []
        assert result["current_position"]["active_item"] is None
        assert result["current_position"]["on_critical_path"] is False
        assert result["current_position"]["distance_to_end"] == 0
        assert result["project_health"]["total"] == 0
        assert result["project_health"]["done"] == 0
        assert result["project_health"]["remaining"] == 0
        assert result["project_health"]["parallelizable_now"] == 0
        assert result["project_health"]["bottlenecks"] == []

    def test_linear_chain_critical_path(self):
        """A→B→C linear chain: critical_path=[A,B,C], length=3."""
        a = _create("A")
        b = _create("B")
        c = _create("C")
        _dep(a["id"], b["id"])
        _dep(b["id"], c["id"])

        result = get_project_graph_metrics()
        assert result["critical_path"] == [a["id"], b["id"], c["id"]]
        assert result["critical_path_length"] == 3

    def test_parallel_paths_picks_longest(self):
        """A→B→C and A→D: critical path is [A,B,C] (length 3 > 2)."""
        a = _create("A")
        b = _create("B")
        c = _create("C")
        d = _create("D")
        _dep(a["id"], b["id"])
        _dep(b["id"], c["id"])
        _dep(a["id"], d["id"])

        result = get_project_graph_metrics()
        assert result["critical_path"] == [a["id"], b["id"], c["id"]]
        assert result["critical_path_length"] == 3

    def test_done_items_excluded_from_path(self):
        """A(done)→B→C: critical_path=[B,C], length=2."""
        a = _create("A")
        b = _create("B")
        c = _create("C")
        _dep(a["id"], b["id"])
        _dep(b["id"], c["id"])
        # Mark A as done
        engine.advance_item(a["id"], "start")
        engine.advance_item(a["id"], "complete")

        result = get_project_graph_metrics()
        assert result["critical_path"] == [b["id"], c["id"]]
        assert result["critical_path_length"] == 2

    def test_impact_scores_count_downstream(self):
        """A blocks B and C, B blocks D: A.unblocks_count=3 (B, C, D)."""
        a = _create("A")
        b = _create("B")
        c = _create("C")
        d = _create("D")
        _dep(a["id"], b["id"])
        _dep(a["id"], c["id"])
        _dep(b["id"], d["id"])

        result = get_project_graph_metrics()
        scores = {s["item_id"]: s for s in result["impact_scores"]}
        assert scores[a["id"]]["unblocks_count"] == 3

    def test_next_on_critical_path_is_actionable(self):
        """A→B→C, A in work: next_on_critical_path=A (already active)."""
        a = _create("A")
        b = _create("B")
        c = _create("C")
        _dep(a["id"], b["id"])
        _dep(b["id"], c["id"])
        engine.advance_item(a["id"], "start")  # queue → work

        result = get_project_graph_metrics()
        assert result["next_on_critical_path"] == a["id"]

    def test_bottlenecks_are_highest_fanout(self):
        """Item blocking the most downstream items = bottleneck."""
        hub = _create("Hub")
        children = [_create(f"Child{i}") for i in range(4)]
        other = _create("Other")
        leaf = _create("Leaf")
        for child in children:
            _dep(hub["id"], child["id"])
        _dep(other["id"], leaf["id"])

        result = get_project_graph_metrics()
        assert hub["id"] in result["project_health"]["bottlenecks"]

    def test_workspace_filter(self):
        """Only items matching workspace tags appear in metrics."""
        workspace.create_workspace("frontend", ["fe"])
        fe_item = _create("FE task", tags="fe")
        be_item = _create("BE task", tags="be")
        _dep(fe_item["id"], be_item["id"])  # cross-workspace dep

        result = get_project_graph_metrics(workspace="frontend")
        all_ids = [s["item_id"] for s in result["impact_scores"]]
        assert fe_item["id"] in all_ids or result["project_health"]["total"] == 1
        assert result["project_health"]["total"] == 1

    def test_current_position_detects_off_path(self):
        """Active item NOT on critical path → on_critical_path=False."""
        a = _create("A")
        b = _create("B")
        c = _create("C")
        off = _create("OffPath")
        _dep(a["id"], b["id"])
        _dep(b["id"], c["id"])
        # off-path item is active
        engine.advance_item(off["id"], "start")

        result = get_project_graph_metrics()
        assert result["current_position"]["active_item"] == off["id"]
        assert result["current_position"]["on_critical_path"] is False

    def test_parallelizable_counts_unblocked_queue(self):
        """Items in queue with no pending deps are parallelizable."""
        a = _create("A")
        b = _create("B")
        _create("C")  # independent, queue
        _create("D")  # independent, queue
        _dep(a["id"], b["id"])  # B blocked by A

        result = get_project_graph_metrics()
        # A, C, D are in queue with no pending deps → parallelizable=3
        # B is in queue but blocked by A → not parallelizable
        assert result["project_health"]["parallelizable_now"] == 3
