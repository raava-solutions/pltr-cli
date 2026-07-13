# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.16.0-raava.1] - 2026-07-13

### Added
- Profile-aware `pltr mcp serve`, `init`, `switch`, `status`, and `pair` commands
- Claude Code, OpenCode, and OMP support, including OMP user registry sync

### Changed
- `configure set-default` now best-effort synchronizes Claude Code and OMP registrations
- Profile listing now includes richer details, and `configure use` aliases `set-default`

### Security
- Tokens remain in the keyring; generated MCP configs pass only profile names
- OMP updates preserve unrelated servers and use atomic writes

### Verification
- Focused MCP and configuration tests: 15 passing

## [0.4.0] - 2025-01-31

### Added
- Comprehensive folder management functionality
- Preview mode support for folder API operations

### Fixed
- CI pipeline issues
- Code style and formatting improvements

## [0.3.0] - 2024-12-XX

### Added
- Initial release with core CLI functionality
- Palantir Foundry API integration
- Command-line interface for data operations

[0.4.0]: https://github.com/anjor/pltr-cli/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/anjor/pltr-cli/releases/tag/v0.3.0
[0.16.0-raava.1]: https://github.com/raava-solutions/pltr-cli/compare/v0.16.0...v0.16.0-raava.1
