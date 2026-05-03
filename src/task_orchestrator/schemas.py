"""Note schema definitions and gate enforcement.

Schemas define required notes per workflow phase. When an item's type or tags
match a schema, advance_item checks that required notes are filled before
allowing phase transitions.

Lifecycle modes:
- auto: skip review phase if no review-phase notes defined in schema
- manual: all phases required (default)
- auto-reopen: terminal items auto-reopen on note update
- permanent: cannot be cancelled

Config loaded from YAML file (TASK_ORCHESTRATOR_CONFIG env var or
.taskorchestrator/config.yaml in working directory).
"""

import os
import yaml
from pathlib import Path

_schemas: dict[str, dict] = {}
_config_loaded = False


def _find_config() -> Path | None:
    explicit = os.environ.get("TASK_ORCHESTRATOR_CONFIG")
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    for candidate in [
        Path(".taskorchestrator/config.yaml"),
        Path(".taskorchestrator/config.yml"),
    ]:
        if candidate.exists():
            return candidate
    return None


def load_schemas(config_path: Path | None = None) -> dict[str, dict]:
    """Load and validate schemas from config file."""
    global _schemas, _config_loaded
    path = config_path or _find_config()
    if not path:
        _schemas = {}
        _config_loaded = True
        return _schemas
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    raw_schemas = raw.get("work_item_schemas", raw.get("note_schemas", {}))
    _schemas = {}
    for name, schema in raw_schemas.items():
        notes = schema.get("notes", [])
        # Legacy format: notes directly as list of dicts without nested "notes" key
        if not notes and isinstance(schema, dict):
            notes = [v for v in schema.values() if isinstance(v, dict) and "key" in v]
        _schemas[name] = {
            "name": name,
            "lifecycle": schema.get("lifecycle", "manual"),
            "notes": notes,
        }
    _config_loaded = True
    return _schemas


def get_schemas() -> dict[str, dict]:
    if not _config_loaded:
        load_schemas()
    return _schemas


def get_schema_for_item(item_type: str, tags: str = "") -> dict | None:
    """Find matching schema by item_type first, then by tags as fallback."""
    schemas = get_schemas()
    if item_type and item_type in schemas:
        return schemas[item_type]
    # Tag fallback
    if tags:
        tag_set = {t.strip() for t in tags.split(",")}
        for name, schema in schemas.items():
            if name in tag_set:
                return schema
    return None


def check_gate(item: dict, notes: list[dict], target_role: str) -> dict:
    """Check if an item can transition to target_role based on schema gates.

    Returns: {
        "can_advance": bool,
        "missing": [{"key": str, "role": str, "description": str}],
        "guidance": str | None  # description of first missing note
    }
    """
    schema = get_schema_for_item(item.get("item_type", ""), item.get("tags", ""))
    if not schema:
        return {"can_advance": True, "missing": [], "guidance": None}

    # Determine which roles need to be checked based on transition
    current = item["status"]
    roles_to_check = _roles_before(current, target_role)

    filled_keys = {n["key"] for n in notes if n.get("body", "").strip()}
    missing = []
    for note_def in schema["notes"]:
        if not note_def.get("required", False):
            continue
        if note_def["role"] not in roles_to_check:
            continue
        if note_def["key"] not in filled_keys:
            missing.append({
                "key": note_def["key"],
                "role": note_def["role"],
                "description": note_def.get("description", ""),
            })

    guidance = missing[0]["description"] if missing else None
    return {"can_advance": len(missing) == 0, "missing": missing, "guidance": guidance}


def should_skip_review(item: dict) -> bool:
    """Check if review phase should be skipped (auto lifecycle with no review notes)."""
    schema = get_schema_for_item(item.get("item_type", ""), item.get("tags", ""))
    if not schema or schema["lifecycle"] != "auto":
        return False
    review_notes = [n for n in schema["notes"] if n["role"] == "review"]
    return len(review_notes) == 0


def can_cancel(item: dict) -> bool:
    """Check if item can be cancelled (permanent lifecycle prevents it)."""
    schema = get_schema_for_item(item.get("item_type", ""), item.get("tags", ""))
    if not schema:
        return True
    return schema["lifecycle"] != "permanent"


def should_auto_reopen(item: dict) -> bool:
    """Check if a terminal item should auto-reopen when a note is updated."""
    schema = get_schema_for_item(item.get("item_type", ""), item.get("tags", ""))
    if not schema:
        return False
    return schema["lifecycle"] == "auto-reopen"


def _roles_before(current: str, target: str) -> set[str]:
    """Return the set of roles whose notes must be filled to reach target."""
    role_order = ["queue", "work", "review", "done"]
    try:
        target_idx = role_order.index(target)
    except ValueError:
        return set()
    # All roles up to (but not including) target need their notes filled
    return set(role_order[:target_idx])
