---
date: 2026-07-17
topic: foundry-dependency-analysis
---

# Foundry Dependency Analysis Requirements

## Summary

Add an agent-native, read-only dependency-analysis capability to `pltr` that explains the upstream inputs, downstream consumers, and adjacent relationships of an addressable Foundry resource. A caller may also supply an intended change to receive a focused impact assessment built from the same observed graph.

The first release directly addresses ontology object types, properties, link types, action types, ontology query types, and Compass resources by RID (including datasets and applications). Workshop modules or variables and standalone Functions resources are included as dependency surfaces when observable, but are not advertised as direct target kinds until the authenticated SDK exposes a stable identifier and read contract for them. When those or any other promised surfaces cannot be read, the result must say so explicitly.

---

## Problem Frame

Foundry changes can appear local while affecting data, ontology semantics, actions, Workshop variables, applications, and other consumers. Builders and ontology managers currently discover those relationships by hopping across Foundry surfaces, which makes effort estimates unreliable and allows apparently small changes to break an application.

Agents need the same evidence in a token-efficient form. A raw graph dump is not sufficient: it obscures the decision-relevant path and consumes context that an agent needs for planning or review.

---

## Key Decisions

- **One canonical dependency model.** Ontology managers, builders, and autonomous agents use the same observed relationship graph so their answers do not diverge.
- **Layered answer with same-invocation graph retention.** The default response presents prioritized paths and evidence while writing the complete graph from that invocation to a local machine-readable artifact referenced by the compact result.
- **Assessment, not action.** The capability reads and evaluates dependency evidence. It does not mutate Foundry resources, approve changes, or remediate impact.
- **Coverage is evidence-backed and mechanically enforced.** Each target-kind × dependency-surface cell required by the coverage contract records a covered, covered-empty, partial, inaccessible, unsupported, unresolved, or budget-exhausted outcome. Anything other than covered or covered-empty produces a visible coverage gap.
- **Intrinsic relations are stable; query direction is contextual.** Stored relations keep a stable orientation; upstream, downstream, and adjacent are derived for each root-to-node path and never rewrite the stored relation.
- **Dependency flow is distinct from adjacent structure.** Every relation kind is classified as `dependency-flow` or `adjacent-structural`. Only dependency-flow orientation produces upstream/downstream traversal; containment, declared link-side navigation, and peer membership remain adjacent from either root. One semantic relation has one edge identity independent of its evidence, and independently observed evidence IDs merge onto that edge.
- **Recursive query closure is sound across roots.** Reachable query type references are resolved with an SCC/fixed-point closure (or an equivalently sound cross-root strategy), so entering a mutually recursive component through a different parameter or output cannot lose reachable leaves. A reachable SDK `UnsupportedType` is an explicit coverage gap.
- **Dataset reverse-schedule discovery is freshness-limited.** The dataset schedule reverse index is treated as deterministically partial because the pinned SDK documents up to one hour of lag. Returned schedule RIDs remain verified evidence, but an empty or fully paged response alone never proves there are no schedule consumers.
- **Dataset traversal coverage is conditional and per sub-read.** Reverse schedule indexing, schedule detail/action, schedule trigger, affected resources, runs, submitted build detail, build jobs, and typed outputs have separate coverage records. Each returned schedule, submitted-build, or job RID makes its next read applicable and forces that record to end as covered, covered-empty, or a specific gap; the stale reverse-index gap cannot satisfy or mask a later uninvoked collector.
- **Schedule trigger and scope references are observable dependencies.** Resource-bearing schedule triggers are walked recursively through nested `and`/`or` variants, and project-scope RIDs are emitted as adjacent structural relations. A hidden, malformed, or unknown trigger/scope variant produces a field- and variant-specific gap instead of disappearing.
- **Reads are bounded and attributable.** Results identify requested/effective branch context and read provenance. Global request, page, item, node, and elapsed-time budgets prevent ontology-wide reverse scans from becoming unbounded.
- **Existing command contracts remain stable.** Dependency-only paging/read helpers do not change the existing `DatasetService.get_schedules` list-of-dictionaries contract consumed by `pltr dataset schedules list` and its formatter. Every dependency-analysis SDK request receives the remaining-budget-derived timeout.

---

## Actors

