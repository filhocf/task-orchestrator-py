# task-orchestrator-py

[![PyPI](https://img.shields.io/pypi/v/task-orchestrator-py)](https://pypi.org/project/task-orchestrator-py/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/filhocf/task-orchestrator-py/actions/workflows/ci.yml/badge.svg)](https://github.com/filhocf/task-orchestrator-py/actions/workflows/ci.yml)

Persistent work item graph with workflow enforcement for AI agents — a Python MCP server.

## Why

AI agents lose track of complex, multi-step work across sessions. They forget what was done, what's blocked, and what comes next. Prompt-based reminders don't survive context resets. File-based state has no enforcement.

**task-orchestrator-py** solves this with a server-enforced workflow engine:

- Items flow through `queue → work → review → done` — the server rejects invalid transitions
- Dependencies block advancement until prerequisites are satisfied
- Note schemas act as gates — required documentation must exist before phase changes
- Stale detection surfaces forgotten work automatically
- Everything persists in SQLite — survives crashes, restarts, and context window resets

This started as a Python port of [jpicklyk/task-orchestrator](https://github.com/jpicklyk/task-orchestrator) (Kotlin) but has diverged into a standalone project with its own feature set.

## How It's Different

| Approach | Limitation | task-orchestrator-py |
|----------|-----------|---------------------|
| Prompt-based tracking | Lost on context reset, no enforcement | Server-enforced state machine, persists across sessions |
| File-based state (JSON/YAML) | No workflow rules, easy to corrupt | SQLite with WAL, dependency cycle detection, gate checks |
| Original Kotlin version | JVM dependency, different feature set | Pure Python, pip-installable, plus features below |

**Python-exclusive features** not in the Kotlin original:

- **Tags** — comma-separated tags on items, filterable in queries
- **Batch transitions** — advance multiple items in one call
- **`create_work_tree`** — atomically create parent + children + dependencies
- **`complete_tree`** — batch-complete all descendants in topological order
- **Short hex IDs** — use `a1b2` instead of full UUIDs (4+ char prefix match)
- **Stale detection** — `get_context()` flags items stuck in queue (>7d) or work (>3d)
- **Structured errors** — typed error codes (`NOT_FOUND`, `VALIDATION`, `CONFLICT`, `DEPENDENCY_UNSATISFIED`, `GATE_BLOCKED`) with field-level detail

## Quick Start

```bash
# Run directly (no install needed)
uvx task-orchestrator-py

# Or install globally
pip install task-orchestrator-py
```

### MCP Client Configuration

Add to your MCP client config (Claude Desktop, Kiro, etc.):

```json
{
  "mcpServers": {
    "task-orchestrator": {
      "command": "uvx",
      "args": ["task-orchestrator-py"],
      "env": {
        "TASK_ORCHESTRATOR_DB": "/path/to/tasks.db"
      }
    }
  }
}
```

If `TASK_ORCHESTRATOR_DB` is not set, defaults to `~/.task-orchestrator/tasks.db`.

## Tools

### Hierarchy & CRUD

| Tool | Description |
|------|-------------|
| `manage_items` | Create, update, or delete work items. Batch create via `items_json`, batch delete via `ids_json`. |
| `query_items` | List with filters (status, priority, tags, search text), get by ID, get children, overview counts. |
| `create_work_tree` | Atomically create root + children + dependencies in one call using ref-based wiring. |
| `complete_tree` | Batch-complete all descendants of a parent in topological order. |

### Workflow

| Tool | Description |
|------|-------------|
| `advance_item` | Trigger-based transitions with dependency and gate enforcement. Supports batch via `transitions_json`. |
| `get_next_status` | Read-only preview — check if a transition is possible before committing. |
| `get_context` | Global dashboard (counts, active, blocked, stale, next action) or item detail (children, notes, gates). |
| `get_next_item` | Highest-priority actionable item with no unsatisfied dependencies. |
| `get_blocked_items` | All blocked items — explicit blocks and unsatisfied dependency chains. |

### Notes

| Tool | Description |
|------|-------------|
| `manage_notes` | Upsert or delete notes on items. Notes are keyed, phased (queue/work/review), and gate-checked. |
| `query_notes` | Get notes with optional `include_body=false` for token-efficient metadata checks. |

### Dependencies

| Tool | Description |
|------|-------------|
| `manage_dependencies` | Add/remove edges, pattern shortcuts (linear, fan-out, fan-in), configurable `unblock_at` threshold. |
| `query_dependencies` | Direct neighbors or full BFS graph traversal with depth control. |

### Schemas

| Tool | Description |
|------|-------------|
| `manage_schemas` | List, inspect, check gate status for items, reload config. |

## Workflow

```
          start         start         start
  queue ────────→ work ────────→ review ────────→ done
    │               │               │
    │  complete      │  complete     │  complete
    └───────────────────────────────────────────→ done
    │               │               │
    │    block       │    block      │    block
    └──────→ blocked ←──────────────┘
                │
                │  resume
                └──────→ (previous status)

  done/cancelled ──reopen──→ queue
```

**Triggers:** `start` (next phase), `complete` (jump to done), `block`/`hold` (pause), `resume` (unblock), `cancel` (close), `reopen` (reactivate)

**Enforcement:** Dependencies must be satisfied before leaving `queue`. Note schema gates are checked on every `start`/`complete`. Reopen cascades to parent if parent is terminal.

## Real Usage Example

A realistic multi-step workflow — building a feature with tracked subtasks:

```
# 1. Create a work tree with children and dependencies
create_work_tree(
  root_title="User authentication",
  root_description="Add JWT-based auth to the API",
  root_priority="high",
  children_json='[
    {"ref": "schema", "title": "Design auth schema", "priority": "high"},
    {"ref": "api",    "title": "Implement auth endpoints", "priority": "high"},
    {"ref": "tests",  "title": "Write auth tests", "priority": "medium"},
    {"ref": "docs",   "title": "Update API docs", "priority": "low"}
  ]',
  deps_json='[
    {"from": "schema", "to": "api"},
    {"from": "api",    "to": "tests"},
    {"from": "api",    "to": "docs"}
  ]'
)
# Returns: root item + 4 children + 3 dependency edges + ref_map for IDs

# 2. Start working — "schema" has no blockers, so it's first
get_next_item()
# → returns "Design auth schema" (highest priority, no deps)

advance_item(item_id="a1b2", trigger="start")
# → status: queue → work (short hex ID — no need for full UUID)

# 3. Add notes as you work
manage_notes(
  operation="upsert",
  item_id="a1b2",
  key="requirements",
  role="queue",
  body="JWT with RS256, refresh tokens, 15min access expiry"
)

# 4. Complete the schema task — this unblocks "api"
advance_item(item_id="a1b2", trigger="complete")
# → status: work → done
# → response includes: unblocked_items: ["Implement auth endpoints"]

# 5. Check what's blocked and what's ready
get_context()
# → Global dashboard: counts, active items, blocked items, stale items, next action

# 6. When the feature is done, batch-complete remaining items
complete_tree(parent_id="f3e4")
# → Completes all non-terminal descendants in dependency order
```

## Note Schemas

Optional YAML config for gate enforcement. Required notes must be filled before phase transitions.

```yaml
# .taskorchestrator/config.yaml
work_item_schemas:
  task:
    lifecycle: auto
    notes:
      - key: requirements
        role: queue
        required: true
        description: "Acceptance criteria before starting"
      - key: done-criteria
        role: work
        required: true
        description: "What does done look like?"
  bug:
    lifecycle: manual
    notes:
      - key: reproduction
        role: queue
        required: true
        description: "Steps to reproduce"
      - key: root-cause
        role: work
        required: true
        description: "Root cause analysis"
```

**Lifecycle modes:**

| Mode | Behavior |
|------|----------|
| `manual` | All phases required (default) |
| `auto` | Skip review if no review-phase notes defined |
| `auto-reopen` | Terminal items reopen when notes are updated |
| `permanent` | Cannot be cancelled |

## Dependencies

Dependencies enforce ordering — blocked items cannot advance until blockers reach the `unblock_at` threshold.

```python
# Linear chain: A must finish before B, B before C
manage_dependencies(operation="pattern", item_ids="id_a,id_b,id_c", pattern="linear")

# Fan-out: A blocks both B and C (parallel after A)
manage_dependencies(operation="pattern", item_ids="id_a,id_b,id_c", pattern="fan-out")

# Fan-in: both A and B must finish before C
manage_dependencies(operation="pattern", item_ids="id_a,id_b,id_c", pattern="fan-in")

# Early unblock: unblock when blocker reaches 'review' instead of 'done'
manage_dependencies(operation="add", from_id="...", to_id="...", unblock_at="review")
```

Cycle detection prevents circular dependencies. `relates_to` type creates informational links without blocking.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TASK_ORCHESTRATOR_DB` | `~/.task-orchestrator/tasks.db` | SQLite database path |
| `TASK_ORCHESTRATOR_CONFIG` | `.taskorchestrator/config.yaml` | Note schema config path |

## MCP Prompts

7 reusable workflow prompts for AI agents: `work_summary`, `create_item_from_context`, `quick_start`, `status_progression`, `dependency_manager`, `batch_complete`, `session_start`.

## Roadmap

| Version | Focus | Features |
|---------|-------|----------|
| **v0.7.0** | Scheduling | Due dates, scheduled items, time-based priority boosting |
| **v0.8.0** | Observability | Workflow metrics, cycle time tracking, CI pipeline |

## Contributing

1. Fork and clone
2. `uv sync` to install dependencies
3. Make changes in `src/task_orchestrator/`
4. Run `uv run python -m task_orchestrator.server` to verify
5. Open a PR against `main`

## License

[MIT](LICENSE)
