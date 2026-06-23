"""FastAPI Kanban Web UI for task-orchestrator."""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..engine import advance_item, get_item, query_items, ToolError
from ..workspace import list_workspaces

app = FastAPI(title="Task Orchestrator Kanban")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

STATUSES = ["queue", "work", "review", "done"]
PRIORITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🔵",
    "low": "⚪",
}
STATUS_TRIGGERS = {
    "queue": None,
    "work": "start",
    "review": "start",
    "done": "start",
}


def _age_days(created_at: str) -> int:
    try:
        dt = datetime.fromisoformat(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return 0


def _trigger_for_move(from_status: str, to_status: str) -> str | None:
    """Determine the trigger needed to move from one status to another."""
    if to_status == "done" and from_status in ("queue", "work", "review"):
        return "complete"
    if to_status == "queue" and from_status in ("done", "cancelled"):
        return "reopen"
    order = {"queue": 0, "work": 1, "review": 2, "done": 3}
    if order.get(to_status, -1) > order.get(from_status, -1):
        return "start"
    return None


def _get_board_data(workspace: str | None) -> dict:
    """Get items grouped by status for a workspace."""
    columns = {}
    ws_config = list_workspaces().get(workspace) if workspace else None
    for status in STATUSES:
        if workspace and ws_config:
            tags = ",".join(ws_config["tags"])
            items = query_items(status=status, tags=tags, limit=200)
        else:
            items = query_items(status=status, limit=200)
        for item in items:
            item["age"] = _age_days(item.get("created_at", ""))
            item["priority_emoji"] = PRIORITY_EMOJI.get(item.get("priority", ""), "⚪")
        columns[status] = items
    return columns


@app.get("/", response_class=RedirectResponse)
def index():
    workspaces = list_workspaces()
    if workspaces:
        first = next(iter(workspaces))
        return RedirectResponse(url=f"/board/{first}", status_code=302)
    return RedirectResponse(url="/board/_all", status_code=302)


@app.get("/board/{workspace}", response_class=HTMLResponse)
def board(request: Request, workspace: str, sort: str = "asc", sort_by: str = "alpha"):
    ws = None if workspace == "_all" else workspace
    columns = _get_board_data(ws)
    workspaces = list_workspaces()
    # Build swimlanes: group items by arc ancestor
    lanes = _build_swimlanes(columns)
    # Sort lanes
    if sort_by == "open":
        lanes = sorted(lanes, key=lambda ln: ln["open_count"], reverse=(sort != "asc"))
    else:
        lanes = sorted(lanes, key=lambda ln: ln["title"].lower(), reverse=(sort == "desc"))
    return templates.TemplateResponse(
        request,
        "board.html",
        {
            "workspace": workspace,
            "workspaces": workspaces,
            "columns": columns,
            "lanes": lanes,
            "statuses": STATUSES,
            "priority_emoji": PRIORITY_EMOJI,
            "sort": sort,
            "sort_by": sort_by,
        },
    )


@app.get("/item/{item_id}", response_class=HTMLResponse)
def item_detail(request: Request, item_id: str):
    """Return item detail as HTML partial (for modal)."""
    item = get_item(item_id)
    if not item:
        return HTMLResponse("Not found", status_code=404)
    item["priority_emoji"] = PRIORITY_EMOJI.get(item.get("priority", ""), "⚪")
    children = query_items(parent_id=item_id, limit=50)
    return templates.TemplateResponse(
        request, "partials/item_detail.html",
        {"item": item, "children": children},
    )


def _find_arc_ancestor(item: dict) -> str | None:
    """Walk up parent chain to find arc-tagged ancestor. Max 4 levels."""
    pid = item.get("parent_id")
    for _ in range(4):
        if not pid:
            return None
        parent = get_item(pid)
        if not parent:
            return None
        if "arc" in (parent.get("tags") or ""):
            return parent["id"]
        pid = parent.get("parent_id")
    return None


def _classify_item(item: dict, arc_map: dict, top_arcs: dict, parent_cache: dict) -> tuple[str, str | None]:
    """Walk up parent chain to find (top_arc_id, sub_arc_id). Uses parent_cache to avoid N+1."""
    pid = item.get("parent_id")
    prev_arc = None
    for _ in range(5):
        if not pid:
            return "__other__", prev_arc
        if pid in top_arcs:
            return pid, prev_arc
        if pid in arc_map:
            prev_arc = pid
        parent = parent_cache.get(pid)
        if not parent:
            return "__other__", prev_arc
        pid = parent.get("parent_id")
    return "__other__", prev_arc


def _build_swimlanes(columns: dict) -> list[dict]:
    """Group all items by arc ancestor for swimlane display, with sublanes."""
    # Collect all arc items
    arc_items = query_items(tags="arc", limit=50)
    arc_map = {a["id"]: a["title"] for a in arc_items}

    # Only top-level arcs become swimlanes
    top_arcs = {}
    for a in arc_items:
        parent_id = a.get("parent_id")
        if parent_id and parent_id in arc_map:
            continue
        top_arcs[a["id"]] = a["title"]

    # Sub-arcs: direct children of top-arcs that are also arcs
    sub_arcs = {}  # sub_arc_id -> {title, parent_arc_id}
    for a in arc_items:
        pid = a.get("parent_id")
        if pid and pid in top_arcs:
            sub_arcs[a["id"]] = {"title": a["title"], "parent": pid}

    # Pre-load parent cache: all items that have a parent_id (avoids N+1 get_item calls)
    all_parent_ids = set()
    for items in columns.values():
        for item in items:
            pid = item.get("parent_id")
            while pid:
                if pid in all_parent_ids:
                    break
                all_parent_ids.add(pid)
                # We don't know the grandparent yet; will resolve after loading
                break
    # Load all potential ancestors in bulk
    parent_cache: dict[str, dict] = {}
    # Arc items themselves are likely parents
    for a in arc_items:
        parent_cache[a["id"]] = a
    # Load remaining parents via get_item (batch: only unique IDs not already cached)
    for pid in all_parent_ids:
        if pid not in parent_cache:
            p = get_item(pid)
            if p:
                parent_cache[p["id"]] = p
    # Expand cache up the chain (max 5 levels)
    for _ in range(4):
        new_ids = set()
        for p in list(parent_cache.values()):
            gpid = p.get("parent_id")
            if gpid and gpid not in parent_cache:
                new_ids.add(gpid)
        if not new_ids:
            break
        for pid in new_ids:
            p = get_item(pid)
            if p:
                parent_cache[p["id"]] = p

    # Assign each item to a lane + sublane
    # Structure: lane_items[top_arc_id][sub_arc_id|"__direct__"][status] = [items]
    lane_data: dict[str, dict[str, dict[str, list]]] = {}
    for status, items in columns.items():
        for item in items:
            top_id, sub_id_raw = _classify_item(item, arc_map, top_arcs, parent_cache)
            sub_id = sub_id_raw or "__direct__"
            lane_data.setdefault(top_id, {}).setdefault(sub_id, {s: [] for s in columns.keys()})
            lane_data[top_id][sub_id][status].append(item)

    # Build lanes with sublanes
    lanes = []
    for arc_id, title in top_arcs.items():
        if arc_id not in lane_data:
            continue
        subs = lane_data[arc_id]
        # Compute totals across all sublanes
        all_items_flat = {s: [] for s in columns.keys()}
        for sub_cols in subs.values():
            for st, items in sub_cols.items():
                all_items_flat[st].extend(items)
        total = sum(len(v) for v in all_items_flat.values())
        open_count = total - len(all_items_flat.get("done", []))

        # Build sublane list
        sublanes = []
        for sub_id, sub_cols in subs.items():
            sub_title = sub_arcs[sub_id]["title"] if sub_id in sub_arcs else None
            sub_total = sum(len(v) for v in sub_cols.values())
            sub_open = sub_total - len(sub_cols.get("done", []))
            sublanes.append({"id": sub_id, "title": sub_title, "columns": sub_cols, "open_count": sub_open, "total_count": sub_total})

        # Sort sublanes: direct first, then by title
        sublanes.sort(key=lambda s: (s["title"] or "", s["id"]))

        # If only one sublane (direct), flatten
        if len(sublanes) == 1 and sublanes[0]["id"] == "__direct__":
            lanes.append({"id": arc_id, "title": title, "columns": all_items_flat, "open_count": open_count, "total_count": total, "sublanes": []})
        else:
            lanes.append({"id": arc_id, "title": title, "columns": all_items_flat, "open_count": open_count, "total_count": total, "sublanes": sublanes})

    if "__other__" in lane_data:
        subs = lane_data["__other__"]
        all_items_flat = {s: [] for s in columns.keys()}
        for sub_cols in subs.values():
            for st, items in sub_cols.items():
                all_items_flat[st].extend(items)
        total = sum(len(v) for v in all_items_flat.values())
        open_count = total - len(all_items_flat.get("done", []))
        lanes.append({"id": "__other__", "title": "Outros", "columns": all_items_flat, "open_count": open_count, "total_count": total, "sublanes": []})
    return lanes


@app.get("/board/{workspace}/column/{status}", response_class=HTMLResponse)
def column_partial(request: Request, workspace: str, status: str):
    ws = None if workspace == "_all" else workspace
    columns = _get_board_data(ws)
    items = columns.get(status, [])
    return templates.TemplateResponse(
        request,
        "partials/column.html",
        {"status": status, "items": items, "workspace": workspace},
    )


@app.post("/board/move", response_class=HTMLResponse)
def move_item(
    request: Request,
    item_id: str = Form(...),
    new_status: str = Form(...),
    workspace: str = Form("_all"),
):
    # Determine current status
    item = get_item(item_id)
    current_status = item["status"] if item else None

    error = None
    if current_status and current_status != new_status:
        trigger = _trigger_for_move(current_status, new_status)
        if trigger:
            try:
                advance_item(item_id, trigger)
            except ToolError as e:
                error = e.message
            except Exception as e:
                error = str(e)

    # Return updated columns for both source and target
    ws = None if workspace == "_all" else workspace
    columns = _get_board_data(ws)

    parts = []
    for status in STATUSES:
        html = templates.TemplateResponse(
            request,
            "partials/column.html",
            {
                "status": status,
                "items": columns.get(status, []),
                "workspace": workspace,
                "error": error if status == new_status else None,
            },
        )
        parts.append(html.body.decode())
    return HTMLResponse("".join(parts))


@app.get("/timeline/{workspace}", response_class=HTMLResponse)
def timeline(request: Request, workspace: str):
    workspaces = list_workspaces()
    ws = None if workspace == "_all" else workspace
    ws_config = workspaces.get(ws) if ws else None

    # Get all non-done items for the workspace
    items = []
    for status in ("queue", "work", "review", "blocked"):
        if ws and ws_config:
            tags = ",".join(ws_config["tags"])
            items.extend(query_items(status=status, tags=tags, limit=500))
        else:
            items.extend(query_items(status=status, limit=500))

    # Batch query dependencies (avoid N+1)
    deps = []
    if items:
        item_ids = {i["id"] for i in items}
        from ..db import get_connection

        conn = get_connection()
        try:
            placeholders = ",".join("?" * len(item_ids))
            rows = conn.execute(
                f"SELECT from_id, to_id FROM dependencies WHERE from_id IN ({placeholders})",
                list(item_ids),
            ).fetchall()
            for r in rows:
                if r["to_id"] in item_ids:
                    deps.append({"from_id": r["from_id"], "to_id": r["to_id"]})
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "timeline.html",
        {
            "workspace": workspace,
            "workspaces": workspaces,
            "items": items,
            "deps": deps,
            "priority_emoji": PRIORITY_EMOJI,
        },
    )


