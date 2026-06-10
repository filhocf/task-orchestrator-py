# PRD — task-orchestrator-py

## Problema

AI agents perdem rastreio de trabalho complexo entre sessões. Contexto compacta, proxy cai, máquina troca — e o agente não sabe o que foi feito, o que está bloqueado, nem o que vem depois. Soluções baseadas em prompt não sobrevivem a resets. Arquivos JSON/YAML não têm enforcement.

## Personas

1. **Desenvolvedor solo com AI agent** (Claudio) — trabalha em 3 máquinas, 5+ projetos simultâneos, precisa de continuidade entre sessões e isolamento de contexto por workspace.
2. **AI agent (Kiro/Guri)** — consome a API MCP para gerenciar tarefas, precisa de contexto filtrado e acionável, não dump completo.
3. **Subagentes** — recebem contexto de workspace para executar tarefas específicas sem poluição de outros projetos.

## Transport

**StreamableHTTP** na porta 3201 (`MCP_TRANSPORT=streamable-http`, `MCP_HOST`, `MCP_PORT`).
Fallback stdio disponível (default quando MCP_TRANSPORT não definido).
Deploy via systemd service.

## Features

### Implementadas (v1.1.0) — 22 tools MCP

- ✅ F001 — Workflow state machine (queue→work→review→done) com enforcement
- ✅ F002 — Dependency graph com cycle detection e unblock_at configurável
- ✅ F003 — Hierarquia de items (4 níveis: epic→feature→task→subtask)
- ✅ F004 — Notes por fase (queue/work/review) com schemas e gates
- ✅ F005 — Tags, prioridade, complexidade, due_at
- ✅ F006 — Batch operations (create_work_tree, complete_tree, batch transitions)
- ✅ F007 — Stale detection e métricas (throughput, WIP, lead time)
- ✅ F008 — Export/import do grafo completo (JSON) com filtro por workspace/tags
- ✅ F009 — Scheduling (cron expressions, next_run_at)
- ✅ F010 — Workspace como entidade (config, tag mapping, memory_tags, repos, conventions)
- ✅ F011 — Queries filtradas por workspace (get_context, get_next_item, get_metrics)
- ✅ F012 — get_workspace_context() — contexto pronto para subagentes (3 verbosities)
- ✅ F013 — Memory tag bridge (2 níveis: inline + referência via mcp-memory)
- ✅ F014 — Resilience (manage_checkpoints, verify, corruption recovery)
- ✅ F015 — Execution stack (get_execution_stack) — retomada pós-interrupção
- ✅ F016 — Auto-archive (manage_archive) — done items >Nd movidos para archived
- ✅ F017 — StreamableHTTP transport com systemd service

### Em Progresso (v1.2.0 — Kanban Web UI)

- [ ] F018 — Kanban board por workspace (FastAPI + HTMX + Tailwind)
- [ ] F019 — Timeline/Gantt com dependências

### Planejadas (v1.3.0 — Graph Analytics)

- [ ] F020 — get_project_graph_metrics (caminho crítico, fan-out máximo, distância ao goal)
- [ ] F021 — Bottleneck detection (items com mais dependentes bloqueados)

## Critérios de Aceite (v1.2.0)

- Kanban board renderiza items por status com drag-and-drop
- Filtro por workspace funciona no UI
- Responsivo (mobile-friendly)

## Fora de Escopo

- Multi-user / auth (é single-user, local)
- Sync entre máquinas (resolvido pelo Insync/OneDrive no nível de arquivo)
- Integração direta com GitHub Issues (usamos CLI separado)
- Notificações push (agente consulta, não recebe push)

## Constraints

- SQLite single-file (sync via OneDrive/Insync — pode corromper WAL)
- Roda em 3 máquinas (DNBSCDC289, socrates, sirdata) — resiliência obrigatória
- MCP protocol: StreamableHTTP (porta 3201) + stdio fallback
- Python 3.11+ / PyPI distribution