- A1. **Ontology manager** evaluates the blast radius of a proposed semantic change before approving it.
- A2. **Foundry builder** inspects a resource while estimating or implementing a change.
- A3. **Autonomous agent** retrieves compact dependency context before planning, reviewing, or acting on a Foundry task.

---

## Requirements

### Dependency discovery

- R1. The capability directly accepts ontology object types, properties, link types, action types, ontology query types, and Compass resource RIDs as analysis targets. A dataset or application is targetable through its Compass RID. A Workshop resource may be targeted only when it has a resolvable Compass RID, in which case unsupported internal Workshop wiring remains an explicit gap. Standalone Functions RIDs and Workshop variable identifiers are not direct target kinds in this release.
- R2. The result identifies direct and transitive upstream dependencies, downstream consumers or effects, and adjacent structural relationships that are observable within the configured bounds.
- R3. Every reported relationship identifies participating resources, intrinsic relation and orientation, relation traversal class (`dependency-flow` or `adjacent-structural`), root-relative direction, complete observed root-to-relationship path, and evidence for each hop. Edge identity is derived only from the intrinsic participants and semantic relation identity; evidence is a merged, sorted set on that edge and cannot split one relation into duplicate edges.
- R4. The result distinguishes verified relationships and verified empty reads from partial, stale, inaccessible, unsupported, unresolved, malformed, or budget-limited coverage.
- R5. Coverage enforcement is driven by a declared target-kind × dependency-surface contract plus conditional per-returned-RID sub-read records. A promised or newly applicable surface cannot disappear merely because a collector returned no edges or was not invoked, and a parent record's gap cannot terminalize a child record.

### Agent-native assessment and retention

- R6. The default response is compact and prioritized for an agent deciding what to inspect next. Each compact relationship includes a readable path and concise evidence, not only a related-resource name.
- R7. Every successful invocation preserves its complete discovered graph, coverage ledger, and provenance as a local machine-readable artifact and returns its reference and integrity digest. Compact output and the artifact share one analysis identifier.
- R8. The graph artifact contains all discovered nodes, edges, paths, coverage outcomes, gaps, errors, and read provenance from that invocation; rendering or top-N selection cannot remove data from it.
- R9. The result supplies a deterministic human-readable assessment usable without manually correlating Foundry surfaces.

### Change-aware analysis

- R10. A caller may supply an intended change alongside any supported target.
- R11. When change intent is supplied, the result ranks relevant discovered paths by likely impact and identifies consumers or follow-up verification that require attention.
- R12. When the intended change cannot be assessed with available evidence, the result states the uncertainty and includes every intersecting coverage gap; a non-empty ranked result does not suppress uncertainty.

### Read context, limits, and errors

