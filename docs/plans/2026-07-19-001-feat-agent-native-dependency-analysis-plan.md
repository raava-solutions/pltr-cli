---
date: 2026-07-19
status: active
origin: docs/plans/2026-07-17-001-feat-foundry-dependency-analysis-plan.md
predecessor: docs/plans/2026-07-17-001-feat-foundry-dependency-analysis-plan.md
topic: agent-native-dependency-analysis
target_repo: pltr-cli
---

# feat: Agent-Native Dependency Analysis Enhancement

## Summary

The predecessor plan (`docs/plans/2026-07-17-001-feat-foundry-dependency-analysis-plan.md`,
implemented in `src/pltr/services/dependency.py`, `src/pltr/commands/dependency.py`,
`src/pltr/utils/dependency_artifacts.py`, and `src/pltr/utils/formatting.py`) shipped a
read-only `pltr dependency` command group that discovers a bounded, evidence-backed
Foundry dependency graph and renders it for a human reading a table or a JSON dump.

This plan is a **machine-first enhancement** of that same graph, not a new capability.
It re-derives a compact `agent` result block — deterministically, from data the BFS in
`DependencyGraphService.analyze()` (`src/pltr/services/dependency.py:550`) already
collected — with zero new Foundry SDK reads. The audience for the `agent` block is an
autonomous agent or a CI pipeline deciding whether a proposed change is safe to merge,
not a human skimming a table. Concretely, machine consumption is prioritized over human
readability in every design choice below:

- A stable, versioned JSON schema (`agent.schema_version`) an agent can parse without
  re-deriving semantics from prose.
- Ranked, deduplicated impact structures instead of a flat path list a human would
  scroll.
- A minimum verification set expressed as structured data (three disjoint buckets),
  not a paragraph telling a human what to go check.
- CI-compatible output and exit codes so a pipeline can gate on the result without
  parsing table text.
- Agent-oriented summary fields (`agent.summary`, `agent.status`) that exist
  specifically for a model to read in one shot.

Human-readable table/CSV rendering remains available and gets exactly two additive
summary lines (`--output-mode graph`, the unchanged default) — it is explicitly
secondary to the `agent` block for this feature.

While assembling the `agent` block, this plan also fixes a real correctness bug already
present in the predecessor implementation: `DependencyGraphService._rank_paths`
(`src/pltr/services/dependency.py:3716`) computes a four-level internal confidence scale
(`confidence_penalty` at `src/pltr/services/dependency.py:3740-3745`: verified / partial
/ unresolved / unsupported) but then collapses it to a binary `coverage_confidence`
field (`"verified" if coverage_score == 0 else "partial"` at
`src/pltr/services/dependency.py:3810-3812`), silently reporting `unresolved` and
`unsupported` paths as merely `"partial"`. That fix is AU1 and is a prerequisite for
every downstream unit in this plan that consumes `coverage_confidence`.

This plan was reviewed by an independent adversarial critique pass mid-authorship (see
`## Risks and Mitigations` and `## RALPLAN-DR Summary`); every CRITICAL/HIGH finding from
that pass was verified against the actual source and test files before being folded in,
and the resulting corrections are reflected directly in the acceptance criteria and
implementation steps below, not bolted on as an appendix.

---

## Requirements Summary

Restated from the enhancement brief, grouped by what they change about the *shape* of
the output rather than the discovery mechanism (discovery is unchanged from the
predecessor plan):

1. **Ranked blast-radius groups** — partition ranked impacts into four ordered buckets:
   critical paths, structural dependents, indirect operational effects, and
   unknown/manual verification.
2. **Semantic dedupe of paths** — collapse readable paths that reach the same related
   node via the same terminal relation and direction into one impact record, while
   preserving every member path's identity and evidence for audit.
3. **Explicit impact categories** — classify every impact as one of `contract-break`,
   `schema-break`, `semantic-break`, `runtime-break`, `workflow-break`,
   `governance-risk`, or `unknown`.
4. **Change-type awareness** — an explicit `--change-type` enum (rename, type change,
   optional→required, required→optional, remove/delete, action input change, query
   output change) additive to the existing free-text `--change`, feeding impact
   categorization and release-risk scoring.
5. **Minimum verification set** — three disjoint, precedence-ordered buckets: must
   verify before merge, should verify before deploy, unsupported/manual surfaces.
6. **Separate blast-radius vs. release-risk scores** — two independent, deterministic,
   0–100, versioned-weight, non-ML scores.
7. **Diff-oriented support** — `--compare-artifact` compares the current graph against a
   previously written artifact: added/removed/changed edges and newly introduced
   impacts.
8. **First-class action/query contract grouping** — for actions: inputs,
   writes/deletes, affected fields, validation risks, runtime consumers; for queries:
   inputs, outputs, input producers, likely downstream consumers, unresolved consumers.
9. **Selective evidence surfacing** — each impact carries relation, confidence, an
   evidence locator, and a why-it-matters string; the full graph remains available
   under `--output-mode graph`.
10. **Agent summaries** — a concise natural-language `summary` plus fully structured,
    machine-parseable fields alongside it.
11. **Severity/confidence model** — direct/transitive/unknown severity plus the fixed
    verified/partial/unsupported coverage-confidence model (AU1).
12. **Output modes for consumers** — `agent` (primary target), `ci` (gate/exit-code
    only), `graph` (current behavior, unchanged default, two additive lines).

---

## Acceptance Criteria

Numbered, testable against the file paths in `## Implementation Steps`.

1. `DependencyGraphService._rank_paths` maps the existing four-value coverage scale to
   exactly three externally reported values — `verified` (score 0), `partial` (scores 1
   and 2, i.e. `partial` and `unresolved`), `unsupported` (score 3) — and
   `tests/test_services/test_dependency.py` gains a case exercising an `unresolved`-
   coverage edge and an `unsupported`-coverage edge through `_rank_paths`, asserting
   `coverage_confidence == "partial"` and `"unsupported"` respectively, without
   regressing the existing assertions at `tests/test_services/test_dependency.py:3125`
   and `:3127`.
