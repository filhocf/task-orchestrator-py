# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Due dates with deadline alerts (#5)
- CI pipeline with GitHub Actions (#9, #12)
- PR template and Dependabot configuration
- This CHANGELOG

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

[Unreleased]: https://github.com/filhocf/task-orchestrator-py/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/filhocf/task-orchestrator-py/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/filhocf/task-orchestrator-py/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/filhocf/task-orchestrator-py/releases/tag/v0.2.0