def _count_children(item_id: str) -> tuple[int, int]:
    """Return (done_count, total_count) for direct children."""
    children = query_items(parent_id=item_id, limit=500)
    total = len(children)
    done = sum(1 for c in children if c.get("status") == "done")
    return done, total


def _build_tree(item_id: str) -> list[dict]:
    """Build tree nodes for children of an item."""
    children = query_items(parent_id=item_id, limit=500)
    nodes = []
    for child in children:
        grandchildren = query_items(parent_id=child["id"], limit=1)
        done_count, total_count = _count_children(child["id"])
        nodes.append({
            "id": child["id"],
            "title": child["title"],
            "status": child.get("status", "queue"),
            "priority_emoji": PRIORITY_EMOJI.get(child.get("priority", ""), "⚪"),
            "children": len(grandchildren) > 0,
            "done_count": done_count,
            "total_count": total_count,
        })
    return nodes


@app.get("/arcs", response_class=HTMLResponse)
def arcs(request: Request, sort: str = "asc"):
    """List all arc root items (tagged 'arc')."""
    arc_items = query_items(tags="arc", limit=50)
    for item in arc_items:
        done, total = _count_children(item["id"])
        item["done_count"] = done
        item["child_count"] = total
        item["priority_emoji"] = PRIORITY_EMOJI.get(item.get("priority", ""), "⚪")
    # Sort by title
    arc_items = sorted(arc_items, key=lambda i: i["title"].lower(), reverse=(sort == "desc"))
    return templates.TemplateResponse(request, "arcs.html", {"arcs": arc_items, "sort": sort})