- R13. The caller may request a Foundry branch. The result records the requested branch separately from every operation's branch argument and, per operation, serializes the exact branch passed, a `server-default` marker when no branch was passed, or `not-applicable` when the endpoint is branchless. The capability does not claim to know an undisclosed server default, and `unsupported` is a coverage status rather than an argument-state value.
- R14. Each evidence record references immutable, artifact-serialized operation provenance containing SDK namespace and method, stable CAP assumption IDs, invocation SDK version, invocation/read timestamps, exact preview mode/value (`explicit`, `server-default`, or `not-applicable`), exact branch argument state/value, and request timeout. Evidence also identifies the relevant response field or discriminator; no SDK-dependent operation may be added without a CAP entry backed by pinned local source.
- R15. Ontology-wide reverse action/query metadata is fetched and indexed at most once per ontology × branch within an invocation, then reused by all frontier nodes.
- R16. One global invocation budget bounds requests, pages, items, graph nodes, and elapsed time. Exhaustion stops further reads deterministically and creates surface-specific `budget-exhausted` gaps for required work left incomplete.
- R17. Failures use deterministic classes at target and sub-read boundaries, including authentication, not-found, branch-not-found, permission-denied, rate-limited, timeout, unsupported, invalid-response, budget-exhausted, artifact-write-failed, and unknown. Target-resolution or artifact-retention failure fails the command; a non-target sub-read is isolated as a coverage gap when safe to continue.
- R18. Query parameter/output traversal computes a complete reachable closure across mutually recursive `typeReferences` before reusing results across roots. A reachable missing reference, unknown variant, or SDK `UnsupportedType` produces an explicit unresolved or unsupported gap; unreachable definitions do not.
- R19. Every dataset analysis based on `Dataset.get_schedules` records the pinned endpoint's documented possible one-hour lag and emits a deterministic target-scoped `partial` gap such as `schedule-index-may-be-stale` on the schedule-reverse-index record, including after a successful fully paged empty response. Only an independently verified freshness-complete source may remove that gap. That partial status applies only to reverse discovery and cannot complete or explain a schedule/build/job descendant record.
- R20. The dependency implementation preserves the existing `DatasetService.get_schedules` command/formatter return contract by using a separate page-oriented schedule-RID read or by migrating every affected callsite, formatter, and test together. Every SDK read made by dependency analysis is passed `request_timeout=min(configured_request_timeout, remaining_time)`.
- R21. Dataset traversal maintains distinct conditional coverage records for schedule reverse index, schedule detail/action, schedule trigger, affected resources, schedule runs, submitted build detail, build jobs, and typed outputs. A returned schedule RID creates the four schedule-level records; each submitted `build_rid` creates a submitted-build-detail record; each successfully returned build creates a build-jobs record; and each returned job creates a typed-outputs record. Every created record must finish `covered`, `covered-empty`, or with a specific gap. A partial reverse-index record never completes any descendant record, and an uninvoked applicable collector is `collector-did-not-report`.
- R22. Schedule detail traversal recursively visits every nested `and`/`or` trigger. Dataset-updated, job-succeeded, and new-logic triggers emit dataset references; table-updated emits a table reference; schedule-succeeded emits a schedule reference; media-set-updated emits a media-set reference. Manual/time triggers prove no resource reference for that variant. Project scope emits adjacent project relations. A missing trigger whose model documentation permits permission-based omission, an unknown trigger/scope discriminator, or a malformed known variant produces a locator- and variant-specific gap.

---

## Key Flows

- F1. Resource dependency query
  - **Trigger:** A1, A2, or A3 supplies an addressable Foundry resource and optional branch/read context.
  - **Steps:** The capability resolves reachable relationships within global budgets, returns a compact prioritized assessment, and writes the complete discovered graph from that invocation to a referenced local artifact.
  - **Outcome:** The caller can identify what feeds, depends on, or is coupled to the target and can distinguish unsupported surfaces from verified absence without hopping across Foundry surfaces.

- F2. Proposed-change impact assessment
  - **Trigger:** A1, A2, or A3 supplies a target resource and intended change.
  - **Steps:** The capability evaluates the change against the discovered dependency graph and prioritizes likely affected consumers and verification needs without changing discovery semantics.
  - **Outcome:** The caller knows the likely blast radius and unresolved uncertainty before a change is planned or made.

---

## Acceptance Examples

