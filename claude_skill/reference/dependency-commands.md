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

## Output and artifact contract

Every success writes a mandatory complete JSON artifact atomically with mode
`0600`. `--graph-output` selects its path; otherwise it is written to:

```text
${XDG_STATE_HOME:-~/.local/state}/pltr/dependency/<analysis-id>.json
```

Artifact retention is operator-managed. `--output` is independent and controls
only the rendered result. The default compact table shows the target/read
context, assessment, top root-relative path and evidence locator, SDK operation,
coverage-gap reasons, budget use, absolute artifact path, analysis ID, and
SHA-256 digest. `--full` expands only the table. JSON retains the complete
result. CSV uses explicit row kinds: `node`, `edge`, `path`, `coverage`, `gap`,
`error`, `evidence`, and `operation-provenance`.

```bash
pltr dependency property ri.ontology.main.ontology.example Employee email \
  --branch dev \
  --change "change email from string to struct" \
  --direction downstream \
  --graph-output ./employee-email-dependencies.json
```

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
