# Dependency Analysis Commands

Use `pltr dependency` for a read-only, evidence-backed assessment of one
addressable Foundry target. One invocation resolves the target, discovers a
bounded graph, writes the complete graph artifact, and renders the requested
view. Rendering never triggers a second discovery pass.

## Direct targets

```bash
pltr dependency object-type ONTOLOGY_RID OBJECT_TYPE
pltr dependency property ONTOLOGY_RID OBJECT_TYPE PROPERTY
pltr dependency link-type ONTOLOGY_RID OBJECT_TYPE LINK_TYPE
pltr dependency action-type ONTOLOGY_RID ACTION_TYPE
pltr dependency query-type ONTOLOGY_RID QUERY_TYPE
pltr dependency resource RESOURCE_RID
```

`resource` requires a Compass-resolvable RID. Dataset and third-party-application
resources receive specialized analysis. There are no direct `function`,
`schedule`, or `workshop-variable` targets. A Workshop resource can only be
addressed by a resolvable Compass RID, and its internal wiring remains a gap.

## Shared controls

```text
--profile PROFILE
--branch BRANCH
--change TEXT
--change-type rename|type-change|optional-to-required|required-to-optional|remove-delete|action-input-change|query-output-change
--compare-artifact PATH
--output-mode graph|agent|ci
--direction both|upstream|downstream|adjacent
--depth N                       default 2, hard ceiling 10
--max-nodes N                   default 150, hard ceiling 1000
--max-requests N                default 200, hard ceiling 1000
--max-pages N                   default 100, hard ceiling 500
--max-items N                   default 10000, hard ceiling 100000
--time-budget-seconds SECONDS   default 60, hard ceiling 600
--format table|json|csv
--output PATH
--graph-output PATH
--full
```

`--branch` is the requested read context. Each SDK operation independently
records whether branch and preview were `explicit`, `server-default`, or
`not-applicable`, including the exact values. Provenance also records the SDK
namespace/method, capability IDs, installed invocation SDK version, timestamps,
known limitations, and request timeout. A branchless call never inherits the
requested branch in its provenance.

`--change-type` is additive to `--change`. An explicit enum controls
change-aware classification and scoring; free text remains human context.
When omitted, change type may be inferred and is labeled as such.

## Output and artifact contract

Every success writes a mandatory complete JSON artifact atomically with mode
`0600`. `--graph-output` selects its path; otherwise it is written to:

```text
${XDG_STATE_HOME:-~/.local/state}/pltr/dependency/<analysis-id>.json
```

Artifact retention is operator-managed. In `graph` and `agent` modes,
`--output` independently controls the rendered result; `ci` emits its one-line
gate payload to stdout. The default compact table shows the target/read
context, assessment, top root-relative path and evidence locator, SDK operation,
coverage-gap reasons, budget use, absolute artifact path, analysis ID, and
SHA-256 digest. `--full` expands only the table. JSON retains the complete
result. CSV uses explicit row kinds: `node`, `edge`, `path`, `coverage`, `gap`,
`error`, `evidence`, and `operation-provenance`.

`--output-mode graph` returns the complete result. `agent` returns the compact
machine contract with status, ranked impacts, independent blast-radius and
release-risk scores, action/query contracts, coverage completeness,
`must_verify_before_merge`, `should_verify_before_deploy`, and an artifact
reference. `ci` returns the minimal gate payload and exits `0` when clean, `2`
when verification is required, and `1` on fatal failure.

`--compare-artifact` validates a retained artifact before discovery and reports
edge additions, removals, coverage changes, newly introduced impacts, budget
comparability, and possible truncation. In CI mode, malformed, oversized,
non-regular, or schema-incompatible comparison artifacts fail closed.

```bash
# Pre-change baseline for agent reasoning
pltr dependency property ri.ontology.main.ontology.example Employee email \
  --branch dev \
  --change "change email from string to struct" \
  --change-type type-change \
  --direction downstream \
  --output-mode agent \
  --graph-output ./employee-email-before.json

# Post-change comparison for merge gating
pltr dependency property ri.ontology.main.ontology.example Employee email \
  --branch dev \
  --change "change email from string to struct" \
  --change-type type-change \
  --direction downstream \
  --compare-artifact ./employee-email-before.json \
  --output-mode ci \
  --graph-output ./employee-email-after.json
```

## Agent assessment contract

Use `workflows/change-impact-assessment.md` for the full operating sequence.
The compact agent result must be interpreted from `status` through verification,
coverage, contracts, and artifact reference. A `needs-verification` status is a
merge gate. Coverage gaps preserve uncertainty and must never be summarized as
“no impact.”

## Reading paths and coverage

Intrinsic edge orientation is stable. Dependency-flow edges become upstream or
downstream relative to the selected root. Adjacent-structural edges, such as
containment, declared link navigation, or project scope, remain adjacent from
either root. Coverage outcomes are `covered`, `covered-empty`, `partial`,
`inaccessible`, `unsupported`, `unresolved`, and `budget-exhausted`. Any outcome
other than covered/covered-empty is visible as a gap; do not interpret it as
verified absence.

The declared target-kind matrix uses `D` (direct evidence), `I` (one cached
reverse index per context), `C` (conditional evidence), `G` (mandatory gap), and
`N` (not structurally applicable). `D/G` reports observable fields and gaps the
known omitted remainder. Applicable conditional records cannot disappear when a
collector is skipped.

Dataset reverse schedule discovery has a documented possible one-hour lag.
Returned schedule RIDs are verified, but even a successful empty reverse-index
read remains partial with `schedule-index-may-be-stale`. Schedule detail/action,
recursive trigger, scope, affected resources, runs, submitted build, build jobs,
and each job's typed outputs are enforced separately. Configured targets/inputs
come only from `Schedule.action.target`; `Build` has no response target field.

The command does not claim visibility into dynamically resolved upstream
lineage, API-omitted output kinds, application internals, Workshop internals, or
standalone Function reverse wiring. These are explicit coverage gaps.

Fatal failures exit 1 with stable classes: `authentication`,
`permission-denied`, `not-found`, `branch-not-found`, `rate-limited`, `timeout`,
`connection`, `invalid-request`, `unsupported`, `invalid-response`,
`budget-exhausted`, `artifact-write-failed`, `internal`, or `unknown`. Partial
analysis with nonfatal gaps exits 0 and retains its artifact.
