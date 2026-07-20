# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added Compass discovery commands for namespace-like Foundry Space listing, project imports, and bounded project search.
- Added dataset statistics with file and transaction aggregates, pagination limits, and coverage metadata.
- Added bounded resource graphs with stable RID-based identities for filesystem hierarchy and project-reference relationships.

### Changed

- Added a native agent output contract and capability manifest with pagination metadata, redaction, explicit errors, and safety gates.
- Removed the MCP launcher integration; native `pltr` commands are the supported agent interface.

### Known limitations

- Project-template listing remains explicitly unsupported because the pinned SDK exposes template creation but no public template catalog operation.
- Namespace discovery is namespace-like Space discovery; no separate public Namespace API is exposed by the pinned SDK.
- Resource graphs do not represent full transformation lineage and report incomplete coverage when applicable.

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
