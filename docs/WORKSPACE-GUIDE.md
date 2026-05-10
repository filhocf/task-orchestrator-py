# Workspace Guide — 2-Level Context Pattern

## Overview

Workspaces provide **scoped context** for AI agents working across multiple projects. They combine task filtering (via tags) with memory bridge configuration, enabling agents to load only relevant context per workspace.

## 2-Level Context Pattern

### Level 1 — Workspace Config (static)

Defined once via `manage_workspaces(operation="create", ...)`:

| Field | Purpose |
|-------|---------|
| `tags` | Item tags that belong to this workspace (used for filtering) |
| `memory_tags` | Tags to query from memory service for relevant context |
| `description` | Brief purpose of the workspace |
| `repos` | Repository paths associated with this workspace |
| `conventions` | Coding conventions / style rules |

### Level 2 — Runtime Context (dynamic)

Retrieved via `get_workspace_context(workspace_name, verbosity)`:

| Verbosity | Returns |
|-----------|---------|
| `minimal` | workspace name, brief, status_counts, memory_tags, next_item |
| `standard` | + active_items (in work), blocked_items |
| `full` | + recent_decisions (notes with 'decision' in key) |

## Usage Pattern

```
# Session start — load workspace context
context = get_workspace_context("my-project", verbosity="standard")

# Use memory_tags to query memory service
memory_search(tags=context["memory_tags"])

# Work on next_item from the workspace
advance_item(context["next_item"]["id"], "start")
```

## Memory Bridge

The `memory_tags` field bridges task-orchestrator with external memory services. When an agent starts a session:

1. Call `get_workspace_context()` to get `memory_tags`
2. Use those tags to query the memory service for relevant decisions, conventions, and context
3. Combine with `conventions` and `repos` for full project awareness

This avoids loading irrelevant memories from other projects.

## Example

```python
# Create workspace with full config
manage_workspaces(
    operation="create",
    name="backend-api",
    tags="api,backend,auth",
    memory_tags="backend-decisions,api-patterns",
    description="Backend REST API service",
    repos="~/git/api-service",
    conventions="PEP8,type hints,pytest"
)

# At session start
ctx = get_workspace_context("backend-api", verbosity="standard")
# ctx.memory_tags → ["backend-decisions", "api-patterns"]
# ctx.active_items → items currently in work
# ctx.next_item → highest priority actionable item
```