2. `analyze()` (`src/pltr/services/dependency.py:550`) returns a new deduplicated,
   ranked `impacts` list where two paths reaching the same `related_node_id` via the
   same terminal `relation_kind` and the same `direction_class` collapse into one
   record with `member_path_ids` containing both source path ids and
   `representative_path_id` set to the lowest-ranked (per the existing `_rank_paths`
   sort key) member; two paths reaching the same node via the same relation but
   opposite `direction_class` remain in separate records.
3. Every impact record carries a closed-enum `impact_category` resolved from a
   `(change_type, relation_kind, direction_class)` lookup that falls back to a
   `relation_kind`-only base table when no `change_type` is supplied; a completeness
   test asserts every entry in `RELATION_KINDS` (`src/pltr/services/dependency.py:402`)
   has a base category and every `direction_class` value for `adjacent-structural`
   relation kinds is always `"adjacent"` (never `"upstream"`/`"downstream"`).
4. `--change-type` is a closed Typer enum (`rename`, `type-change`,
   `optional-to-required`, `required-to-optional`, `remove-delete`,
   `action-input-change`, `query-output-change`) accepted additively alongside the
   existing `--change` on all six subcommands in `src/pltr/commands/dependency.py`;
   omitting it leaves current `--change`-only behavior unchanged, verified by a
   regression test that reruns an existing `--change`-only test case unmodified.
5. `agent.verification` contains exactly three keys —
   `must_verify_before_merge`, `should_verify_before_deploy`,
   `unsupported_manual_surfaces` — and a test asserts every impact/gap subject appears
   in exactly one bucket (disjointness) using the fixed precedence
   must > should > unsupported.
6. A dedicated invariant test proves: whenever `context.budget` reports exhaustion on
   any dimension, or a `CoverageGap` with `coverage` in `{"unresolved", "unsupported"}`
   touches a node in the `critical_paths` or `structural_dependents` blast-radius
   group, `must_verify_before_merge` is non-empty and contains at least one entry with
   `reason` set to `"budget-truncation"` or `"coverage-gap"` respectively — this must
   hold even when zero impact-derived entries exist, closing the CI false-green gap.
7. `agent.blast_radius.score` and `agent.release_risk.score` are each independently
   computed 0–100 integers from versioned weight tables (`weight_table_version` field
   on each), `blast_radius.score` is unaffected by `--change`/`--change-type` (same
   graph, same score regardless of change input), and `release_risk.score` is `null`
   when no `--change` or `--change-type` was supplied and non-null otherwise, tagged
   with `change_type_source` in `{"explicit", "inferred", "absent"}`.
8. Both scores carry a `budget_fingerprint` string that is identical for two invocations
   run with identical `DiscoveryBudget` values and differs when any budget dimension
   (`max_requests`, `max_pages`, `max_items`, `max_nodes`, `max_depth`,
   `time_budget_seconds`) differs.
9. For an `action-type` target or an action-type related node, `agent.action_query_
   contracts.actions` is populated exclusively from `context.caches[("action-metadata",
   ...)]` (already populated by `resolve_action_type` / `_prepare_frontier_target` at
   `src/pltr/services/dependency.py:507-508` and `639-646`) with zero additional mocked
   SDK calls in the corresponding test beyond what the existing action-metadata tests
   already mock.
10. For a `query-type` target or a query-type related node, `agent.action_query_
    contracts.queries` is populated exclusively from `context.caches[("query-metadata",
    ...)]` with zero additional mocked SDK calls, mirroring acceptance criterion 9.
11. `--compare-artifact PATH` is accepted on all six subcommands; `agent.diff` is `null`
    when the flag is omitted and populated when supplied, containing `added_edges` and
    `removed_edges` as sets of stable `edge_id` values (never evidence ids), and
    `changed_edges` as coverage-transition records (`edge_id`, `from_coverage`,
    `to_coverage`) for edges present in both graphs.
12. A test proves an edge absent from the current run's graph purely because
    `context.budget` was exhausted before that edge's subject was reached is reported
    in `removed_edges` with `possibly_budget_truncated: true`, distinguishing it from an
    edge absent because the underlying Foundry relationship was actually deleted
    (`possibly_budget_truncated: false`).
13. `--output-mode` accepts exactly `agent`, `ci`, `graph`; the default remains `graph`
    on all six subcommands, verified by a regression test asserting an existing
    `graph`-mode (implicit, pre-change) table/JSON/CSV test case is byte-for-byte
    unchanged except for the two additive table lines and the new `agent` JSON/CSV
    keys/columns.
14. `--output-mode ci` sets the process exit code to `0` when `agent.status ==
    "clean"`, to `2` when `agent.status == "needs-verification"`, and never overlaps
    exit code `1`, which remains reserved for the existing fatal/tool-failure path
    (`ProfileNotFoundError`, `MissingCredentialsError`, `DependencyFatalError`,
    `ArtifactWriteError`, unknown exception) exercised today by
    `tests/test_commands/test_dependency.py:485`, `:498`, and `:514` — those three
    assertions must still pass unmodified.
15. `docs/user-guide/commands.md` documents `--change-type`, `--output-mode`, and
    `--compare-artifact` in the "Dependency Analysis Commands" section
    (`docs/user-guide/commands.md:28-50`) alongside the existing flag list.
16. `serialize_dependency_result` / `write_dependency_artifact`
    (`src/pltr/utils/dependency_artifacts.py:49`, `:76`) round-trip the new top-level
    `agent` key without modification to their existing dataclass-serialization logic,
    verified by extending `tests/test_utils/test_dependency_artifacts.py`.

---

## Implementation Steps

### AU1. Fix the 3-state coverage-confidence bug (prerequisite for AU2–AU7)

**Files:** `src/pltr/services/dependency.py` (`_rank_paths`, lines 3716–3827, mapping at
3810–3812), `tests/test_services/test_dependency.py` (existing coverage at lines
3093–3127).

