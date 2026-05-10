"""FastAPI Kanban Web UI for task-orchestrator."""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..engine import advance_item, query_items, ToolError
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
    for status in STATUSES:
        if workspace:
            ws_config = list_workspaces().get(workspace)
            if ws_config:
                tags = ",".join(ws_config["tags"])
                items = query_items(status=status, tags=tags, limit=200)
            else:
                items = query_items(status=status, limit=200)
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
def board(request: Request, workspace: str):
    ws = None if workspace == "_all" else workspace
    columns = _get_board_data(ws)
    workspaces = list_workspaces()
    return templates.TemplateResponse(
        request,
        "board.html",
        {
            "workspace": workspace,
            "workspaces": workspaces,
            "columns": columns,
            "statuses": STATUSES,
            "priority_emoji": PRIORITY_EMOJI,
        },
    )


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
    items = query_items(limit=500)
    current_status = None
    for item in items:
        if item["id"] == item_id:
            current_status = item["status"]
            break

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
