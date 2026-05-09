"""MCP Server exposing task orchestrator tools."""

import json
from mcp.server.fastmcp import FastMCP
from . import db, engine
from .engine import ToolError
from .schemas import get_schemas, load_schemas, get_schema_for_item
from .prompts import register_prompts
from . import workspace

mcp = FastMCP(
    "task-orchestrator",
    instructions="""Task Orchestrator — persistent work item graph for AI agents.
WorkItems flow: queue → work → review → done. Use triggers: start, complete, block, resume, cancel, reopen.
Start sessions with get_context() to see current state. Use get_next_item() for priority-ranked next action.""",
)


def _json(obj) -> str:
    return json.dumps(obj, default=str)


def _err(e: Exception) -> str:
    if isinstance(e, ToolError):
        return _json(e.to_dict())
    return _json({"error": str(e)})


def _resolve(id_str: str) -> str:
    """Resolve a potentially short hex ID to full UUID."""
    if not id_str:
        return id_str
    if len(id_str) < 36:
        return engine.resolve_short_id(id_str)
    return id_str


@mcp.tool()
def manage_items(operation: str, title: str = "", item_id: str = "", description: str = "",
                 summary: str = "", parent_id: str = "", priority: str = "medium",
                 complexity: int | None = None, item_type: str = "", tags: str = "",
                 metadata: str = "", properties: str = "",
                 due_at: str = "",
                 items_json: str = "", ids_json: str = "", recursive: bool = False) -> str:
    """Create, update, or delete work items. Supports batch operations.

    Operations: create, update, delete.
    Priority: critical, high, medium, low. Complexity: 1-10.
    Items support hierarchy via parent_id (max 4 levels deep).
    Batch create: pass items_json as JSON array of item objects.
    Batch delete: pass ids_json as JSON array of item IDs. Use recursive=true to delete descendants.
    due_at: optional ISO 8601 datetime string for due date (e.g. '2025-12-31T23:59:59+00:00').
    """
    try:
        item_id = _resolve(item_id)
        parent_id = _resolve(parent_id)
        if operation == "create":
            if items_json:
                items = json.loads(items_json)
                return _json(engine.create_items_batch(items, parent_id=parent_id or None))
            return _json(engine.create_item(
                title=title, description=description, summary=summary,
                parent_id=parent_id or None, priority=priority,
                complexity=complexity, item_type=item_type, tags=tags,
                metadata=metadata or None, properties=properties or None,
                due_at=due_at or None))
        elif operation == "update":
            kwargs = {}
            if title:
                kwargs["title"] = title
            if description:
                kwargs["description"] = description
            if summary:
                kwargs["summary"] = summary
            if priority:
                kwargs["priority"] = priority
            if complexity is not None:
                kwargs["complexity"] = complexity
            if item_type:
                kwargs["item_type"] = item_type
            if tags:
                kwargs["tags"] = tags
            if metadata:
                kwargs["metadata"] = metadata
            if properties:
                kwargs["properties"] = properties
            if due_at:
                kwargs["due_at"] = due_at
            return _json(engine.update_item(item_id, **kwargs))
        elif operation == "delete":
            if ids_json:
                ids = json.loads(ids_json)
                return _json(engine.delete_items_batch(ids, recursive=recursive))
            return _json(engine.delete_item(item_id, recursive=recursive))
        return _json({"error": f"Invalid operation: {operation}. Use: create, update, delete"})
    except Exception as e:
        return _err(e)


@mcp.tool()
def query_items(operation: str = "list", item_id: str = "", status: str = "",
                parent_id: str = "", priority: str = "", search: str = "",
                tags: str = "",
                include_ancestors: bool = False, limit: int = 50, offset: int = 0) -> str:
    """Query work items. Operations: get (by id), list (with filters), children (of parent), overview (status counts).

    Filters: status (queue/work/review/done/blocked/cancelled), priority, parent_id, search text, tags (comma-separated).
    Use include_ancestors=true with get to see the full parent chain.
    """
    try:
        item_id = _resolve(item_id)
        parent_id = _resolve(parent_id)
        if operation == "get":
            result = engine.get_item(item_id)
            if not result:
                return _json({"error": f"Item {item_id} not found"})
            if include_ancestors:
                result["ancestors"] = engine.get_ancestors(item_id)
            return _json(result)
        elif operation == "children":
            return _json(engine.get_children(parent_id or item_id))
        elif operation == "overview":
            ctx = engine.get_context()
            return _json({"counts": ctx["counts"], "active_count": len(ctx["active"]),
                          "blocked_count": len(ctx["blocked"])})
        return _json(engine.query_items(status=status or None, parent_id=parent_id or None,
                                        priority=priority or None, search=search or None,
                                        tags=tags or None, limit=limit, offset=offset))
    except Exception as e:
        return _err(e)


