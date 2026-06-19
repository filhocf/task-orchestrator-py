# Web UI — Task Orchestrator

## Status

- **Board kanban** (#29): implementado com swimlanes + sort
- **Timeline** (#30): implementado
- **Vista de arcos**: implementada com grafo Cytoscape.js

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend | FastAPI + Uvicorn |
| Templates | Jinja2 (server-side render) |
| Interatividade | HTMX (drag-drop, partial updates) |
| Estilo | Tailwind CSS (inline) |
| Grafos | Cytoscape.js + dagre layout (CDN) |
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

## Ativação

Env var `MCP_UI_ENABLED=1` para ativar a UI no service (quando integrado). Standalone via entry point não precisa.

## Rotas existentes

| Rota | Descrição |
|------|-----------|
| `GET /` | Redirect para primeiro workspace |
| `GET /board/{workspace}` | Kanban board (queue/work/review/done) |
| `GET /board/{workspace}/column/{status}` | Partial HTMX de uma coluna |
| `POST /board/move` | Mover item entre colunas (advance_item) |
| `GET /timeline/{workspace}` | Timeline com dependências |
| `GET /arcs` | Lista de arcos (sort A-Z/Z-A) |
| `GET /arcs/{item_id}` | Detalhe do arco com grafo + árvore |
| `GET /arcs/{item_id}/children` | Partial HTMX: filhos de um nó |
| `GET /item/{item_id}` | Partial: detalhe de item (modal) |

## Grafo de Arcos

Visualização interativa do grafo de dependências/hierarquia de cada arco.

**Tecnologia**: Cytoscape.js com layout dagre (direção LR — esquerda para direita).

**Funcionalidades**:
- Nós coloridos por status: done (verde), work (azul), review (roxo), blocked (vermelho), queue (cinza)
- Nó raiz com borda azul mais grossa
- Click-to-detail: clicar num nó abre modal com detalhes do item
- Edges com seta indicando direção de dependência
- Filtragem: mostra apenas waves + items com deps + items com filhos (mesma lógica anterior)
- Fallback: se nenhum item qualifica, mostra todos os filhos diretos

**CDN (sem deps locais)**:
- `cytoscape@3` — engine de grafos
- `dagre@0.8` — algoritmo de layout hierárquico
- `cytoscape-dagre@2` — plugin de integração

## Pendente

### Fixes no skeleton

- DB path não é descoberto automaticamente (precisa env var)
- Board não tem feedback visual de erro
- Timeline sem estilo (HTML cru)

## Changelog

| Feature | Descrição |
|---------|-----------|
| Sort A-Z/Z-A | Ordenação alfabética de lanes e arcos |
| Legendas | Cores por status + emojis de prioridade |
| Swimlanes | Agrupamento de itens por arco ancestral |
| Cytoscape grafo | Grafo interativo de dependências (substituiu Mermaid) |
| MCP_UI_ENABLED | Env var para ativar UI no service |

## Referências

- Issues: #29 (board), #30 (timeline)
- Entry point: `pyproject.toml` → `task-orchestrator-ui`
- Código: `src/task_orchestrator/ui/`
