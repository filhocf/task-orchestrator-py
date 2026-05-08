# Architecture — task-orchestrator-py

## Overview

Python MCP server for AI agent work management. Provides a persistent, hierarchical task system with workflow state machine, dependency graph, and note-based gates.

## Stack

- **Runtime**: Python 3.11+
- **Protocol**: MCP (Model Context Protocol) via `mcp` SDK, stdio transport
- **Storage**: SQLite with WAL journal mode
- **Dependencies**: pyyaml, croniter

## Module Layout

```
src/task_orchestrator/
├── server.py      # MCP server — tool registration and dispatch
├── engine.py      # Core logic — state machine, dependency resolution, queries
├── db.py          # SQLite schema, migrations, connection management
├── schemas.py     # Note schema definitions and gate validation
└── prompts.py     # Prompt templates for AI agent context
```

## Data Model

### Work Items

Hierarchical (max 4 levels deep via `parent_id`). Fields: id, title, description, status, priority (critical/high/medium/low), complexity (1-10), tags, metadata, due_at.

### Dependencies

Directed edges (`from_id` blocks `to_id`). Configurable `unblock_at` threshold: an item unblocks when its blocker reaches `done`, `review`, or `work` status.

### Notes

Key-value documents attached to items. Scoped by `role` (queue/work/review) to indicate which workflow phase they belong to.

## Workflow State Machine

```
queue → work → review → done
```

Triggers drive transitions:
- `start`: advance to next phase (queue→work→review→done)
- `complete`: jump directly to done
- `block` / `hold`: pause item (any phase → blocked/hold)
- `resume`: return to previous phase
- `cancel`: close item
- `reopen`: terminal → queue (cascades parent from terminal to work)

## Dependency Graph

- Cycle detection via DFS before adding edges
- Pattern-based creation: `linear`, `fan-out`, `fan-in`
- BFS traversal for transitive dependency queries
- Items cannot advance if unsatisfied dependencies exist (blocker hasn't reached `unblock_at`)

## Note Schemas as Gates

YAML-defined schemas specify required notes per workflow phase. An item cannot advance past a gate unless the required notes exist. Schemas are loaded from config and validated at transition time.

## Key Features

- **Stale detection**: identifies items stuck in a phase beyond configurable thresholds
- **Batch operations**: create trees atomically (root + children + deps), batch transitions
- **FTS5 search**: full-text search on item titles/descriptions (graceful fallback to LIKE)
- **Metrics**: throughput, lead time, WIP count, stale ratio
- **Import/Export**: full graph serialization as JSON

## MCP Tools

| Tool | Purpose |
|------|---------|
| `manage_items` | CRUD for work items (create, update, delete, batch) |
| `advance_item` | Trigger state transitions |
| `manage_dependencies` | Add/remove/query dependency edges |
| `manage_notes` | Upsert/delete/list notes on items |
| `get_context` | Dashboard or item detail snapshot |
| `get_next_item` | Highest-priority actionable item |
| `get_blocked_items` | Items with unsatisfied dependencies |
| `get_metrics` | Work throughput and health stats |
| `create_work_tree` | Atomic tree creation (root + children + deps) |
| `complete_tree` | Batch-complete all descendants |
| `manage_schemas` | View/check note gate schemas |
| `export_graph` / `import_graph` | Serialization |

## Storage Details

- **Location**: `~/.task-orchestrator/tasks.db` (override via `TASK_ORCHESTRATOR_DB` env var)
- **WAL mode**: concurrent reads, single writer
- **Foreign keys**: enforced (CASCADE deletes)
- **Migrations**: additive ALTER TABLE, applied on startup