@app.get("/arcs/{item_id}", response_class=HTMLResponse)
def arc_detail(request: Request, item_id: str, direction: str = "TB", edges: str = "bezier"):
    """Show hierarchical tree for an arc."""
    arc = get_item(item_id)
    if not arc:
        return HTMLResponse("Not found", status_code=404)
    arc["priority_emoji"] = PRIORITY_EMOJI.get(arc.get("priority", ""), "⚪")
    children = _build_tree(item_id)
    done_count = sum(1 for c in children if c["status"] == "done")
    total_count = len(children)
    graph_data = _build_cytoscape_data(item_id, children)
    return templates.TemplateResponse(
        request, "arc_detail.html",
        {"arc": arc, "children": children, "done_count": done_count,
         "total_count": total_count, "graph_data": graph_data, "direction": direction, "item_id": item_id, "edges": edges},
    )


@app.get("/arcs/{item_id}/children", response_class=HTMLResponse)
def arc_children(request: Request, item_id: str):
    """HTMX partial: load children of a node."""
    nodes = _build_tree(item_id)
    return templates.TemplateResponse(request, "partials/tree_node.html", {"nodes": nodes})


@app.get("/arcs/{item_id}/children-json")
def arc_children_json(item_id: str):
    """JSON: children as Cytoscape nodes/edges for graph expand."""
    import json as _json
    children = query_items(parent_id=item_id, limit=50)
    nodes = []
    edges = []
    for child in children:
        nodes.append({"data": {"id": child["id"], "label": child.get("title", "")[:25], "status": child.get("status", "queue")}})
        edges.append({"data": {"source": item_id, "target": child["id"]}})
    return _json.loads(_json.dumps({"nodes": nodes, "edges": edges}))