- AE1. Given an ontology property, the result identifies every discovered relationship required by the coverage contract and emits an explicit per-surface gap where a relationship surface cannot be observed.
- AE2. Given an action type or ontology query type, the result uses full action rule/parameter metadata or cycle-safe query type-reference traversal to identify observed ontology and function relationships; application, Workshop, standalone Function, and data surfaces that are unreachable remain explicit gaps.
- AE3. Given a dataset RID and branch, the analysis follows the real schedule-RID → schedule-run → submitted build → build jobs → typed outputs chain within bounds, reports configured targets only from `Schedule.action.target`, gaps dynamically resolved upstream lineage the API does not enumerate, and always reports the schedule reverse index as possibly stale for up to one hour. A successful empty schedule page is partial, never `covered-empty`, without independent freshness evidence. Each returned RID creates the applicable schedule-detail/action, trigger, affected-resource, runs, build-detail, jobs, and typed-output records, so stale reverse-index coverage cannot mask an uninvoked descendant collector.
- AE4. Given a property and intended semantic change, the result prioritizes affected root-relative paths and names follow-up verification required before change.
- AE5. Given a dependency cone too large for one context, the compact result reports truncation, retains every pre-bound item in a same-invocation graph artifact, and marks each uncompleted required surface `budget-exhausted` or `partial`.
- AE6. Given an inaccessible or unsupported surface, the result reports a deterministic coverage gap and does not claim no relationship exists there.
- AE7. Given `A = union[object X, ref B]` and `B = union[object Y, ref A]`, traversal from either A or B terminates and returns both X and Y with the correct parameter/output evidence prefix. Missing reachable reference IDs are unresolved, reachable `UnsupportedType` values are unsupported gaps, and valid back-edges are not dependencies.
- AE8. Given two frontier nodes in the same ontology and branch, reverse action/query metadata is fetched once and reused; provenance counters never exceed global bounds.
- AE9. Given a compact table result, every listed relationship shows root-relative direction, path, and evidence, and its graph reference resolves to an artifact with the same analysis ID and digest.
- AE10. Given action→object, query→object, and schedule→dataset dependency-flow relations plus link A↔B and container→member structural relations, reciprocal-root analysis reverses upstream/downstream only for dependency flow; structural relations remain adjacent. Two independent observations of the same intrinsic relation produce one edge with both evidence IDs.
- AE11. Given preview full-metadata, explicit-branch ontology/dataset, omitted-branch, and branchless schedule/build/resource reads, the artifact records the exact SDK namespace/method, stable CAP IDs, installed invocation SDK version, preview state/value, branch argument state/value, timestamp, and request timeout for each operation. A registered operation without a valid CAP ID fails the operation-registry completeness test.
- AE12. Given the pre-existing `pltr dataset schedules list` command and a dependency dataset traversal, the former still receives schedule dictionaries accepted by `format_schedules`, while the latter consumes explicit RID pages with page tokens and remaining-budget-derived request timeouts.
- AE13. Given nested `and`/`or` schedule triggers, all dataset/job/new-logic, table, schedule, and media-set RID leaves produce evidence-backed relations with exact trigger field paths; manual/time leaves produce no invented resource edge. An unknown nested trigger variant or permission-hidden trigger produces a specific gap, and project scope produces adjacent project relations.
- AE14. Given a stale-but-successful non-empty schedule reverse index, deliberately leaving the runs, build-jobs, or typed-outputs collector uninvoked fails coverage completion with the exact conditional record and `collector-did-not-report`; the reverse-index `partial` record cannot satisfy it.

---

## Success Criteria

- An agent can determine the discovered dependency footprint of a target resource in one invocation and retrieve deeper paths from that invocation's artifact.
- An ontology manager can use a change-aware result to identify affected consumers and required verification before approval.
- A result never represents incomplete discovery, a documented stale reverse index, an exhausted budget, or an unsupported surface as a complete absence of impact.
- Results identify the read context and provide deterministic evidence, paths, gaps, and error classes suitable for automation.
- The capability makes a cross-surface dependency assessment materially faster than manual navigation across Foundry tools.

---

## Scope Boundaries

### Included

- Read-only discovery and assessment across supported ontology targets and Compass resources, with related data, actions, ontology query types, applications, Workshop, and function surfaces included wherever authenticated APIs make relationships observable.
- Explicit gap behavior for Workshop, standalone Function, application-internal, lineage, reverse-index, permission, and budget surfaces that are not observable.
- Resource-first queries and optional intended-change impact assessment.
- Agent-optimized, human-readable, and machine-consumable results from one canonical dependency model and one invocation.

### Deferred for later

- Mutation, proposal approval, remediation, or automatic change execution.
- A standalone visual graph-exploration product.
- Guaranteed discovery of relationships unavailable through the authenticated Foundry surfaces.
- Direct targeting of standalone Functions RIDs or Workshop variables/modules that lack a confirmed stable target-resolution contract in the pinned SDK.
- Name-based guessing of Workshop variables, arbitrary function implementations, or application internals.
- A shared or server-side graph store; the required reference in this release is local to the invoking machine.

---

## Dependencies and Assumptions

- The authenticated Foundry and `pltr` surfaces can enumerate or resolve enough resource metadata and cross-surface references to construct each verified relationship.
- Relationship coverage varies by Foundry surface, branch support, permissions, and invocation budgets; the capability exposes that variance as evidence or a gap.
- Foundry remains the source of truth for deployed resource state; local artifacts preserve observations and provenance but do not become a second authority.

---

## Sources / Research

- `docs/plans/2026-07-17-001-feat-foundry-dependency-analysis-plan.md` — implementation contract and keyed local SDK/source evidence.
- [raava-brain:docs/plans/2026-07-13-001-feat-foundry-application-portfolio-plan] — canonical ontology, compatibility-review, known-consumer, Foundry-authority, and `pltr` readback context.
