# MEMORY.md — task-orchestrator-py

## Estado Atual

**Versão**: 0.8.0 (PyPI)
**Branch principal**: main
**CI**: GitHub Actions (ruff lint + pytest)
**Último release**: v0.8.0 (croniter fix, datetime naive/aware)

## Em Andamento

### v0.9.0 — Workspace-Aware Context Engine
- Issues #24–#28 criadas no GitHub (09/mai/2026)
- Milestone criado
- Labels: workspace, context-engine, resilience
- Ordem: #24 (entity) + #28 (resilience) paralelos → #25 (scoped queries) → #27 (memory bridge) → #26 (workspace context)
- Nenhuma implementação iniciada ainda

### v1.0.0 — Kanban Web UI
- Issues #29–#31 criadas
- Depende de v0.9.0 (workspace entity)
- Stack definida: FastAPI + HTMX + Alpine.js + Tailwind CSS

## Decisões Recentes

| Data | Decisão |
|------|---------|
| 09/mai | Workspace como filtro de tags (não campo novo no DB inicialmente) |
| 09/mai | 2 níveis de contexto: inline (orchestrator) + referência (memory tags) |
| 09/mai | Web UI com HTMX (server-driven, sem SPA pesado) |
| 09/mai | PRs obrigatórios com Gemini Code Assist review |
| 09/mai | Resiliência: auto-checkpoint JSON + standalone .md briefs |

## Próximos Passos

1. Criar docs/specs/ com SPEC por feature (#24–#28)
2. Implementar #24 (workspace entity) — branch feat/workspace-entity
3. Implementar #28 (resilience) em paralelo — branch feat/resilience
4. Testar, PR, review, merge, tag v0.9.0

## Contexto Multi-Máquina

- DB: `~/dtp/ai-configs/global/tasks.db` (sync via Insync/OneDrive)
- Risco: WAL corruption se 2 máquinas escrevem simultaneamente
- Mitigação: auto-checkpoint JSON + hot backup + import com dedup
