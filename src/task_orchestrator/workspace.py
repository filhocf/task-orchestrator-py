"""Workspace management — tag-group config with JSON file storage."""

import json
import logging
import os
from pathlib import Path

from .db import DB_PATH

logger = logging.getLogger(__name__)


def _config_path() -> str:
    return os.environ.get(
        "TASK_ORCHESTRATOR_WORKSPACES",
        str(Path(DB_PATH).parent / "workspaces.json"),
    )


def _load() -> dict:
    path = _config_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load workspaces config from %s: %s", path, e)
        return {}


def _save(data: dict):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def list_workspaces() -> dict:
    return _load()


def create_workspace(
    name: str, tags: list[str], memory_tags: list[str] | None = None
) -> dict:
    data = _load()
    if name in data:
        raise ValueError(f"Workspace '{name}' already exists")
    data[name] = {"tags": tags, "memory_tags": memory_tags or []}
    _save(data)
    return {name: data[name]}


def update_workspace(
    name: str, tags: list[str] | None = None, memory_tags: list[str] | None = None
) -> dict:
    data = _load()
    if name not in data:
        raise ValueError(f"Workspace '{name}' not found")
    if tags is not None:
        data[name]["tags"] = tags
    if memory_tags is not None:
        data[name]["memory_tags"] = memory_tags
    _save(data)
    return {name: data[name]}


def delete_workspace(name: str) -> dict:
    data = _load()
    if name not in data:
        raise ValueError(f"Workspace '{name}' not found")
    del data[name]
    _save(data)
    return {"deleted": name}


def get_workspace_tags(name: str) -> list[str] | None:
    """Get tags for a workspace. Returns None if workspace not found."""
    data = _load()
    ws = data.get(name)
    return ws["tags"] if ws else None
