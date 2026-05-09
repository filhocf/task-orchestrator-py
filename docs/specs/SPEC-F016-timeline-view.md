# SPEC-F016 — Timeline View

## Resumo

Visualização temporal de items com dependências como setas. Mostra progresso do workspace ao longo do tempo.

## Design

```
Timeline: ──────────────────────────────────────────────────────►
           Mai 3        Mai 6        Mai 9        Mai 12

  Item A   ████████████████░░░░░░░░░  (queue→work, 6 dias)
                    │
                    ▼ (blocks)
  Item B            ░░░░░████████████  (queue, aguardando A)

  Item C   ██████████████████████████████████  (work, 9 dias, stale!)

  Item D                        ████████  (done em 3 dias)
```

## Stack

- Mesmo app FastAPI da Kanban UI (nova rota `/timeline/{workspace}`)
- SVG gerado server-side (Python) OU lib JS leve (vis-timeline / custom canvas)
- Preferência: SVG server-side com HTMX (zero JS dependency extra)

## Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| GET | `/timeline/{workspace}` | Página com timeline |
| GET | `/timeline/{workspace}/svg` | SVG puro (embeddable) |

## Dados por item

- Início: `created_at`
- Fim: `updated_at` (se done/cancelled) ou `now` (se ativo)
- Cor: por prioridade ou por status
- Setas: dependências (`from_id` → `to_id`)
- Highlight: items bloqueados (vermelho), stale (amarelo)

## Interações

- Hover: tooltip com título + descrição
- Click: navega para detalhes do item
- Zoom: scroll horizontal (semana/mês/trimestre)
- Filtro: por prioridade, por status

## Fora de Escopo

- Edição inline (não é Gantt editor)
- Estimativas de duração (não temos esse dado)
- Critical path calculation (complexo demais para v1)

## Depende de

- SPEC-F015 (Kanban Web UI) — mesmo app, mesma infra