Replace the binary `"verified" if coverage_score == 0 else "partial"` expression with an
explicit three-way mapping over the existing `confidence_penalty` scale
(`src/pltr/services/dependency.py:3740-3745`):

| `coverage_score` | source coverage value | reported `coverage_confidence` |
|---|---|---|
| 0 | `verified` | `verified` |
| 1 | `partial` | `partial` |
| 2 | `unresolved` | `partial` |
| 3 | `unsupported` | `unsupported` |

`unresolved` folds into `partial` (not a fourth externally reported state) because both
represent "an attempted read did not fully resolve" as opposed to `unsupported`, which
means the surface is structurally unreachable by the SDK — this matches the requirement
brief's target model of exactly three reported states. This is a **value-domain change**
to an existing field, not a purely additive change: the existing test assertions at
`tests/test_services/test_dependency.py:3125` and `:3127` only ever exercise
`verified`/`partial` source coverage, so they remain unchanged, but new test cases must
exercise `unresolved` and `unsupported` source coverage through `_rank_paths` for the
fix to be provably correct (Acceptance Criterion 1).

### AU2. Semantic dedupe of ranked paths

**Files:** `src/pltr/services/dependency.py` (new function, called from `analyze()` at
line 561 immediately after `ranked = self._rank_paths(context, paths, change)`).

Add `_dedupe_ranked_impacts(context, ranked)`. Group key:
`(related_node_id, terminal_edge.relation_kind, direction_class)`, where
`direction_class` reuses `_overall_direction` (`src/pltr/services/dependency.py:3704`)
already computed per path (adjacent-structural relations always resolve to `"adjacent"`
per `_traversal_direction`, `src/pltr/services/dependency.py:3697-3701`). Because
`ranked` is already sorted ascending by `(hop_count, change_relevance, coverage_score,
severity, path["id"])`, the first member encountered for a given key in iteration order
is the representative — no second sort needed. Each output record carries:
`representative_path_id`, `member_path_ids` (all path ids sharing the key),
`representative_evidence_ids` (only the representative path's evidence, matching what a
human/agent would actually see cited), and `all_member_evidence_ids` (the union across
every member, kept as a separate field so a consumer never conflates the headline
evidence with lower-confidence corroborating evidence from a 3-hop member of the same
group). This directly implements the requirement's "collapse equivalent readable paths
while preserving all evidence locators" without merging heterogeneous-confidence paths
into one indistinguishable blob.

### AU3. Explicit impact categories with change-type and direction awareness

**Files:** `src/pltr/services/dependency.py` (new module-level tables + function),
`src/pltr/commands/dependency.py` (new `--change-type` option).

Add a closed base table keyed by `relation_kind` (all 15 entries of `RELATION_KINDS`,
`src/pltr/services/dependency.py:402-418`) mapping to one of `contract-break`,
`schema-break`, `semantic-break`, `runtime-break`, `workflow-break`, `governance-risk`.
Add a change-type override table keyed by the **triple** `(change_type, relation_kind,
direction_class)` — not by `change_type` alone — so a change type only recategorizes the
specific relation/direction combinations it actually affects; every other combination
falls back to the base table. `direction_class` is `"adjacent"` for all five
`adjacent-structural` relation kinds, so those base categories are never split by
upstream/downstream and downstream-presuming categories (e.g. `contract-break`) are
never assigned to an `"adjacent"` or `"upstream"` impact by the base table alone.

Add the `--change-type` Typer option (`typer.Option(None, "--change-type",
help="rename, type-change, optional-to-required, required-to-optional, remove-delete, "
"action-input-change, or query-output-change")`) to `_validate_options` and all six
command functions in `src/pltr/commands/dependency.py`, additive to the existing
free-text `--change` (`src/pltr/commands/dependency.py:247`). When `--change-type` is
supplied it is authoritative for categorization; when only `--change` free text is
supplied, the category resolution records `change_type_source: "inferred"` using the
existing term-matching logic in `_rank_paths` (`semantic_relations`,
`src/pltr/services/dependency.py:3728-3739`) as a heuristic signal, never silently
treated as equivalent to an explicit enum value.

### AU4. Ranked blast-radius groups, minimum verification set, dual scores

**Files:** `src/pltr/services/dependency.py` (new functions, called from `analyze()`).

Partition the AU2 deduped impact list into four ordered, mutually exclusive groups
(first-matching rule wins, evaluated in this order):

1. `critical_paths` — `direction_class != "adjacent"`, `hop_count == 1`,
   `coverage_confidence == "verified"`, `impact_category` in
   `{contract-break, runtime-break}`.
2. `structural_dependents` — `direction_class == "adjacent"`, or
   (`direction_class != "adjacent"` and `hop_count > 1` and `coverage_confidence ==
   "verified"` and `impact_category` in `{schema-break, semantic-break}`).
3. `indirect_operational_effects` — `hop_count > 1` and `impact_category` in
   `{workflow-break, governance-risk}`, or `coverage_confidence == "partial"`.
4. `unknown_manual_verification` — `coverage_confidence == "unsupported"`, or
   `impact_category == "unknown"`.

