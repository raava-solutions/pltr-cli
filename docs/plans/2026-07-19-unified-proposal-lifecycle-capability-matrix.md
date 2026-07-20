# Proposal Lifecycle Capability Matrix

This matrix separates provider capability verified through the authenticated
Foundry MCP catalog from operations reachable through this repository's pinned
`foundry-platform-sdk==1.95.0` client. A provider capability is executable by
`pltr` only when both columns are verified.

| Proposal type | Operation | Authenticated MCP catalog | SDK 1.95.0 client | `pltr` behavior |
| --- | --- | --- | --- | --- |
| `code-pr` | create | Verified | No client surface | `unsupported-capability` |
| `code-pr` | list | Verified | No client surface | `unsupported-capability` |
| `code-pr` | get | Verified | No client surface | `unsupported-capability` |
| `code-pr` | comment | Verified | No client surface | `unsupported-capability` |
| `code-pr` | approve | Unsupported | No client surface | `unsupported-capability` |
| `code-pr` | request changes | Unsupported | No client surface | `unsupported-capability` |
| `code-pr` | merge | Unsupported | No client surface | `unsupported-capability` |
| `code-pr` | close | Unsupported | No client surface | `unsupported-capability` |
| `global-proposal` | create | Verified | No client surface | `unsupported-capability` |
| `global-proposal` | list | Unsupported | No client surface | `unsupported-capability` |
| `global-proposal` | get | Verified | No client surface | `unsupported-capability` |
| `global-proposal` | comment | Unsupported | No client surface | `unsupported-capability` |
| `global-proposal` | approve | Unsupported | No client surface | `unsupported-capability` |
| `global-proposal` | request changes | Unsupported | No client surface | `unsupported-capability` |
| `global-proposal` | accept | Unsupported | No client surface | `unsupported-capability` |
| `global-proposal` | close | Verified | No client surface | `unsupported-capability` |

## Installed-client evidence

The official SDK tag `1.95.0` defines `FoundryClient` namespaces for admin,
AIP agents, audit, checkpoints, connectivity, data health, datasets,
filesystem, functions, language models, media sets, models, ontologies,
orchestration, SQL queries, streams, third-party applications, and widgets.
It defines neither a Code Repositories namespace nor a Global Proposal
namespace.

The CLI therefore does not import a guessed SDK resource, call an undocumented
HTTP endpoint, invoke a UI fallback, or report simulated success. Every command
requires the explicit type (`code-pr` or `global-proposal`) and returns the
typed `unsupported-capability` error with a nonzero exit until an installed,
verified client exposes the operation.

Global Proposal close retains the command-level safety contract for when the
client surface becomes available: JSON automation requires `--yes`; interactive
use refreshes state before prompting; and provider errors are surfaced without
claiming optimistic-concurrency protection that has not been verified.
