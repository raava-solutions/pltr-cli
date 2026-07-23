# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

_No changes yet._

## [0.21.0] - 2026-07-23

### Added

- Added `pltr search <text>` for cross-resource search across Foundry, returning matching resources with their type and path.


## [0.20.0] - 2026-07-23

### Added

- Completed full-lifecycle change-impact analysis: `pltr dependency` now answers "what breaks downstream if I change this" across the whole Foundry lifecycle, both above and below the ontology.
- Added transport selection with `--providers sdk,conjure,graphql` and a configuration-gated `--positive-controls` flag for firing endpoint canaries, alongside the existing `--no-internal` public-SDK-only fallback.
- Added degraded-mode reporting. An unreachable, permission-denied, or drifted internal endpoint records a coverage gap and the command still exits successfully with the public-SDK graph intact. Only target resolution, artifact writes, and authentication remain fatal.

### Changed

- Internal transport failures now report as inconclusive rather than partial. A partial result implies some data was obtained; no internal response means absence was never tested, and the two must not be confused.

### Fixed

- The fail-toward-false-safety contract is now mechanically enforced rather than conventional. Every internal operation is characterized against empty, truncated, and permission-denied responses and must not report verified-empty coverage. The single sanctioned exception, a build specification proving a dataset has no producing transform, requires both a passing endpoint canary and independent confirmation that the dataset exists.
- Added registry-completeness, canary-contract, and provenance-resolution checks, plus permanent regression guards for out-of-order streamed responses, omitted branch fallbacks, and resources absent from the lineage index.

### Known limitations

- Workshop variables remain unreadable on the verified stack.
- Notepad object-reference widget configurations remain bundle-derived and are not resolved to ontology bindings.

## [0.19.1] - 2026-07-22

### Added

- Added reverse dependency analysis over Foundry's internal APIs: object types to the Workshop modules and third-party applications that consume them, per-application SDK version ranges for consumers, code repository to transform to dataset lineage, and property to dataset column mapping.
- Added `pltr notepad get` for reading a notepad's latest body and its embedded resource references.
- Added a Palantir expert benchmark corpus and scorer for grading command-contract knowledge.

### Changed

- Upgraded runtime and development dependencies, and hardened continuous integration with a locked dependency sync and a runtime dependency audit.

### Fixed

- Fixed `pltr notepad get` reporting an inconclusive read for every notepad, caused by requesting a composite metadata field without a subselection.
- Restored the ontology action and object read commands after platform SDK drift.

### Known limitations

- Internal-API coverage degrades explicitly. Empty, truncated, permission-denied, and expired-token results are reported as inconclusive, never as verified absence.

## [0.18.0] - 2026-07-20

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

[0.18.0]: https://github.com/zaycruz/pltr-cli/compare/v0.17.1...v0.18.0
[0.4.0]: https://github.com/anjor/pltr-cli/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/anjor/pltr-cli/releases/tag/v0.3.0
