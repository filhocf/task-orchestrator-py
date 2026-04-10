# task-orchestrator-py

Python port of [jpicklyk/task-orchestrator](https://github.com/jpicklyk/task-orchestrator) — an MCP server for AI agent work management.

Persistent work item graph with workflow enforcement, dependency tracking, and session-resumable context. Runs natively with `uvx` — no Docker required.

## Quick Start

```bash
# Run directly (no install needed)
uvx --from git+https://github.com/filhocf/task-orchestrator-py.git task-orchestrator-py

# Or install and run
pip install git+https://github.com/filhocf/task-orchestrator-py.git
task-orchestrator-py
```

## MCP Configuration

```json
{
  "mcpServers": {
    "task-orchestrator": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/filhocf/task-orchestrator-py.git", "task-orchestrator-py"]
    }
  }
}
```

Database defaults to `~/.task-orchestrator/tasks.db`. Override with:
```json
"env": {"TASK_ORCHESTRATOR_DB": "/path/to/tasks.db"}
```

## Tools (10)

| Tool | Description |
|------|-------------|
| `manage_items` | Create, update, delete work items |
| `query_items` | Get by ID, list with filters, overview |
| `advance_item` | Trigger-based workflow transitions |
| `get_next_item` | Priority-ranked next actionable item |
| `get_context` | Session resume — global dashboard or item detail |
| `get_blocked_items` | All items blocked by deps or explicit block |
| `manage_notes` | Persistent per-phase documentation on items |
| `manage_dependencies` | Add/remove/query dependency edges |
| `create_work_tree` | Atomic creation of root + children + deps |

## Workflow

```
queue → work → review → done
  ↓       ↓       ↓
  └── blocked ──→ resume → previous status
  
Any → cancelled (via cancel trigger)
done/cancelled → queue (via reopen trigger)
```

Triggers: `start`, `complete`, `block`, `resume`, `cancel`, `reopen`

## What's Implemented (v0.1)

- ✅ WorkItems with hierarchy (4 levels deep)
- ✅ Status workflow with trigger-based transitions
- ✅ Dependency graph with cycle detection
- ✅ Dependency enforcement on advance
- ✅ Notes per item/phase
- ✅ `get_next_item()` — priority-ranked next action
- ✅ `get_context()` — session resume
- ✅ `get_blocked_items()` — blocked item detection
- ✅ `create_work_tree()` — atomic tree creation
- ✅ SQLite persistence (WAL mode)

## Not Yet Implemented

Features from the [original Kotlin project](https://github.com/jpicklyk/task-orchestrator) to port:

- [ ] Note schemas (YAML config, phase gate enforcement)
- [ ] Lifecycle modes (linear, milestone, exploratory)
- [ ] Sub-agent orchestration
- [ ] HTTP transport mode
- [ ] `complete_tree` (batch complete descendants)
- [ ] Plugin system (skills, hooks)
- [ ] Output styles

Track the original project for new features: https://github.com/jpicklyk/task-orchestrator/releases

## License

MIT — see [LICENSE](LICENSE). Based on [jpicklyk/task-orchestrator](https://github.com/jpicklyk/task-orchestrator).
