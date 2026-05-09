# SPEC-F017 — Auto-Archive Done Items

## Resumo

Mover items completados há mais de N dias para estado "archived", limpando as views ativas sem perder dados.

## Design

### Novo status: `archived`

Extensão do state machine:
```
done ──(30 dias)──► archived
archived ──(reopen)──► queue  (se precisar reativar)
```

### Regras

- Items em `done` há mais de `archive_after_days` (default: 30) → archived
- Configurável por workspace (workspace com muita rotação pode ter 7d)
- Archived items **excluídos** de: `get_context()`, `get_next_item()`, kanban board
- Archived items **incluídos** em: `get_context(include_archived=true)`, timeline, export
- Notes e dependencies preservados integralmente

### Trigger

Não é background job. Opções:
1. **Tool explícito**: `manage_archive(operation=run|configure|stats)`
2. **Automático no get_context**: se detectar items elegíveis, arquivar silenciosamente
3. **Cron via scheduling** (já temos infra de cron no orchestrator)

Recomendação: opção 1 + 3 (tool + cron schedule). O agente pode rodar `manage_archive(operation=run)` no startup ou via schedule.

### Configuração

```json
{
  "archive_after_days": 30,
  "per_workspace": {
    "dtp": 60,
    "pessoal": 14
  }
}
```

## Endpoints (Web UI)

| Método | Path | Descrição |
|--------|------|-----------|
| GET | `/archive/{workspace}` | Lista items arquivados |
| POST | `/archive/{workspace}/run` | Trigger manual de archiving |

## Métricas

- `get_metrics()` inclui: `archived_count`, `archived_this_period`
- Útil para ver throughput real (done + archived = trabalho concluído)

## Fora de Escopo

- Deletar items permanentemente (archive é soft-delete)
- Compressão de notes antigos (manter tudo)
- Export automático antes de arquivar (checkpoint já cobre isso)

## Depende de

- Workspace entity (#24/PR #33) — para config per-workspace
