# PRD — task-orchestrator-py

## Problema

AI agents perdem rastreio de trabalho complexo entre sessões. Contexto compacta, proxy cai, máquina troca — e o agente não sabe o que foi feito, o que está bloqueado, nem o que vem depois. Soluções baseadas em prompt não sobrevivem a resets. Arquivos JSON/YAML não têm enforcement.

## Personas

1. **Desenvolvedor solo com AI agent** (Claudio) — trabalha em 3 máquinas, 5+ projetos simultâneos, precisa de continuidade entre sessões e isolamento de contexto por workspace.
2. **AI agent (Kiro/Guri)** — consome a API MCP para gerenciar tarefas, precisa de contexto filtrado e acionável, não dump completo.
3. **Subagentes** — recebem contexto de workspace para executar tarefas específicas sem poluição de outros projetos.

## Features

### Implementadas (v0.8.0)
- [x] F001 — Workflow state machine (queue→work→review→done) com enforcement
- [x] F002 — Dependency graph com cycle detection e unblock_at configurável
- [x] F003 — Hierarquia de items (4 níveis: epic→feature→task→subtask)
- [x] F004 — Notes por fase (queue/work/review) com schemas e gates
- [x] F005 — Tags, prioridade, complexidade, due_at
- [x] F006 — Batch operations (create_work_tree, complete_tree, batch transitions)
- [x] F007 — Stale detection e métricas (throughput, WIP, lead time)
- [x] F008 — Export/import do grafo completo (JSON)
- [x] F009 — Scheduling (cron expressions, next_run_at)

### Planejadas (v0.9.0 — Workspace-Aware Context Engine)
- [ ] F010 — Workspace como entidade (config, tag mapping, metadata)
- [ ] F011 — Queries filtradas por workspace (get_context, get_next_item, get_metrics)
- [ ] F012 — get_workspace_context() — contexto pronto para subagentes
- [ ] F013 — Memory tag bridge (2 níveis: inline + referência via mcp-memory)
- [ ] F014 — Resilience (auto-checkpoint JSON, corruption recovery, workspace brief standalone)

### Planejadas (v1.0.0 — Kanban Web UI)
- [ ] F015 — Kanban board por workspace (FastAPI + HTMX + Tailwind)
- [ ] F016 — Timeline/Gantt com dependências
- [ ] F017 — Auto-archive de items done >30d

## Critérios de Aceite (v0.9.0)

- `get_context(workspace="pessoal")` retorna apenas items do workspace
- `get_workspace_context("mir")` gera payload consumível por subagente (<2000 tokens)
- Export filtrado por workspace funciona
- Auto-checkpoint JSON a cada N minutos (configurável)
- Backward compatible (sem workspace = comportamento atual)

## Fora de Escopo

- Multi-user / auth (é single-user, local)
- Sync entre máquinas (resolvido pelo Insync/OneDrive no nível de arquivo)
- Integração direta com GitHub Issues (usamos CLI separado)
- Notificações push (agente consulta, não recebe push)

## Constraints

- SQLite single-file (sync via OneDrive/Insync — pode corromper WAL)
- Roda em 3 máquinas (DNBSCDC289, socrates, sirdata) — resiliência obrigatória
- MCP protocol (stdio transport) — sem HTTP server próprio (exceto Web UI futura)
- Python 3.11+ / PyPI distribution
