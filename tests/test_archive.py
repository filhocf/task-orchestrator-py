"""Tests for auto-archive feature (issue #31)."""

from datetime import datetime, timezone, timedelta

from task_orchestrator import db, engine


class TestArchiveTransition:
    """Test the archive trigger in the state machine."""

    def test_archive_from_done(self, tmp_db):
        item = engine.create_item(title="Test item")
        engine.advance_item(item["id"], "complete")
        result = engine.advance_item(item["id"], "archive")
        assert result["status"] == "archived"

    def test_archive_from_non_done_fails(self, tmp_db):
        item = engine.create_item(title="Test item")
        try:
            engine.advance_item(item["id"], "archive")
            assert False, "Should have raised"
        except engine.ToolError as e:
            assert e.code == "CONFLICT"

    def test_archived_is_terminal(self, tmp_db):
        item = engine.create_item(title="Test item")
        engine.advance_item(item["id"], "complete")
        engine.advance_item(item["id"], "archive")
        # Cannot start/complete/block from archived
        try:
            engine.advance_item(item["id"], "start")
            assert False, "Should have raised"
        except engine.ToolError as e:
            assert e.code == "CONFLICT"

    def test_reopen_from_archived_not_allowed(self, tmp_db):
        """Archived items cannot be reopened (not in reopen transitions)."""
        item = engine.create_item(title="Test item")
        engine.advance_item(item["id"], "complete")
        engine.advance_item(item["id"], "archive")
        try:
            engine.advance_item(item["id"], "reopen")
            assert False, "Should have raised"
        except engine.ToolError as e:
            assert e.code == "CONFLICT"


class TestArchiveItems:
    """Test the archive_items bulk operation."""

    def test_archive_old_done_items(self, tmp_db):
        conn = db.get_connection()
        # Create item and mark done with old updated_at
        item = engine.create_item(title="Old done item")
        engine.advance_item(item["id"], "complete")
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        conn.execute(
            "UPDATE work_items SET updated_at=? WHERE id=?", (old_date, item["id"])
        )
        conn.commit()
        conn.close()

        result = engine.archive_items(days=30)
        assert result["archived_count"] == 1
        assert item["id"] in result["archived_ids"]

        # Verify status changed
        updated = engine.get_item(item["id"])
        assert updated["status"] == "archived"

    def test_archive_skips_recent_done(self, tmp_db):
        item = engine.create_item(title="Recent done item")
        engine.advance_item(item["id"], "complete")

        result = engine.archive_items(days=30)
        assert result["archived_count"] == 0

    def test_archive_skips_non_done(self, tmp_db):
        conn = db.get_connection()
        item = engine.create_item(title="Work item")
        engine.advance_item(item["id"], "start")
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        conn.execute(
            "UPDATE work_items SET updated_at=? WHERE id=?", (old_date, item["id"])
        )
        conn.commit()
        conn.close()

        result = engine.archive_items(days=30)
        assert result["archived_count"] == 0


class TestArchiveStats:
    """Test archive_stats."""

    def test_stats_counts(self, tmp_db):
        conn = db.get_connection()
        # Create 1 old done item
        item1 = engine.create_item(title="Old")
        engine.advance_item(item1["id"], "complete")
        old_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        conn.execute(
            "UPDATE work_items SET updated_at=? WHERE id=?", (old_date, item1["id"])
        )
        conn.commit()
        conn.close()

        # Create recent done item
        item2 = engine.create_item(title="Recent")
        engine.advance_item(item2["id"], "complete")

        # Archive one manually
        item3 = engine.create_item(title="Already archived")
        engine.advance_item(item3["id"], "complete")
        engine.advance_item(item3["id"], "archive")

        stats = engine.archive_stats(days=30)
        assert stats["archived_count"] == 1
        assert stats["eligible_count"] == 1
        assert stats["archive_after_days"] == 30


class TestArchiveList:
    """Test archive_list."""

    def test_list_archived(self, tmp_db):
        item = engine.create_item(title="To archive")
        engine.advance_item(item["id"], "complete")
        engine.advance_item(item["id"], "archive")

        items = engine.archive_list()
        assert len(items) == 1
        assert items[0]["id"] == item["id"]


class TestGetContextExcludesArchived:
    """Test that get_context excludes archived items by default."""

    def test_context_excludes_archived_from_counts(self, tmp_db):
        item = engine.create_item(title="Archived item")
        engine.advance_item(item["id"], "complete")
        engine.advance_item(item["id"], "archive")

        ctx = engine.get_context()
        assert "archived" not in ctx["counts"]

    def test_context_includes_archived_when_requested(self, tmp_db):
        item = engine.create_item(title="Archived item")
        engine.advance_item(item["id"], "complete")
        engine.advance_item(item["id"], "archive")

        ctx = engine.get_context(include_archived=True)
        assert "archived" in ctx["counts"]
        assert ctx["counts"]["archived"] == 1


class TestGetNextItemExcludesArchived:
    """Archived items should never appear in get_next_item."""

    def test_next_item_skips_archived(self, tmp_db):
        item = engine.create_item(title="Archived")
        engine.advance_item(item["id"], "complete")
        engine.advance_item(item["id"], "archive")

        result = engine.get_next_item()
        assert result is None


class TestMetricsIncludesArchived:
    """Archived items should count in throughput metrics."""

    def test_metrics_counts_archived_in_throughput(self, tmp_db):
        item = engine.create_item(title="Archived item")
        engine.advance_item(item["id"], "complete")
        engine.advance_item(item["id"], "archive")

        metrics = engine.get_metrics(days=30)
        # archived item should be counted in throughput
        total_throughput = sum(w["count"] for w in metrics["throughput_per_week"])
        assert total_throughput >= 1