Add `severity` per impact — `direct` (`hop_count == 1`), `transitive` (`hop_count > 1`),
or `unknown` (path could not establish a hop count, e.g. an adjacent-only record) —
distinct from `coverage_confidence` (AU1's verified/partial/unsupported), per the
requirement's explicit two-axis severity/confidence model.

Derive the minimum verification set from the **same** group/gap classification used
above — not a second, independently written pass — to avoid the "two truths" failure
mode where this new set and the existing `change_assessment.verification_needed`
(`_assess_change`, `src/pltr/services/dependency.py:3829-3873`) could silently diverge.
Concretely, factor the gap/impact classification into one shared internal helper that
both `_assess_change` (unchanged, still emitting `change_assessment` for existing
callers) and the new verification-set builder call, so `agent.verification`'s three
buckets and `change_assessment.verification_needed`/`uncertainty` are always structurally
consistent views over the same underlying classification, never two hand-maintained
lists. Buckets, in fixed precedence (`must` > `should` > `unsupported`, each subject
appears in exactly one bucket):

- `must_verify_before_merge` — every `critical_paths` member, every
  `unsupported`-coverage impact inside `structural_dependents`, **and** a forced entry
  (tagged `reason: "budget-truncation"` or `reason: "coverage-gap"`) whenever
  `context.budget` reports exhaustion or an `unresolved`/`unsupported` `CoverageGap`
  touches `critical_paths` or `structural_dependents` — this is a hard invariant
  (Acceptance Criterion 6), not a best-effort heuristic, specifically to prevent a
  budget-truncated or gap-riddled analysis from silently reporting an empty must-verify
  set and passing CI clean.
- `should_verify_before_deploy` — remaining `structural_dependents` and
  `indirect_operational_effects` members not already placed in `must`.
- `unsupported_manual_surfaces` — `unknown_manual_verification` members and any
  `CoverageGap` whose `reason_code` indicates a structurally unsupported surface (e.g.
  `unsupported-application-internals`, `unsupported-workshop-internals` from
  `MATRIX_GAPS`, `src/pltr/services/dependency.py:422-432`) with no corresponding
  discovered edge at all.

Every `VerificationItem` carries `reason` in `{"impact", "coverage-gap",
"budget-truncation"}` so a consumer can distinguish "we found a real risky
relationship" from "we don't know and are telling you to check manually" — forced
entries must never be presented as indistinguishable from genuine discovered impacts.

Compute two independent, deterministic, non-ML 0–100 scores, each with a distinct
semantic role stated explicitly (not left implicit):

- `blast_radius_score` — the structural reach of the graph: a weighted function of the
  four group population counts (`blast_radius_weights_v1`), **change-type-agnostic** —
  identical for the same target/graph regardless of `--change`/`--change-type`.
- `release_risk_score` — `blast_radius_score` modulated by a change-type severity
  multiplier (`release_risk_weights_v1`); `null` when no change input was supplied.
  Tagged with `change_type_source` (`"explicit"` | `"inferred"` | `"absent"`) so a
  consumer can discount a score whose change-type contribution was only heuristically
  inferred from free text rather than an explicit `--change-type` enum value.

Both scores carry `weight_table_version` and a `budget_fingerprint` (a stable hash of
the effective `DiscoveryBudget` values) so an agent or CI job can detect when two scores
from different invocations were computed under different discovery bounds and are not
directly comparable — bucket counts remain the primary, always-comparable agent-facing
signal; the scores are secondary/advisory.

### AU5. Action/query contract projection

**Files:** `src/pltr/services/dependency.py` (new function, reads existing
`context.caches`).

Add `_project_action_query_contracts(context, ranked_impacts)`, reading exclusively from
the action/query metadata caches already populated during discovery:
`context.caches[("action-metadata", ontology_rid, branch, action_type)]`
(`src/pltr/services/dependency.py:507-508`, `639-646`) and
`context.caches[("query-metadata", ontology_rid, branch, query_type)]`
(`src/pltr/services/dependency.py:533-534`, `647-655`). Zero new SDK operations.

For each action-type node reached by the analysis: `inputs` (from
`ActionTypeFullMetadata.action_type.parameters`), `writes_deletes` (from
`full_logic_rules`, reusing the existing rule-type extraction that already derives
`action-affects-object` edges), `affected_fields` (property-level references already
walked for the predecessor's action-metadata collector), `validation_risks` (parameters
whose bound object/property/link also appears elsewhere in `ranked_impacts`, i.e.
parameters bound to entities this same analysis already flagged as impacted),
`runtime_consumers` (nodes reached via `action-uses-function` edges from this node).

For each query-type node: `inputs`/`outputs` (from the query's parameter/output type
closure, reusing the existing SCC/fixed-point walker), `input_producers` (nodes with a
`query-accepts-object` edge into this query), `likely_downstream_consumers` (nodes
reached via `query-returns-object` edges from this query where the reverse index found a
consumer), `unresolved_consumers` (query outputs whose reverse-consumer discovery ended
in a `CoverageGap` on the `query-related-function-metadata` surface — we know the output
shape but cannot enumerate who calls it).

### AU6. Diff-oriented `--compare-artifact` support

**Files:** `src/pltr/commands/dependency.py` (new option + load logic),
`src/pltr/services/dependency.py` (new diff function).

Add `--compare-artifact PATH` (optional `Path`, additive) to all six commands. When
supplied, `_run()` loads and JSON-parses the prior artifact and passes both graphs to a
new `_diff_graphs(baseline, current)` function. Diffing uses **only** `edge_id` — proven
content-stable because `_add_edge` derives it as `_stable_id("edge", source, target,
relation_kind, orientation)` from node-derived, timestamp-free values
(`src/pltr/services/dependency.py:928`; node ids are themselves derived purely from
`kind` + normalized `identifiers`, `src/pltr/services/dependency.py:866-870`) — never
`evidence_id`, which is proven **not** cross-invocation-stable:
`_add_evidence` derives it from `operation_id`
(`src/pltr/services/dependency.py:900-902`), and `operation_id` embeds `invoked_at`, a
wall-clock timestamp, plus `context.read_context.id`
(`src/pltr/services/dependency.py:706-712`), so every independent `analyze()` call
produces entirely fresh evidence and operation-provenance ids even against byte-identical
underlying Foundry state.

`added_edges` = current edge ids not in baseline; `removed_edges` = baseline edge ids not
in current; `changed_edges` = edge ids present in both whose stored `coverage` value
differs (`{edge_id, from_coverage, to_coverage}`) — since `edge_id` already pins
`relation_kind`/`traversal_class`/`intrinsic_orientation` immutably, `coverage` is the
only field that can legitimately "change" for a fixed edge id, and it is compared as a
value, never inferred from evidence-id set differences.

Because a run's discovered edge set depends on its `DiscoveryBudget`, an edge that
disappears purely because the current run hit a depth/request/node/time ceiling before
reaching it must not be reported as if the underlying Foundry relationship were deleted.
`removed_edges` entries are tagged `possibly_budget_truncated: true` when the current
run's budget snapshot or gap ledger shows exhaustion at or before the point that edge's
subject would have been reached, `false` otherwise. The diff payload also carries both
sides' `DiscoveryBudget` snapshots and a `comparable: bool` summary flag.

`newly_introduced_impacts` = the subset of AU2's deduped impact list whose
`representative_path_id` terminates on an edge in `added_edges`.

### AU7. Agent result block, output modes, CI gating

**Files:** `src/pltr/services/dependency.py` (`analyze()`, line 550–578),
`src/pltr/commands/dependency.py` (`--output-mode`, exit codes),
`src/pltr/utils/formatting.py` (`format_dependency_result`, `_format_dependency_table`).

Add `_build_agent_block(context, target, change, change_type, deduped_impacts, groups,
verification, blast_radius, release_risk, contracts, diff)` in
`DependencyGraphService`, called at the end of `analyze()`
(`src/pltr/services/dependency.py:561-577`) and assigned to `result["agent"]` — computed
entirely from `context.nodes` / `context.edges` / `context.coverage_records` /
`context.gaps` / `context.errors` / `context.budget` plus the AU2–AU6 outputs, all
already collected by the existing BFS; zero new SDK operations. This is purely additive
to the existing `result` dict (Option A from `## RALPLAN-DR Summary` /
`## ADR: Additive Agent Block`) — every existing top-level key (`target`,
`read_contexts`, `operation_provenance`, `evidence`, `graph`, `paths`,
`ranked_relationships`, `coverage`, `gaps`, `errors`, `budget`, `summary`,
`change_assessment`, `artifact`) is unchanged.

Add `--output-mode {agent,ci,graph}` (default `graph`) to `_validate_options` and all
six commands. `graph` (default, unchanged): current rendering, plus exactly two
additive lines in the table renderer (`_format_dependency_table`,
`src/pltr/utils/formatting.py:187`) summarizing `agent.verification` bucket counts and
`agent.blast_radius` group counts, and the new `agent` key/columns in JSON/CSV — no
existing key, column, or line removed or renamed. `agent`: `--format table` rendering is
replaced by a compact agent-summary rendering built from `agent.summary` and the
structured buckets (this is the primary target per the requirement brief); `--format
json`/`csv` are unchanged in shape from `graph` mode (machine consumers already get
everything). `ci`: a minimal machine-parseable summary line plus `agent.status`/exit
code only, intended for pipeline gating.

Exit codes in `--output-mode ci`, wired into `_run()`'s success path
(`src/pltr/commands/dependency.py:211-217`) without touching the existing failure path
(`:218-235`, which already returns `1` for auth/`DependencyFatalError`/
`ArtifactWriteError`/unknown exceptions, load-bearing per
`tests/test_commands/test_dependency.py:485`, `:498`, `:514`):

- `0` — `agent.status == "clean"` (`must_verify_before_merge` empty and the AU4
  coverage-completeness invariant did not force an entry).
- `1` — unchanged existing fatal/tool-failure path.
- `2` — `agent.status == "needs-verification"` (`must_verify_before_merge` non-empty,
  for any reason including a forced budget/gap entry).

### AU8. Formatter, docs, and test-suite updates

**Files:** `src/pltr/utils/formatting.py`, `docs/user-guide/commands.md`,
`tests/test_services/test_dependency.py`, `tests/test_commands/test_dependency.py`,
`tests/test_utils/test_dependency_artifacts.py`.

- `_format_dependency_table` (`src/pltr/utils/formatting.py:187`) and
  `_format_dependency_csv` (`:140`): additive rendering only, per AU7.
- `docs/user-guide/commands.md:28-50`: document `--change-type`, `--output-mode`,
  `--compare-artifact`, and the `agent` JSON block alongside the existing flag list.
- `tests/test_services/test_dependency.py`: extend for AU1 (3-state mapping incl.
  `unresolved`/`unsupported` cases), AU2 (dedupe incl. direction-splitting and
  representative-path selection), AU3 (category table incl. `direction_class` and
  override precedence, plus the `RELATION_KINDS` completeness test), AU4 (group
  partitioning, verification-set disjointness/precedence, the forced-non-empty
  invariant, both scores incl. `budget_fingerprint`/`change_type_source`), AU5
  (action/query contract projection with zero additional mocked SDK calls), AU6 (diff
  mode incl. the budget-truncation-vs-real-removal distinction).
- `tests/test_commands/test_dependency.py`: new flags, `--output-mode` rendering across
  `table`/`json`/`csv`, `ci`-mode exit codes `0`/`1`/`2` without disturbing the existing
  `exit_code == 1` assertions at lines 485, 498, 514.
- `tests/test_utils/test_dependency_artifacts.py`: artifact round-trips the new `agent`
  key through `serialize_dependency_result`/`write_dependency_artifact`
  (`src/pltr/utils/dependency_artifacts.py:49`, `:76`) unmodified; document/assert that
  `artifact_identity()` (`:57`) was already non-stable across independent invocations
  before this change (it hashes `evidence`/`operation_provenance`, both timestamp-
  embedded), so adding `agent` introduces no new instability to an already
  per-invocation-unique digest.

---

## Risks and Mitigations

- **AU1 is a value-domain change, not purely additive.** `coverage_confidence` already
  exists and is asserted exactly by `tests/test_services/test_dependency.py:3125`/
  `:3127`. *Mitigation:* the new mapping is the identity function for every value those
  two assertions currently exercise (`verified`→`verified`, `partial`→`partial`); only
  the previously-mislabeled `unresolved`/`unsupported` cases change, and those gain
  dedicated new test coverage (Acceptance Criterion 1) rather than being asserted only
  incidentally.
- **CI exit-code collision.** A naive `ci`-mode design could reuse exit code `1` for a
  new meaning, breaking the existing fatal-error contract asserted at
  `tests/test_commands/test_dependency.py:485`, `:498`, `:514`. *Mitigation:* exit `1`
  keeps its current, unchanged meaning; the new must-verify gate state uses exit `2`,
  which no existing code path emits today.
- **CI false-green on incomplete coverage.** A budget-truncated or heavily-gapped
  analysis could report an empty `must_verify_before_merge` and exit `0`, letting a
  pipeline treat "we didn't finish looking" as "we looked and it's safe." *Mitigation:*
  AU4's coverage-completeness invariant forces a `must_verify_before_merge` entry
  whenever budget exhaustion or an unresolved/unsupported gap touches the critical or
  structural-dependents groups, enforced by a dedicated test (Acceptance Criterion 6),
  and every such forced entry is tagged `reason: "budget-truncation"` /
  `"coverage-gap"` so it is never visually indistinguishable from a genuine discovered
  impact.
- **Change-type override table over-generalizing.** A `change_type`-keyed override
  table (without `relation_kind`/`direction_class`) would recategorize every edge in
  the graph identically regardless of what kind of relationship it actually is, and
  would apply downstream-presuming categories (e.g. `contract-break`) to upstream or
  adjacent-structural relationships where the causal direction is reversed or absent.
  *Mitigation:* the override table is keyed by the triple `(change_type, relation_kind,
  direction_class)`, falls back to the `relation_kind`-only base table, and
  `direction_class` is always `"adjacent"` for the five adjacent-structural relation
  kinds, verified by a completeness test.
- **Dedupe key conflating heterogeneous-confidence paths.** A dedupe key of just
  `(related_node_id, terminal relation_kind)` would silently merge a 1-hop verified
  path with a 3-hop unsupported-coverage path into one group and blindly union their
  evidence, hiding the confidence difference from the consumer. *Mitigation:* the key
  adds `direction_class`, the representative path is chosen deterministically by the
  existing rank ordering (verified/lower-hop paths always sort first), and
  representative evidence is reported separately from the full member-evidence union.
- **Two-truths verification set.** A hand-written `agent.verification` computed
  independently from the existing `_assess_change`/`change_assessment` output could
  silently diverge from it over time. *Mitigation:* both are derived from one shared
  internal classification helper over the same `ranked`/`context.gaps` inputs; only the
  two top-level presentations differ, never the underlying facts.
- **Diff mode reporting spurious changes from evidence-id churn or budget mismatch.**
  Evidence and operation-provenance ids are proven to embed invocation timestamps
  (`src/pltr/services/dependency.py:706-712`, `900-902`) and are therefore never equal
  across two independent runs, even against identical Foundry state; and an edge
  missing from a differently-budgeted run is not necessarily an edge that was actually
  removed from Foundry. *Mitigation:* diffing uses only content-stable `edge_id`s and
  the `coverage` field for `changed_edges` — never evidence ids — and `removed_edges`
  entries are tagged `possibly_budget_truncated` using the existing budget/gap ledger so
  a consumer can tell real removal from incomplete discovery apart.
- **Dual scores presented without a stated semantic distinction, or budget-incomparable
  scores presented as directly comparable.** Two 0–100 numbers with no documented
  difference in what they measure, or compared across differently-budgeted runs without
  a signal, would be misleading rather than useful. *Mitigation:* `blast_radius_score`
  is explicitly documented as change-type-agnostic structural reach;
  `release_risk_score` is explicitly documented as that same reach modulated by
  change-type severity and tagged with `change_type_source` so a heuristically-inferred
  contribution is distinguishable from an explicit one; both carry a
  `budget_fingerprint` so non-comparable runs are detectable rather than silently
  compared. Bucket counts, not the scores, remain the primary agent-facing signal.
- **Adding a top-level `agent` key changes `artifact_identity()`'s digest.**
  `artifact_identity()` (`src/pltr/utils/dependency_artifacts.py:57-67`) hashes the
  entire result except the `artifact` key. *Mitigation:* this digest was already
  non-reusable as a cross-invocation content fingerprint before this change (it
  includes `evidence`/`operation_provenance`, both timestamp-embedded per the diff-mode
  finding above), so adding `agent` introduces no new instability; nothing in this plan
  relies on `analysis_id`/digest equality across runs — AU6's diff mode deliberately
  operates at the `edge_id` level instead, which is genuinely content-stable.
- **Preview/full-metadata drift (inherited from the predecessor plan).** AU5's
  action/query contract projection reads the same preview-flagged full-metadata caches
  the predecessor plan already depends on; any SDK-shape change there is already a
  predecessor-plan risk and is not reintroduced here — AU5 adds no new SDK surface.

---

## Verification Steps

1. `uv run pytest tests/test_services/test_dependency.py -q` — full AU1–AU6 service-layer
   coverage, including the new invariant/completeness tests.
2. `uv run pytest tests/test_commands/test_dependency.py -q` — new flags, output modes,
   and CI exit codes, including a rerun of the existing exit-code-1 assertions
   (lines 485, 498, 514) to prove no regression.
3. `uv run pytest tests/test_utils/test_dependency_artifacts.py -q` — artifact
   round-trip with the new `agent` key.
4. `uv run pytest tests/ -q` — full suite, to catch any cross-module regression from the
   `--output-mode`/`--change-type`/`--compare-artifact` additions touching shared
   formatter/CLI code paths.
5. `uv run ruff check src/pltr/services/dependency.py src/pltr/commands/dependency.py
   src/pltr/utils/formatting.py src/pltr/utils/dependency_artifacts.py` and
   `uv run mypy` per `mypy.ini` — lint/type gate matching existing repository
   conventions (`pyproject.toml` dev dependency group: `ruff`, `mypy`).
6. Manual smoke check: run `pltr dependency object-type <ontology_rid> <object_type>
   --change-type rename --output-mode agent` against a fixture/mock client and confirm
   the rendered summary and the underlying JSON `agent` block are both present and
   internally consistent (bucket counts sum to the impact count; `verification` bucket
   membership is disjoint).
7. Manual smoke check: run the same target twice with `--graph-output` pointing at a
   fixed path, then rerun with `--compare-artifact` against that path and no graph
   change in between, and confirm `agent.diff.added_edges`/`removed_edges` are empty
   while `changed_edges` reflects only genuine coverage-state differences, if any.

---

## Agent-Native Result Schema

Fields only — no implementation. All fields are additive under a new top-level `agent`
key in the existing `analyze()` result dict; every field name below is illustrative of
shape, not a promise of a specific serialization library.

```text
result.agent (object)
  schema_version                     string   # e.g. "dependency-agent-v1"
  generated_at                       string   # ISO-8601 timestamp
  status                             enum     # "clean" | "needs-verification" | "fatal"
  summary                            string   # one-paragraph natural-language summary
  target
    node_id                          string
    kind                             string
    display_name                     string
  change
    text                             string | null   # free-text --change, if supplied
    change_type                      enum | null      # closed --change-type value, if supplied
    change_type_source               enum             # "explicit" | "inferred" | "absent"

  impacts                            array[ImpactRecord]     # deduped, ranked
    ImpactRecord
      impact_id                      string
      related_node_id                string
      related_kind                   string
      related_display_name           string
      relation_kind                  string
      impact_category                enum   # contract-break | schema-break | semantic-break |
                                      #   runtime-break | workflow-break | governance-risk | unknown
      direction_class                enum   # upstream | downstream | adjacent
      severity                       enum   # direct | transitive | unknown
      coverage_confidence            enum   # verified | partial | unsupported
      hop_count                      integer
      dedupe_key                     string
      representative_path_id         string
      member_path_ids                array[string]
      representative_evidence_ids    array[string]
      all_member_evidence_ids        array[string]
      evidence_locator                string | null
      readable_path                  string
      why_it_matters                  string

  blast_radius
    score                           integer  # 0-100, change-type-agnostic
    weight_table_version            string
    budget_fingerprint              string
    groups
      critical_paths                array[string]   # impact_id references
      structural_dependents         array[string]
      indirect_operational_effects  array[string]
      unknown_manual_verification   array[string]

  release_risk
    score                           integer | null   # 0-100, null when no change supplied
    weight_table_version            string
    budget_fingerprint              string
    change_type_source              enum   # explicit | inferred | absent

  verification
    must_verify_before_merge        array[VerificationItem]
    should_verify_before_deploy     array[VerificationItem]
    unsupported_manual_surfaces     array[VerificationItem]
    VerificationItem
      subject_node_id                string | null
      subject_display_name           string | null
      related_impact_ids             array[string]
      reason                         enum   # impact | coverage-gap | budget-truncation
      message                        string

  coverage_completeness
    complete                        boolean
    budget_exhausted                boolean
    exhausted_dimensions            array[string]
    truncated_surfaces              array[string]

  action_query_contracts
    actions                         array[ActionContract]
      ActionContract
        action_type                  string
        inputs                       array[object]
        writes_deletes                array[object]
        affected_fields               array[string]
        validation_risks              array[string]
        runtime_consumers             array[string]
    queries                          array[QueryContract]
      QueryContract
        query_type                    string
        inputs                        array[object]
        outputs                       array[object]
        input_producers                array[string]
        likely_downstream_consumers    array[string]
        unresolved_consumers           array[string]

  diff                              object | null   # only when --compare-artifact supplied
    compared_against                string           # baseline artifact id
    comparable                      boolean
    baseline_budget                 object
    current_budget                  object
    added_edges                     array[string]    # edge_id
    removed_edges                   array[RemovedEdge]
      RemovedEdge
        edge_id                      string
        possibly_budget_truncated    boolean
    changed_edges                   array[ChangedEdge]
      ChangedEdge
        edge_id                      string
        from_coverage                 string
        to_coverage                   string
    newly_introduced_impacts        array[string]     # impact_id

  artifact_reference
    artifact_id                     string
    path                            string
    sha256                          string
```

---

## Non-Goals

- No new Foundry SDK read is added anywhere in this plan; every `agent` field is derived
  from data the predecessor plan's BFS already collects into `context`.
- No mutation, remediation, or approval workflow — this remains strictly read-only
  assessment, matching the predecessor plan's "Assessment, not action" decision.
- No change to the six existing target commands (`object-type`, `property`,
  `link-type`, `action-type`, `query-type`, `resource`) or the resolvers behind them;
  this plan only changes what `analyze()` returns and how it is rendered/exited.
- No machine-learning, statistical, or probabilistic scoring; `blast_radius_score` and
  `release_risk_score` are deterministic, versioned-weight-table functions of already-
  discovered graph structure, never trained or fitted.
- No retention/pruning system for `--compare-artifact` baselines; artifact lifecycle
  management remains operator-managed exactly as the predecessor plan already scoped it
  (`docs/plans/2026-07-17-001-feat-foundry-dependency-analysis-plan.md:700`).
- No change to `--format table|json|csv` semantics beyond the two additive table lines
  and new JSON/CSV keys/columns; `--output-mode graph --format json` remains a superset,
  never a replacement, of the pre-existing JSON shape.
- No reassignment of exit code `1`; its existing fatal/tool-failure meaning is preserved
  exactly.
- No cross-run stability guarantee for `analysis_id`/artifact digest; that property does
  not exist today (timestamp-embedded evidence/operation-provenance ids) and this plan
  does not attempt to introduce it — diffing is deliberately done at the `edge_id`
  level instead, where that guarantee already holds.
- No third scoring axis beyond `blast_radius_score`/`release_risk_score`; bucket counts
  are the primary signal and additional derived scores are out of scope for this plan.

---

## RALPLAN-DR Summary

**Principles**

- Machine consumption is the primary design constraint; human table rendering is a
  secondary, backward-compatible surface.
- Every new field must be derivable from data already collected by the existing BFS —
  no new SDK reads, no new discovery surface.
- A fix to an existing bug (AU1) is a prerequisite, stated and scoped explicitly, not
  silently folded into a "related" feature unit.
- Every design decision that shipped in this plan was checked against the actual source
  and test files before being finalized, including via an independent adversarial
  critique pass mid-authorship; findings that were verified as correct were folded in
  with the corrected (not the literally-proposed) fix where the literal proposal would
  itself have broken an existing contract (see the CI exit-code decision below).

**Top 3 Decision Drivers**

1. **Backward compatibility of the existing `pltr dependency` contract.** Three existing
   commands' test suites assert exact JSON shape, exact CSV columns, exact exit codes
   (`1` for fatal/tool failure), and an exact binary `coverage_confidence` value pair.
   Any design that could not preserve those exactly was rejected.
2. **CI-safety against false negatives.** An agent-native gate that can silently report
   "clean" on an incomplete analysis (budget-exhausted or gap-riddled) is worse than no
   gate at all, because it actively hides risk behind a green signal.
3. **No new discovery cost.** The predecessor plan already spent significant design
   effort bounding SDK reads with a global budget; this enhancement must not reopen that
   by adding new reads for agent-facing convenience.

**Options considered (≥2 viable) and tradeoffs**

- **Option A — Additive `agent` block, computed post-BFS from already-collected
  context.** *(Chosen.)* Zero new reads, fully backward compatible (new top-level key
  only), reuses the existing rank/gap/coverage machinery. Tradeoff: the `agent` block
  duplicates some derivation logic already present in `_assess_change` unless explicitly
  factored to share it (addressed directly in AU4 by using one shared classification
  helper).
- **Option B — Replace the existing graph output shape with the agent-oriented shape.**
  Would produce a cleaner, single-purpose schema with no legacy fields. Tradeoff:
  breaks every existing JSON/CSV consumer and the existing test suite's exact-shape
  assertions; rejected as violating the top decision driver (backward compatibility).
- **Option C — A separate `pltr dependency agent-analyze` command that re-runs
  discovery from scratch and returns only the agent shape.** Would keep the two
  concerns cleanly separated at the CLI surface. Tradeoff: doubles SDK read cost per
  agent invocation (a fresh BFS instead of reusing one already-collected context),
  duplicates budget/target/branch option handling across two command families, and
  produces two graphs for the same target that could disagree if run at different
  times; rejected as violating decision driver 3 and introducing exactly the kind of
  divergence risk decision driver 1 was meant to prevent.

**Tradeoffs accepted with Option A**

- The `agent` block is computed inside `analyze()`, so it is included in the artifact
  digest computed by `artifact_identity()`. This was already a non-stable digest across
  invocations (timestamp-embedded evidence/operation-provenance ids); Option A adds no
  new instability but does mean `agent` cannot be added "for free" after artifact
  identity has already been computed without restructuring `_run()` — accepted, since
  no existing or planned consumer relies on cross-invocation digest equality.
- CI-mode gating needed a new exit code (`2`) rather than the more intuitive `1`
  ("something needs attention"), because `1` is already load-bearing for a different,
  pre-existing meaning (auth/tool failure) that three existing tests assert exactly.
  Reusing `1` for the new meaning — as an initial adversarial-critique proposal
  suggested — was rejected after verifying against
  `tests/test_commands/test_dependency.py:485,498,514` that it would break the existing
  contract; `2` was chosen instead as the smallest change that preserves both meanings
  distinctly.

---

## ADR: Additive Agent Block Over Replacement or a Separate Command

**Status:** Accepted

**Decision:** Implement agent-native dependency analysis as an additive `agent` key on
the existing `analyze()` result, computed post-BFS from already-collected
`context.nodes`/`context.edges`/`context.coverage_records`/`context.gaps` with zero new
SDK operations, rendered via a new `--output-mode {agent,ci,graph}` flag whose default
(`graph`) preserves current behavior exactly except for two additive table lines and new
JSON/CSV keys.

**Drivers:**

- Preserve the predecessor plan's existing contract (exact JSON/CSV shape, exact exit
  codes, exact `coverage_confidence` binary pair) for every caller that does not opt
  into the new surface.