@mcp.tool()
def advance_item(item_id: str = "", trigger: str = "", transitions_json: str = "") -> str:
    """Advance work items through workflow using triggers. Supports batch transitions.

    Triggers: start (next phase), complete (jump to done), block/hold (pause), resume (unblock),
    cancel (close), reopen (done/cancelled → queue).
    Flow: queue → work → review → done. Checks dependency satisfaction and note gates.
    Batch: pass transitions_json as JSON array of {item_id, trigger} objects.
    Reopen cascades parent from terminal to work.
    """
    try:
        if transitions_json:
            transitions = json.loads(transitions_json)
            for t in transitions:
                t["item_id"] = _resolve(t["item_id"])
            return _json(engine.advance_items_batch(transitions))
        item_id = _resolve(item_id)
        return _json(engine.advance_item(item_id, trigger))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_next_status(item_id: str, trigger: str) -> str:
    """Read-only preview of what would happen with a given trigger.

    Returns can_advance (bool), current status, next status, and any blockers.
    Use before advance_item to check feasibility without side effects.
    """
    return _json(engine.get_next_status(_resolve(item_id), trigger))


@mcp.tool()
def get_next_item(workspace: str = "") -> str:
    """Get the highest-priority actionable item with no unsatisfied dependencies.

    Returns the single best next item to work on, or null if nothing is actionable.
    Priority: items already in 'work' first, then by priority (critical > high > medium > low).
    Use workspace to filter by workspace tags (e.g. workspace="dtp").
    """
    result = engine.get_next_item(workspace=workspace or None)
    return _json(result) if result else _json({"message": "No actionable items"})


@mcp.tool()
def get_context(item_id: str = "", include_ancestors: bool = False, workspace: str = "") -> str:
    """Get context snapshot for session resume or item inspection.

    Without item_id: global dashboard — status counts, active items, blocked items, next action.
    With item_id: item detail — children, notes, blockers, can_advance flag.
    Use include_ancestors=true to get the full parent chain.
    Use workspace to filter by workspace tags (e.g. workspace="dtp").
    Call this at session start to understand current work state.
    """
    try:
        return _json(engine.get_context(_resolve(item_id) or None, include_ancestors=include_ancestors,
                                        workspace=workspace or None))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_blocked_items() -> str:
    """Get all blocked items — both explicitly blocked and those with unsatisfied dependencies.

    Use to identify what's stuck and what needs to be resolved to unblock progress.
    """
    return _json(engine.get_blocked_items())


@mcp.tool()
def manage_notes(operation: str, item_id: str, key: str = "", body: str = "", role: str = "queue") -> str:
    """Manage notes on work items. Notes are persistent documentation per phase.

    Operations: upsert (create/update by key), delete, list (all notes for item).
    Role: queue, work, review — indicates which phase the note belongs to.
    Use notes to capture requirements, decisions, done-criteria, and handoff context.
    """
    try:
        item_id = _resolve(item_id)
        if operation == "upsert":
            return _json(engine.upsert_note(item_id, key, body, role))
        elif operation == "delete":
            return _json({"deleted": engine.delete_note(item_id, key)})
        elif operation == "list":
            return _json(engine.get_notes(item_id))
        return _json({"error": f"Invalid operation: {operation}. Use: upsert, delete, list"})
    except Exception as e:
        return _err(e)