def _build_cytoscape_data(arc_id: str, children: list[dict]) -> str:
    """Generate Cytoscape.js JSON data showing evolution tree (waves + deps only)."""
    import json

    from ..db import get_connection

    conn = get_connection()
    try:
        root = conn.execute("SELECT id, title, status FROM work_items WHERE id = ?", (arc_id,)).fetchone()
        if not root:
            return json.dumps({"nodes": [], "edges": []})

        direct_children = conn.execute(
            "SELECT id, title, status, priority, tags FROM work_items WHERE parent_id = ?", (arc_id,)
        ).fetchall()

        all_child_ids = [r["id"] for r in direct_children]
        placeholders = ",".join("?" * len(all_child_ids)) if all_child_ids else "''"

        # Items involved in dependencies
        dep_items = set()
        dep_rows = []
        if all_child_ids:
            dep_rows = conn.execute(
                f"SELECT from_id, to_id FROM dependencies WHERE from_id IN ({placeholders}) OR to_id IN ({placeholders})",
                all_child_ids + all_child_ids,
            ).fetchall()
            for r in dep_rows:
                dep_items.add(r["from_id"])
                dep_items.add(r["to_id"])

        # Filter: show waves + items with deps + items with children
        show_items = []
        for item in direct_children:
            tags = item["tags"] or ""
            has_deps = item["id"] in dep_items
            has_children = conn.execute("SELECT COUNT(*) FROM work_items WHERE parent_id=?", (item["id"],)).fetchone()[0] > 0
            is_wave = "wave" in tags
            if is_wave or has_deps or has_children:
                show_items.append(dict(item))

        if not show_items:
            show_items = [dict(r) for r in direct_children]

        if not show_items:
            return json.dumps({"nodes": [], "edges": []})

        nodes = [{"data": {"id": root["id"], "label": root["title"][:40], "status": root["status"] or "queue", "is_root": True}}]
        show_ids = set()
        for item in show_items:
            show_ids.add(item["id"])
            nodes.append({"data": {"id": item["id"], "label": item["title"][:35], "status": item.get("status", "queue"), "is_root": False}})

        edges = []
        dep_edges = set()
        if all_child_ids:
            for r in dep_rows:
                if r["from_id"] in show_ids and r["to_id"] in show_ids:
                    edges.append({"data": {"source": r["from_id"], "target": r["to_id"]}})
                    dep_edges.add((r["from_id"], r["to_id"]))

        # Root→child edges for items without incoming deps
        items_with_incoming = {to for _, to in dep_edges}
        for item in show_items:
            if item["id"] not in items_with_incoming:
                edges.append({"data": {"source": root["id"], "target": item["id"]}})

    finally:
        conn.close()

    return json.dumps({"nodes": nodes, "edges": edges})


@app.get("/workspaces")
def get_workspaces():
    return list_workspaces()


def main():
    parser = argparse.ArgumentParser(description="Task Orchestrator Kanban UI")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--db", help="Database path (overrides TASK_ORCHESTRATOR_DB)")
    args = parser.parse_args()

    if args.db:
        os.environ["TASK_ORCHESTRATOR_DB"] = args.db

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
