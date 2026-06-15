# GOAL: Web UI funcional com Vista de Arcos

## Critérios de Aceite (para /goal)

```bash
/goal --max 8 Implementar a web UI do task-orchestrator com vista de arcos. Critérios:
1. `uv run task-orchestrator-ui --port 8080` sobe sem erro com TASK_ORCHESTRATOR_DB=~/local-data/mcp/tasks.db
2. GET /board/harness retorna HTTP 200 com itens reais do banco
3. GET /arcs retorna HTTP 200 com lista de arcos (items com tag 'arc')
4. GET /arcs/{item_id} retorna HTTP 200 com árvore hierárquica expandida (filhos recursivos)
5. A árvore mostra: título, status, priority_emoji, contagem de filhos done/total
6. Dependências entre nós são visíveis (linhas ou lista)
7. Todos os testes existentes continuam passando (pytest tests/ -q)
```

## Escopo detalhado

### Fase 1: Fix skeleton (board funciona)
- Env var `TASK_ORCHESTRATOR_DB` descoberta automaticamente (fallback: `~/local-data/mcp/tasks.db`)
- Board carrega sem 500
- Drag-drop funcional

### Fase 2: Vista de Arcos (nova rota)
- `GET /arcs` — lista todos os items com tag `arc` (raízes de arco)
- `GET /arcs/{item_id}` — árvore hierárquica:
  - Busca filhos recursivamente (até 4 níveis)
  - Mostra status consolidado (X done / Y total)
  - Expandir/colapsar via HTMX
  - Dependências como lista ou linhas SVG simples

### Fase 3: Navegação
- Navbar: Board | Timeline | Arcs
- Sidebar workspaces funciona para todas as vistas

## Não-escopo (futuro)
- Edição inline de items
- Criação de items via UI
- Auth/login
- Deploy externo

## Como rodar o goal

```bash
# Na sessão Kiro CLI:
/goal --max 8 Implementar web UI task-orchestrator com vista de arcos funcional. \
  Critérios: 1) uv run task-orchestrator-ui sobe sem erro com DB real (tasks.db), \
  2) GET /board/harness retorna 200 com items, \
  3) GET /arcs retorna 200 listando items com tag arc, \
  4) GET /arcs/{id} retorna árvore hierárquica com filhos recursivos e status consolidado, \
  5) pytest tests/ passa sem regressão.
```
