# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- `get_project_graph_metrics` — critical path, max fan-out, distance to goal

## [1.1.0] - 2026-06-08

### Added
- `get_execution_stack` tool — context stack for session resume after interruptions
- `manage_archive` tool — auto-archive done items older than N days
- `manage_checkpoints` tool — create/list/restore/verify JSON snapshots
- `get_workspace_context` tool — workspace payload at 3 verbosity levels (minimal/standard/full)
- Workspace `repos` and `conventions` fields

### Changed
- Test suite expanded to 114+ tests

## [1.0.0] - 2026-05-28

### Added
- **StreamableHTTP transport** on port 3201 (`MCP_TRANSPORT=streamable-http`)
- systemd service support (task-orchestrator.service)
- `manage_workspaces` tool — create/update/delete/list workspace configs
- Workspace-scoped queries in `get_context`, `get_next_item`, `get_metrics`
- `export_graph` and `import_graph` tools with workspace/tag filtering
- Kanban Web UI skeleton (FastAPI + HTMX + Tailwind)

### Changed
- Default transport remains stdio for backward compatibility

## [0.9.0] - 2026-05-18

### Added
- Workspace entity — tag mapping, memory_tags, description
- Workspace-filtered `get_context`, `get_next_item`, `get_metrics`
- Memory tag bridge (2 levels: inline + reference via memory service)
- Auto-checkpoint JSON resilience (corruption recovery)

## [0.8.0] - 2026-05-10

### Added
- Scheduling support (cron expressions, `next_run_at`)
- `due_at` field on work items with deadline alerts

### Fixed
- croniter naive/aware datetime handling
- CI pipeline stabilization

## [0.7.0] - 2026-05-06

### Added
- `get_metrics` tool — throughput per week, lead time, WIP, stale ratio
- Priority and tag breakdowns in metrics
- Configurable lookback period (days param)
- `complete_tree` tool — batch-complete descendants in topological order
- `create_work_tree` — atomically create root + children + dependencies

## [0.6.1] - 2026-05-02

### Added
- Comprehensive test suite with 35+ tests (#9)

### Changed
- Comprehensive README rewrite (#11)

## [0.6.0] - 2026-05-02

### Added
- Stale item detection in get_context (#4)
- Structured ToolError responses (#3)
- Filter query_items by tags (#2)
- Short hex ID resolution (4+ chars) (#1)

## [0.5.0] - 2026-04-10

### Added
- Full feature parity with original Kotlin task-orchestrator

## [0.4.0] - 2026-04-10

### Added
- Auto-reopen parent items from terminal status
- `unblock_at` threshold for dependencies
- README documentation

## [0.3.0] - 2026-04-10

### Added
- MCP prompts (workflow skills)
- Note schema gates

## [0.2.0] - 2026-04-10

### Added
- Full feature parity with original task-orchestrator
- Note schemas with gate enforcement
- Lifecycle modes
- GitHub Actions workflow for PyPI trusted publishing
- Initial Python port of task-orchestrator

[Unreleased]: https://github.com/filhocf/task-orchestrator-py/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/filhocf/task-orchestrator-py/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.9.0...v1.0.0
[0.9.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/filhocf/task-orchestrator-py/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/filhocf/task-orchestrator-py/releases/tag/v0.2.0
