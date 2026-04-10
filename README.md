# task-orchestrator-py

Python port of [jpicklyk/task-orchestrator](https://github.com/jpicklyk/task-orchestrator) — an MCP server that gives AI agents a persistent work item graph with workflow enforcement.

[![PyPI](https://img.shields.io/pypi/v/task-orchestrator-py)](https://pypi.org/project/task-orchestrator-py/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Why

AI agents lose track of complex work across sessions. This server provides persistent state: items flow through `queue → work → review → done` with dependency enforcement, note-based documentation, and optional schema gates.

## Quick Start

```bash
# Run directly (no install needed)
uvx task-orchestrator-py

# Or install
pip install task-orchestrator-py
```

### MCP Client Configuration

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

## Tools (14)

### Hierarchy & CRUD
| Tool | Description |
|------|-------------|
| `manage_items` | Create, update, or delete work items |
| `query_items` | Get by ID, search with filters, children, overview |
| `create_work_tree` | Atomically create root + children + dependencies |
| `complete_tree` | Batch-complete descendants in topological order |

### Workflow
| Tool | Description |
|------|-------------|
| `advance_item` | Trigger-based transitions with gate enforcement |
| `get_next_status` | Read-only transition preview before advancing |
| `get_context` | Session resume dashboard or item detail with gate info |
| `get_next_item` | Priority-ranked next actionable item |
| `get_blocked_items` | Items blocked by deps or explicit block |

### Notes
| Tool | Description |
|------|-------------|
| `manage_notes` | Upsert or delete notes on items |
| `query_notes` | Get notes with optional `include_body=false` for token efficiency |

### Dependencies
| Tool | Description |
|------|-------------|
| `manage_dependencies` | Add/remove edges, pattern shortcuts (linear, fan-out, fan-in) |
| `query_dependencies` | Direct neighbors or full BFS graph traversal |

### Schemas
| Tool | Description |
|------|-------------|
| `manage_schemas` | List, inspect, check gates, reload config |

## Workflow

```
queue → work → review → done
  ↘       ↘       ↘
   → blocked (block trigger) → resume → previous status
```

Triggers: `start`, `complete`, `block`, `resume`, `cancel`, `reopen`

## Note Schemas

Optional YAML config for gate enforcement. Required notes must be filled before phase transitions.

```yaml
# .taskorchestrator/config.yaml
work_item_schemas:
  task:
    lifecycle: auto  # auto | manual | auto-reopen | permanent
    notes:
      - key: requirements
        role: queue
        required: true
        description: "Acceptance criteria before starting"
      - key: done-criteria
        role: work
        required: true
        description: "What does done look like?"
```

Lifecycle modes:
- **auto**: skip review if no review-phase notes defined
- **manual**: all phases required (default)
- **auto-reopen**: terminal items reopen when notes are updated
- **permanent**: cannot be cancelled

## Dependencies

```python
# Linear chain: A → B → C
manage_dependencies(operation="pattern", item_ids="id_a,id_b,id_c", pattern="linear")

# Fan-out: A → B, A → C
manage_dependencies(operation="pattern", item_ids="id_a,id_b,id_c", pattern="fan-out")

# Custom unblock threshold (unblock when blocker reaches 'work', not 'done')
manage_dependencies(operation="add", from_id="...", to_id="...", unblock_at="work")
```

## MCP Prompts (7)

Reusable workflow skills: `work_summary`, `create_item_from_context`, `quick_start`, `status_progression`, `dependency_manager`, `batch_complete`, `session_start`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TASK_ORCHESTRATOR_DB` | `~/.task-orchestrator/tasks.db` | SQLite database path |
| `TASK_ORCHESTRATOR_CONFIG` | `.taskorchestrator/config.yaml` | Schema config path |

## License

MIT
