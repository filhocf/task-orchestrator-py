"""Tests for kanban board swimlane logic."""
from unittest.mock import patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from task_orchestrator.ui.app import _classify_item, _build_swimlanes


# Test data
TOP_ARC = {"id": "arc-top", "title": "Top Arc", "tags": "arc", "parent_id": None}
SUB_ARC = {"id": "arc-sub", "title": "Sub Arc", "tags": "arc", "parent_id": "arc-top"}
WAVE = {"id": "wave-1", "title": "Wave 1", "tags": "arc,wave", "parent_id": "arc-sub"}


class TestClassifyItem:
    """Tests for _classify_item."""

    def test_direct_under_top_arc(self):
        arc_map = {"arc-top": "Top Arc"}
        top_arcs = {"arc-top": "Top Arc"}
        parent_cache = {"arc-top": TOP_ARC}
        item = {"id": "item-1", "parent_id": "arc-top"}

        top_id, sub_id = _classify_item(item, arc_map, top_arcs, parent_cache)
        assert top_id == "arc-top"
        assert sub_id is None

    def test_under_sub_arc(self):
        arc_map = {"arc-top": "Top Arc", "arc-sub": "Sub Arc"}
        top_arcs = {"arc-top": "Top Arc"}
        parent_cache = {"arc-top": TOP_ARC, "arc-sub": SUB_ARC}
        item = {"id": "item-1", "parent_id": "arc-sub"}

        top_id, sub_id = _classify_item(item, arc_map, top_arcs, parent_cache)
        assert top_id == "arc-top"
        assert sub_id == "arc-sub"

    def test_orphan_no_parent(self):
        arc_map = {"arc-top": "Top Arc"}
        top_arcs = {"arc-top": "Top Arc"}
        parent_cache = {}
        item = {"id": "item-1", "parent_id": None}

        top_id, sub_id = _classify_item(item, arc_map, top_arcs, parent_cache)
        assert top_id == "__other__"
        assert sub_id is None

    def test_parent_not_in_cache(self):
        arc_map = {"arc-top": "Top Arc"}
        top_arcs = {"arc-top": "Top Arc"}
        parent_cache = {}  # parent not cached
        item = {"id": "item-1", "parent_id": "unknown-parent"}

        top_id, sub_id = _classify_item(item, arc_map, top_arcs, parent_cache)
        assert top_id == "__other__"

    def test_deep_nesting_under_wave(self):
        arc_map = {"arc-top": "Top", "arc-sub": "Sub", "wave-1": "Wave"}
        top_arcs = {"arc-top": "Top"}
        parent_cache = {
            "arc-top": TOP_ARC,
            "arc-sub": SUB_ARC,
            "wave-1": WAVE,
        }
        item = {"id": "item-1", "parent_id": "wave-1"}

        top_id, sub_id = _classify_item(item, arc_map, top_arcs, parent_cache)
        assert top_id == "arc-top"
        # sub_id should be arc-sub (the sub-arc between top and wave)
        assert sub_id in ("arc-sub", "wave-1")


class TestBuildSwimlanes:
    """Tests for _build_swimlanes (mocked queries)."""

    @patch("task_orchestrator.ui.app.get_item")
    @patch("task_orchestrator.ui.app.query_items")
    def test_flat_no_subarcs(self, mock_query, mock_get):
        mock_query.return_value = [TOP_ARC]
        mock_get.return_value = None

        columns = {
            "queue": [{"id": "i1", "parent_id": "arc-top", "priority": "medium", "title": "T1", "priority_emoji": "🔵"}],
            "work": [],
            "review": [],
            "done": [],
        }
        lanes = _build_swimlanes(columns)
        assert len(lanes) == 1
        assert lanes[0]["title"] == "Top Arc"
        assert lanes[0]["sublanes"] == []
        assert lanes[0]["open_count"] == 1
        assert lanes[0]["total_count"] == 1

    @patch("task_orchestrator.ui.app.get_item")
    @patch("task_orchestrator.ui.app.query_items")
    def test_with_sublanes(self, mock_query, mock_get):
        mock_query.return_value = [TOP_ARC, SUB_ARC]
        mock_get.side_effect = lambda pid: {"arc-top": TOP_ARC, "arc-sub": SUB_ARC}.get(pid)

        columns = {
            "queue": [{"id": "i1", "parent_id": "arc-sub", "priority": "medium", "title": "T1", "priority_emoji": "🔵"}],
            "work": [],
            "review": [],
            "done": [],
        }
        lanes = _build_swimlanes(columns)
        assert len(lanes) == 1
        assert lanes[0]["title"] == "Top Arc"
        assert len(lanes[0]["sublanes"]) >= 1
        sub = next(s for s in lanes[0]["sublanes"] if s["title"] == "Sub Arc")
        assert sub["open_count"] == 1

    @patch("task_orchestrator.ui.app.get_item")
    @patch("task_orchestrator.ui.app.query_items")
    def test_other_lane(self, mock_query, mock_get):
        mock_query.return_value = [TOP_ARC]
        mock_get.return_value = None

        columns = {
            "queue": [{"id": "i1", "parent_id": None, "priority": "low", "title": "Orphan", "priority_emoji": "⚪"}],
            "work": [],
            "review": [],
            "done": [],
        }
        lanes = _build_swimlanes(columns)
        other = next((ln for ln in lanes if ln["id"] == "__other__"), None)
        assert other is not None
        assert other["open_count"] == 1
