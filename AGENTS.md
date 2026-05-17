# AGENTS.md

## Project Overview

MCP server for work item management — tasks, dependencies, notes, workspaces, and workflow automation. Built with Python (FastMCP), SQLite storage, Streamable HTTP transport on port 3201. Entry point: `src/task_orchestrator/server.py`.

## Architecture

```
src/task_orchestrator/
├── server.py            ← FastMCP server, registers all tools
├── models.py            ← Pydantic models (WorkItem, Note, Dependency)
├── storage.py           ← SQLite operations (CRUD, queries, migrations)
├── workflow.py          ← State machine (queue→work→review→done), triggers
├── dependencies.py      ← Dependency graph, BFS traversal, unblock logic
├── workspaces.py        ← Workspace configs, scoped queries
├── metrics.py           ← Throughput, lead time, WIP calculations
└── schemas.py           ← Note gate schemas, validation
```

**Data flow:** Tool call → validate params → storage operation → state transition (if applicable) → return result.

## Key Conventions

- **Storage**: single SQLite file (`~/.task-orchestrator/tasks.db`). WAL mode enabled.
- **State machine**: queue → work → review → done. Triggers: start, complete, block, hold, resume, cancel, reopen.
- **Dependencies**: `from_id` blocks `to_id`. Configurable `unblock_at` (done, review, work).
- **Workspaces**: tag-based filtering. Config in `workspaces.json`.
- **Transport**: `MCP_TRANSPORT=streamable-http` (default) or `stdio`. Port via `MCP_PORT` (default 3201).

## Adding a New Tool

1. Define the tool function in `server.py` with `@mcp.tool(name=..., description=...)`.
2. Use `Annotated[type, Field(description=...)]` for all parameters.
3. Call storage/workflow functions for business logic.
4. Add tests in `tests/`.

## Tests

```bash
pytest                    # All tests
pytest tests/test_api.py  # Specific module
```

- Tests use temp SQLite databases (auto-cleanup).
- No external dependencies needed for testing.
