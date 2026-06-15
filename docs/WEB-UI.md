# Web UI — Task Orchestrator

## Status

- **Board kanban** (#29): skeleton implementado, quebrado (DB path)
- **Timeline** (#30): skeleton implementado, sem teste
- **Vista de arcos**: NÃO EXISTE (próximo a implementar)

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | FastAPI + Uvicorn |
| Templates | Jinja2 (server-side render) |
| Interatividade | HTMX (drag-drop, partial updates) |
| Estilo | Tailwind CSS (inline) |
| DB | SQLite — mesmo banco do MCP service |

Zero dependências fora do Python. Instalação: `uv sync --extra ui`.

## Como erguer

```bash
# Variável obrigatória — apontar para o banco do service
export TASK_ORCHESTRATOR_DB=~/local-data/mcp/tasks.db

# Opção 1: entry point
uv run task-orchestrator-ui --port 8080

# Opção 2: módulo direto
uv run python -m task_orchestrator.ui.app --port 8080

# Abrir: http://localhost:8080
```

## Rotas existentes

| Rota | Descrição |
|------|-----------|
| `GET /` | Redirect para primeiro workspace |
| `GET /board/{workspace}` | Kanban board (queue/work/review/done) |
| `GET /board/{workspace}/column/{status}` | Partial HTMX de uma coluna |
| `POST /board/move` | Mover item entre colunas (advance_item) |
| `GET /timeline/{workspace}` | Timeline com dependências |

## Pendente

### Vista de Arcos (nova)

Visualizar hierarquia de arcos: ARC → SUB-ARC → WAVE → tarefas.
- Filtrar por tag `arc`
- Expandir/colapsar níveis
- Mostrar status consolidado (% done)
- Mostrar dependências entre nós

### Fixes no skeleton

- DB path não é descoberto automaticamente (precisa env var)
- Board não tem feedback visual de erro
- Timeline sem estilo (HTML cru)

## Referências

- Issues: #29 (board), #30 (timeline)
- Entry point: `pyproject.toml` → `task-orchestrator-ui`
- Código: `src/task_orchestrator/ui/`
