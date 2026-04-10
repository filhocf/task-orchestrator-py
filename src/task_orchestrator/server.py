"""MCP Server exposing task orchestrator tools."""

import json
from mcp.server.fastmcp import FastMCP
from . import db, engine

mcp = FastMCP(
    "task-orchestrator",
    instructions="""Task Orchestrator — persistent work item graph for AI agents.
WorkItems flow: queue → work → review → done. Use triggers: start, complete, block, resume, cancel, reopen.
Start sessions with get_context() to see current state. Use get_next_item() for priority-ranked next action.""",
)


@mcp.tool()
def manage_items(operation: str, title: str = "", item_id: str = "", description: str = "",
                 parent_id: str = "", priority: str = "medium", item_type: str = "", tags: str = "") -> str:
    """Create, update, or delete work items.

    Operations: create, update, delete.
    Priority: critical, high, medium, low.
    Items support hierarchy via parent_id (max 4 levels deep).
    """
    try:
        if operation == "create":
            result = engine.create_item(title=title, description=description,
                                        parent_id=parent_id or None, priority=priority,
                                        item_type=item_type, tags=tags)
        elif operation == "update":
            kwargs = {}
            if title: kwargs["title"] = title
            if description: kwargs["description"] = description
            if priority: kwargs["priority"] = priority
            if item_type: kwargs["item_type"] = item_type
            if tags: kwargs["tags"] = tags
            result = engine.update_item(item_id, **kwargs)
        elif operation == "delete":
            result = {"deleted": engine.delete_item(item_id)}
        else:
            return json.dumps({"error": f"Invalid operation: {operation}. Use: create, update, delete"})
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def query_items(operation: str = "list", item_id: str = "", status: str = "",
                parent_id: str = "", priority: str = "", search: str = "",
                limit: int = 50, offset: int = 0) -> str:
    """Query work items. Operations: get (by id), list (with filters), children (of parent), overview (status counts).

    Filters: status (queue/work/review/done/blocked/cancelled), priority, parent_id, search text.
    """
    try:
        if operation == "get":
            result = engine.get_item(item_id)
            if not result:
                return json.dumps({"error": f"Item {item_id} not found"})
        elif operation == "children":
            result = engine.get_children(parent_id or item_id)
        elif operation == "overview":
            ctx = engine.get_context()
            result = {"counts": ctx["counts"], "active_count": len(ctx["active"]),
                      "blocked_count": len(ctx["blocked"])}
        else:
            result = engine.query_items(status=status or None, parent_id=parent_id or None,
                                        priority=priority or None, search=search or None,
                                        limit=limit, offset=offset)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def advance_item(item_id: str, trigger: str) -> str:
    """Advance a work item through its workflow using a trigger.

    Triggers: start (next phase), complete (jump to done), block (pause), resume (unblock),
    cancel (close), reopen (done/cancelled → queue).
    Flow: queue → work → review → done. Checks dependency satisfaction before advancing.
    Returns the updated item plus any newly unblocked items.
    """
    try:
        return json.dumps(engine.advance_item(item_id, trigger), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_next_item() -> str:
    """Get the highest-priority actionable item with no unsatisfied dependencies.

    Returns the single best next item to work on, or null if nothing is actionable.
    Priority: items already in 'work' first, then by priority (critical > high > medium > low).
    """
    result = engine.get_next_item()
    return json.dumps(result, default=str) if result else json.dumps({"message": "No actionable items"})


@mcp.tool()
def get_context(item_id: str = "") -> str:
    """Get context snapshot for session resume or item inspection.

    Without item_id: global dashboard — status counts, active items, blocked items, next action.
    With item_id: item detail — children, notes, blockers, can_advance flag.
    Call this at session start to understand current work state.
    """
    try:
        return json.dumps(engine.get_context(item_id or None), default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_blocked_items() -> str:
    """Get all blocked items — both explicitly blocked and those with unsatisfied dependencies.

    Use to identify what's stuck and what needs to be resolved to unblock progress.
    """
    return json.dumps(engine.get_blocked_items(), default=str)


@mcp.tool()
def manage_notes(operation: str, item_id: str, key: str = "", body: str = "", role: str = "queue") -> str:
    """Manage notes on work items. Notes are persistent documentation per phase.

    Operations: upsert (create/update by key), delete, list (all notes for item).
    Role: queue, work, review — indicates which phase the note belongs to.
    Use notes to capture requirements, decisions, done-criteria, and handoff context.
    """
    try:
        if operation == "upsert":
            result = engine.upsert_note(item_id, key, body, role)
        elif operation == "delete":
            result = {"deleted": engine.delete_note(item_id, key)}
        elif operation == "list":
            result = engine.get_notes(item_id)
        else:
            return json.dumps({"error": f"Invalid operation: {operation}. Use: upsert, delete, list"})
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def manage_dependencies(operation: str, from_id: str = "", to_id: str = "",
                        item_id: str = "", direction: str = "both") -> str:
    """Manage dependency edges between work items.

    Operations: add (from_id blocks to_id), remove, query (get deps for item_id).
    Direction for query: inbound, outbound, both.
    Dependencies enforce ordering — blocked items cannot advance until blockers are done.
    """
    try:
        if operation == "add":
            result = engine.add_dependency(from_id, to_id)
        elif operation == "remove":
            result = {"removed": engine.remove_dependency(from_id, to_id)}
        elif operation == "query":
            result = engine.get_dependencies(item_id or from_id, direction)
        else:
            return json.dumps({"error": f"Invalid operation: {operation}. Use: add, remove, query"})
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def create_work_tree(root_title: str, root_description: str = "", root_priority: str = "medium",
                     children_json: str = "[]", deps_json: str = "[]") -> str:
    """Atomically create a root item + children + dependencies in one call.

    children_json: JSON array of {ref, title, description, priority} objects.
    deps_json: JSON array of {from, to} objects using ref names.
    Example: children=[{"ref":"a","title":"Schema"},{"ref":"b","title":"API"}], deps=[{"from":"a","to":"b"}]
    """
    try:
        children = json.loads(children_json) if isinstance(children_json, str) else children_json
        deps = json.loads(deps_json) if isinstance(deps_json, str) else deps_json
        result = engine.create_work_tree(
            root={"title": root_title, "description": root_description, "priority": root_priority},
            children=children, deps=deps,
        )
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def main():
    db.init_db()
    mcp.run()


if __name__ == "__main__":
    main()
