# MEMORY.md — task-orchestrator-py

## Estado Atual

**Versão**: 1.1.0 (PyPI) | **Branch**: main | **Testes**: 114+
**Transport**: StreamableHTTP porta 3201 (MCP_TRANSPORT=streamable-http) + stdio fallback
**Deploy**: systemd service (task-orchestrator.service)
**Tools MCP**: 22 | **CI**: GitHub Actions (ruff + pytest)

## Features Principais

- Workflow engine: queue→work→review→done com enforcement + batch transitions
- Dependency graph com cycle detection, unblock_at, patterns (linear/fan-out/fan-in)
- Hierarquia 4 níveis + create_work_tree + complete_tree
- Notes com schemas e gate enforcement por fase
- **Workspaces**: entidade com tags, memory_tags, repos, conventions
- **get_workspace_context**: payload filtrado por workspace (3 verbosities)
- **get_execution_stack**: context stack para retomada pós-interrupção
- **manage_archive**: auto-archive items done >Nd
- **manage_checkpoints**: create/list/restore/verify (JSON snapshots)
- **export/import_graph**: backup completo filtrado por workspace/tags
- **get_metrics**: throughput, lead time, WIP, stale ratio, breakdowns

## Próximos Passos

- get_project_graph_metrics (caminho crítico, fan-out máximo, distância ao goal)
- Kanban Web UI (FastAPI + HTMX + Tailwind) — em progresso

## Contexto Multi-Máquina

- DB: SQLite single-file (sync via Insync/OneDrive)
- Mitigação WAL: manage_checkpoints + export_graph JSON