- Avoid doubling Foundry SDK read cost per agent invocation.
- Avoid a second, independently-derived source of truth for verification/impact
  classification that could silently diverge from the existing `change_assessment`.
- Make CI/agent consumption safe against false-green results on incomplete coverage.

**Alternatives considered:** Replace the existing output shape entirely (Option B);
introduce a separate `agent-analyze` command that re-discovers the graph independently
(Option C). Both are detailed with rejection reasons in `## RALPLAN-DR Summary` above.

**Why chosen:** Option A is the only alternative that satisfies all three decision
drivers simultaneously — it costs nothing in additional SDK reads, it cannot regress an
existing consumer because it only adds keys/lines/exit-code branches gated behind new,
opt-in flags, and it shares its verification/classification logic with the existing
`_assess_change` path by construction (AU4) rather than by discipline alone.

**Consequences:**

- `analyze()`'s return type grows a new key; any future change to the `agent` block's
  internal shape must bump `agent.schema_version`, not silently change field meaning
  in place — this repeats, deliberately, the lesson of the AU1 bug this plan fixes.
- The CI/agent output modes introduce exit code `2` as a new, permanent part of the
  CLI's process-exit contract; any future third gating state must not reuse `0`, `1`,
  or `2` without an equivalent backward-compatibility review.
- `artifact_identity()`'s digest remains, and will continue to be, non-reusable as a
  cross-invocation content fingerprint; any future feature that wants that property
  will need its own content-stable identity scheme (as AU6's diff mode already builds
  at the `edge_id` level) rather than relying on `analysis_id`.

**Follow-ups (explicitly out of scope for this plan, tracked for later consideration):**

- Retention/pruning policy for `--compare-artifact` baseline files, inherited as an open
  question from the predecessor plan and not resolved here.
- Whether `blast_radius_score`/`release_risk_score` weight tables should eventually be
  tunable per-deployment rather than fixed in source, once real usage data exists to
  justify it — deliberately deferred to avoid speculative configurability now.
- Whether a third CI gate state distinguishing "must-verify due to genuine impact" from
  "must-verify due to incomplete coverage" (currently both fold into exit code `2`, with
  the distinction only visible in the `reason` field of each `VerificationItem`) is
  worth a fourth exit code once pipelines actually attempt to consume this output.