@mcp.tool()
def query_notes(item_id: str, key: str = "", include_body: bool = True) -> str:
    """Query notes for a work item. Use include_body=false for token-efficient metadata checks.

    With key: get a single note. Without key: list all notes for the item.
    """
    try:
        item_id = _resolve(item_id)
        if key:
            from .db import get_connection
            conn = get_connection()
            try:
                row = conn.execute("SELECT * FROM notes WHERE item_id=? AND key=?", (item_id, key)).fetchone()
                return _json(dict(row) if row else {"error": f"Note '{key}' not found on item {item_id}"})
            finally:
                conn.close()
        return _json(engine.get_notes(item_id, include_body=include_body))
    except Exception as e:
        return _err(e)


@mcp.tool()
def manage_dependencies(operation: str, from_id: str = "", to_id: str = "",
                        item_id: str = "", direction: str = "both",
                        item_ids: str = "", pattern: str = "linear",
                        unblock_at: str = "done") -> str:
    """Manage dependency edges between work items.

    Operations: add (from_id blocks to_id), remove, query (get deps for item_id), pattern.
    Direction for query: inbound, outbound, both.
    Pattern operation: create deps using shortcuts — linear, fan-out, fan-in.
      item_ids: comma-separated list of item IDs for pattern creation.
    unblock_at: status threshold at which blocker unblocks (done, review, work). Default: done.
    Dependencies enforce ordering — blocked items cannot advance until blockers reach unblock_at.
    """
    try:
        from_id = _resolve(from_id)
        to_id = _resolve(to_id)
        item_id = _resolve(item_id)
        if operation == "add":
            return _json(engine.add_dependency(from_id, to_id, unblock_at=unblock_at))
        elif operation == "remove":
            return _json({"removed": engine.remove_dependency(from_id, to_id)})
        elif operation == "query":
            return _json(engine.get_dependencies(item_id or from_id, direction))
        elif operation == "pattern":
            ids = [_resolve(i.strip()) for i in item_ids.split(",") if i.strip()]
            return _json(engine.add_dependency_pattern(ids, pattern))
        return _json({"error": f"Invalid operation: {operation}. Use: add, remove, query, pattern"})
    except Exception as e:
        return _err(e)


@mcp.tool()
def query_dependencies(item_id: str, direction: str = "outbound",
                       neighbors_only: bool = True, max_depth: int = 10) -> str:
    """Query dependencies with optional BFS traversal.

    neighbors_only=true: direct edges only (fast). false: full BFS graph traversal.
    Direction: outbound (what this blocks), inbound (what blocks this).
    """
    try:
        item_id = _resolve(item_id)
        if neighbors_only:
            return _json(engine.get_dependencies(item_id, direction))
        return _json(engine.query_dependencies_bfs(item_id, direction, max_depth))
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_work_tree(root_title: str, root_description: str = "", root_priority: str = "medium",
                     children_json: str = "[]", deps_json: str = "[]",
                     create_notes: bool = False) -> str:
    """Atomically create a root item + children + dependencies in one call.

    children_json: JSON array of {ref, title, description, priority} objects.
    deps_json: JSON array of {from, to, type?, unblock_at?} objects using ref names.
    create_notes: auto-create blank notes from matching schemas (default: false).
    Example: children=[{"ref":"a","title":"Schema"},{"ref":"b","title":"API"}], deps=[{"from":"a","to":"b"}]
    """
    try:
        children = json.loads(children_json) if isinstance(children_json, str) else children_json
        deps = json.loads(deps_json) if isinstance(deps_json, str) else deps_json
        return _json(engine.create_work_tree(
            root={"title": root_title, "description": root_description, "priority": root_priority},
            children=children, deps=deps, create_notes=create_notes,
        ))
    except Exception as e:
        return _err(e)


@mcp.tool()
def complete_tree(parent_id: str) -> str:
    """Batch-complete all descendants of a parent item in topological order.

    Skips items already in terminal status. Reports items that couldn't be completed (e.g., blocked by deps).
    """
    try:
        return _json(engine.complete_tree(_resolve(parent_id)))
    except Exception as e:
        return _err(e)


