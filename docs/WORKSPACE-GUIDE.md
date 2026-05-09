# Workspace Guide

## Overview

Workspaces group related items by tags, enabling scoped queries and context isolation. Each workspace maps to a set of item tags and optional metadata for richer context.

## Configuration

Workspaces are stored in `workspaces.json` (next to the DB file). Create via the `manage_workspaces` tool or edit the JSON directly.

### Schema

```json
{
  "workspace_name": {
    "tags": ["tag1", "tag2"],
    "memory_tags": ["mem-tag1", "mem-tag2"],
    "repos": ["/path/to/repo"],
    "conventions": "Free-text coding conventions",
    "description": "Brief description of this workspace"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tags` | list[str] | yes | Item tags that belong to this workspace. Used to filter items in scoped queries. |
| `memory_tags` | list[str] | no | Tags to search in external memory service (mcp-memory-service). |
| `repos` | list[str] | no | Repository paths associated with this workspace. |
| `conventions` | str | no | Coding conventions, style rules, or patterns for this workspace. |
| `description` | str | no | Workspace brief — injected into context for subagents. |

## The 2-Level Context Pattern

Task orchestrator uses a 2-level documentation strategy:

### Level 1 — Inline (always available)

Lives in the orchestrator DB. Returned by `get_context`, `get_workspace_context`.

- **Items**: tasks, their status, dependencies, hierarchy
- **Notes**: per-phase documentation (queue/work/review)
- **Workspace brief**: the `description` field — concise summary for subagents

This is the "working memory" — always available, always current.

### Level 2 — Reference (on-demand)

Lives in **mcp-memory-service**. Accessed via `memory_tags`.

- Architecture decisions, ADRs
- Deep technical context (how systems work, why decisions were made)
- Historical context (past bugs, lessons learned)
- Domain knowledge (business rules, API specs)

This is the "long-term memory" — rich context fetched when needed.

### How It Works

1. Agent calls `get_context(workspace="dtp")` → gets Level 1 (items, notes, brief)
2. Agent sees `memory_tags: ["mir", "dtp"]` in workspace config
3. Agent calls `memory_search(tags=["mir"])` → gets Level 2 (deep context)

The orchestrator **never** calls memory service directly. It provides the tags; the agent decides when to fetch deeper context.

## Subagent Usage

When spawning a subagent for a workspace task:

1. Call `get_context(workspace="name")` for the task list and brief
2. Pass `memory_tags` to the subagent so it can fetch relevant memories
3. Include `conventions` in the subagent prompt for style consistency
4. Reference `repos` for the subagent to know which codebases to work on

## Examples

### Work Project (dtp)

```json
{
  "dtp": {
    "tags": ["mir", "rer", "dtp"],
    "memory_tags": ["mir", "dtp", "dataprev"],
    "repos": ["~/git/task-orchestrator-py", "~/git/mir-frontend"],
    "conventions": "Python 3.11+, pytest, ruff. PRs required. Conventional commits.",
    "description": "Dataprev work projects — MIR (Jenkins MCP), RER (React migration), task-orchestrator."
  }
}
```

### Personal Project (pessoal)

```json
{
  "pessoal": {
    "tags": ["papo-saude", "finance", "home"],
    "memory_tags": ["pessoal", "health", "finance"],
    "repos": ["~/git/papo-saude"],
    "conventions": "TypeScript, Next.js 14, Tailwind. Move fast, minimal tests.",
    "description": "Personal projects — health tracker, finance tools, home automation."
  }
}
```

### Infrastructure (infra)

```json
{
  "infra": {
    "tags": ["infra", "k8s", "ci"],
    "memory_tags": ["infra", "kubernetes", "jenkins"],
    "repos": ["~/git/infra-as-code", "~/git/jenkins-configs"],
    "conventions": "Terraform, Helm charts, GitOps. Always plan before apply.",
    "description": "Infrastructure — Kubernetes clusters, CI/CD pipelines, monitoring."
  }
}
```

## Tool Usage

```
# Create workspace
manage_workspaces(operation="create", name="dtp", tags="mir,rer", memory_tags="mir,dtp", repos="~/git/mir", conventions="Python 3.11+", description="Work projects")

# Update workspace
manage_workspaces(operation="update", name="dtp", description="Updated description")

# List all
manage_workspaces(operation="list")

# Delete
manage_workspaces(operation="delete", name="dtp")
```
