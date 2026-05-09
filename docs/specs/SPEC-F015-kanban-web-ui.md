# SPEC-F015 — Kanban Web UI

## Resumo

Interface web local com board kanban por workspace. Visualização de items por status com drag-and-drop para transições.

## Stack

- **Backend**: FastAPI (já é nosso framework MCP)
- **Frontend**: HTMX + Alpine.js (server-driven, mínimo JS)
- **CSS**: Tailwind CSS (CDN para dev, bundle para prod)
- **Dados**: SQLite read (mesmo DB do MCP server, read-only da UI)
- **Transporte**: HTTP REST (não MCP — UI é cliente separado)

## Arquitetura

```
┌─────────────┐     HTTP      ┌──────────────┐     SQLite     ┌─────────┐
│  Browser    │ ◄──────────► │  FastAPI UI  │ ◄────────────► │  tasks  │
│  (HTMX)    │               │  (porta X)   │                │   .db   │
└─────────────┘               └──────────────┘                └─────────┘
                                     │
                                     │ calls MCP tools
                                     ▼
                              ┌──────────────┐
                              │  Engine.py   │
                              │  (reuse)     │
                              └──────────────┘
```

A UI **não** é um MCP client. É um app FastAPI separado que importa `engine.py` diretamente para queries e `advance_item` para transições via drag-and-drop.

## Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| GET | `/` | Redirect para workspace default ou selector |
| GET | `/board/{workspace}` | Kanban board do workspace |
| GET | `/board/{workspace}/items` | HTMX partial — cards por coluna |
| POST | `/board/{workspace}/move` | Drag-and-drop: move item entre colunas |
| GET | `/workspaces` | Lista de workspaces (selector) |
| GET | `/item/{id}` | Modal/panel com detalhes do item |

## Layout

```
┌─────────────────────────────────────────────────────────────┐
│  [workspace selector ▼]              task-orchestrator v0.9  │
├──────────────┬──────────────┬──────────────┬────────────────┤
│   QUEUE (5)  │   WORK (2)   │  REVIEW (1)  │   DONE (10)    │
├──────────────┼──────────────┼──────────────┼────────────────┤
│ ┌──────────┐ │ ┌──────────┐ │              │                │
│ │ Item A   │ │ │ Item C   │ │              │                │
│ │ 🔴 crit  │ │ │ 🟡 med   │ │              │                │
│ │ #mir     │ │ │ #infra   │ │              │                │
│ └──────────┘ │ └──────────┘ │              │                │
│ ┌──────────┐ │ ┌──────────┐ │              │                │
│ │ Item B   │ │ │ Item D   │ │              │                │
│ │ 🟠 high  │ │ │ 🔵 low   │ │              │                │
│ └──────────┘ │ └──────────┘ │              │                │
└──────────────┴──────────────┴──────────────┴────────────────┘
```

## Cards

Cada card mostra:
- Título (truncado 60 chars)
- Badge de prioridade (🔴 critical, 🟠 high, 🔵 medium, ⚪ low)
- Tags (chips)
- Idade (criado há Xd)
- Ícone 🔗 se tem dependências
- Ícone 🚫 se bloqueado

## Interações

- **Drag-and-drop**: mover card entre colunas = `advance_item(trigger=start|complete)`
- **Click no card**: abre panel lateral com detalhes (descrição, notes, deps)
- **Workspace tabs**: trocar workspace sem reload (HTMX swap)
- **Auto-refresh**: polling a cada 30s (ou SSE se viável)

## Configuração

```bash
# Iniciar UI (separado do MCP server)
task-orchestrator-ui --port 8080 --db ~/dtp/ai-configs/global/tasks.db
```

Ou como subcomando:
```bash
uvx task-orchestrator-py ui --port 8080
```

## Fora de Escopo (v1.0.0)

- Criar/editar items pela UI (só visualizar e mover)
- Auth (é local, single-user)
- Mobile-first (desktop-first, responsivo é bonus)
- Real-time collaboration (single-user)

## Riscos

| Risco | Mitigação |
|-------|-----------|
| SQLite lock entre MCP server e UI | Read-only na UI (WAL permite concurrent reads) |
| HTMX drag-and-drop complexo | Usar SortableJS (lib mínima, integra com HTMX) |
| Tailwind CDN lento | Bundle local para prod |