@mcp.tool()
def manage_schemas(operation: str = "list", schema_name: str = "", item_id: str = "") -> str:
    """View note schemas and check gate status for items.

    Operations:
    - list: show all loaded schemas
    - get: show a specific schema by name
    - check: check gate status for an item (requires item_id)
    - reload: reload schemas from config file
    """
    try:
        item_id = _resolve(item_id)
        if operation == "list":
            return _json(get_schemas())
        elif operation == "get":
            schemas = get_schemas()
            if schema_name not in schemas:
                return _json({"error": f"Schema '{schema_name}' not found", "available": list(schemas.keys())})
            return _json(schemas[schema_name])
        elif operation == "check":
            item = engine.get_item(item_id)
            if not item:
                return _json({"error": f"Item {item_id} not found"})
            schema = get_schema_for_item(item.get("item_type", ""), item.get("tags", ""))
            if not schema:
                return _json({"has_schema": False, "can_advance": True})
            from .db import get_connection
            conn = get_connection()
            try:
                notes = [dict(r) for r in conn.execute(
                    "SELECT * FROM notes WHERE item_id=?", (item_id,)).fetchall()]
            finally:
                conn.close()
            from .schemas import check_gate
            # Check gate for next natural transition
            next_status = engine.TRANSITIONS.get("start", {}).get(item["status"])
            if not next_status:
                return _json({"has_schema": True, "schema": schema["name"],
                              "status": item["status"], "can_advance": item["status"] in engine.TERMINAL})
            gate = check_gate(item, notes, next_status)
            return _json({"has_schema": True, "schema": schema["name"], "lifecycle": schema["lifecycle"],
                          **gate})
        elif operation == "reload":
            result = load_schemas()
            return _json({"reloaded": True, "schemas": list(result.keys())})
        return _json({"error": f"Invalid operation: {operation}. Use: list, get, check, reload"})
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_metrics(days: int = 30, workspace: str = "") -> str:
    """Work metrics — throughput per week, average lead time, WIP count, stale ratio, breakdowns by priority and tag.

    Optional days param controls the lookback period (default: 30).
    Use workspace to filter by workspace tags (e.g. workspace="dtp").
    """
    try:
        return _json(engine.get_metrics(days=days, workspace=workspace or None))
    except Exception as e:
        return _err(e)


@mcp.tool()
def export_graph() -> str:
    """Export the entire work graph (items, notes, dependencies) as JSON.

    Returns a JSON object with items, notes, dependencies, exported_at timestamp, and version.
    Use import_graph to restore from this export.
    """
    try:
        return _json(engine.export_graph())
    except Exception as e:
        return _err(e)


@mcp.tool()
def import_graph(data_json: str, mode: str = "merge") -> str:
    """Import a work graph from JSON. Supports merge and replace modes.

    data_json: JSON string from export_graph output.
    mode: 'merge' inserts items/notes/deps that don't exist (skip on conflict).
          'replace' deletes everything first then inserts all.
    """
    try:
        data = json.loads(data_json)
        return _json(engine.import_graph(data, mode=mode))
    except Exception as e:
        return _err(e)


@mcp.tool()
def manage_workspaces(operation: str, name: str = "", tags: str = "", memory_tags: str = "") -> str:
    """Manage workspace configurations. Workspaces map tag groups for scoped queries.

    Operations: create, update, delete, list.
    tags: comma-separated list of item tags that belong to this workspace.
    memory_tags: comma-separated list of memory service tags for this workspace.
    Use workspace param in get_context, get_next_item, get_metrics to filter by workspace.
    """
    try:
        if operation == "list":
            return _json(workspace.list_workspaces())
        elif operation == "create":
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            mem_list = [t.strip() for t in memory_tags.split(",") if t.strip()] if memory_tags else []
            return _json(workspace.create_workspace(name, tag_list, mem_list))
        elif operation == "update":
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
            mem_list = [t.strip() for t in memory_tags.split(",") if t.strip()] if memory_tags else None
            return _json(workspace.update_workspace(name, tag_list, mem_list))
        elif operation == "delete":
            return _json(workspace.delete_workspace(name))
        return _json({"error": f"Invalid operation: {operation}. Use: create, update, delete, list"})
    except Exception as e:
        return _err(e)


def main():
    db.init_db()
    register_prompts(mcp)
    mcp.run()


if __name__ == "__main__":
    main()
