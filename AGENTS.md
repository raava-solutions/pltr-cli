# Repository Agent Instructions

These instructions are model-agnostic and apply to every coding agent working in this repository.

## Development

- Use `uv` for dependency management and to run Python commands.
- The wrapped SDK is `foundry-platform-python`; its upstream development branch is `develop`, not `main`.
- Be exact about what the Foundry SDK exposes. Preserve explicit gaps instead of guessing.
- Prefer removing unsupported behavior over returning misleading results.
- Treat Foundry identifiers as RIDs unless a command explicitly accepts an API name.

## Mandatory Foundry change-impact gate

Before planning, proposing, or applying a change to a Foundry ontology resource, action, query, dataset, application, or other Compass resource:

1. Read `skills/pltr-cli/SKILL.md` and `skills/pltr-cli/workflows/change-impact-assessment.md`.
2. Run the matching read-only `pltr dependency` command with the intended `--change`, an explicit `--change-type` when one matches, `--output-mode agent`, and a retained `--graph-output` artifact.
3. Use the returned `agent` block to identify direct and transitive impact paths, action/query contracts, coverage gaps, `must_verify_before_merge`, and `should_verify_before_deploy`.
4. Treat `partial`, `inaccessible`, `unsupported`, `unresolved`, and `budget-exhausted` coverage as uncertainty—not proof that no dependency exists.
5. Do not merge a Foundry change while `agent.status` is `needs-verification` until every relevant `must_verify_before_merge` item is resolved or explicitly accepted by the operator.
6. After the change, rerun the same target with `--compare-artifact <baseline>` and `--output-mode ci`. Exit `0` is clean, `2` needs verification, and `1` is fatal.

The assessment is read-only. It does not authorize or execute a Foundry mutation.

## Skill source of truth

`skills/pltr-cli/` is the single canonical skill bundle for all agent clients. Do not create provider-specific copies. Client-specific instruction files may point here for compatibility but must not duplicate these rules.

## Documented knowledge

`docs/solutions/` records verified lessons by category, and `CONCEPTS.md` defines shared project vocabulary. Consult them when the current work touches a documented area or term.
