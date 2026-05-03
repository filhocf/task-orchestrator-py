"""Shared fixtures for task-orchestrator tests."""

import pytest

from task_orchestrator import db


@pytest.fixture()
def tmp_db(tmp_path):
    """Create a fresh temp SQLite DB, initialize schema, yield path, clean up."""
    db_file = str(tmp_path / "test_tasks.db")
    original = db.DB_PATH
    db.DB_PATH = db_file
    db.init_db()
    yield db_file
    db.DB_PATH = original


@pytest.fixture(autouse=True)
def engine_db(tmp_db):
    """Ensure every test uses the temp DB (autouse)."""
    yield tmp_db
