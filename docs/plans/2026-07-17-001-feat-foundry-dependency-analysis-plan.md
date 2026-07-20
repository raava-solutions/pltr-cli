---
date: 2026-07-17
status: active
origin: docs/brainstorms/2026-07-17-foundry-dependency-analysis-requirements.md
topic: foundry-dependency-analysis
target_repo: pltr-cli
---

# feat: Foundry Dependency Analysis

## Summary

Add a read-only, agent-native `pltr dependency` command group that resolves supported ontology entities and Compass RIDs and reports discovered intrinsic relations plus root-relative upstream, downstream, and adjacent paths. Optional free-text change intent produces deterministic impact ranking over the same graph. Every applicable but inaccessible, unsupported, unresolved, failed, or budget-cut dependency surface produces a coverage gap.

The default compact result includes path and evidence context and references a complete local JSON artifact written by the same invocation. JSON/CSV output may additionally render the complete result, but no output mode reconstructs a graph by re-running discovery.

The implementation exposes six explicit target commands: `object-type`, `property`, `link-type`, `action-type`, `query-type`, and `resource`. `resource` means a Compass-resolvable RID and specializes datasets/applications while retaining metadata-only handling plus gaps for other resource types. Standalone Functions RIDs, schedules as a separate CLI kind, and Workshop variables/modules are not direct target commands; function and schedule nodes remain discoverable where typed metadata provides them.

---

## Review Corrections Incorporated

- Action discovery uses `ActionTypeFullMetadata.action_type.parameters` and `ActionTypeFullMetadata.full_logic_rules`; it never treats shallow `ActionTypeV2.operations` as the full rule model.
- Dataset-to-schedule reverse discovery uses the real pinned `Dataset.get_schedules` iterator. The returned schedule RIDs are traversed through schedule action/affected resources, runs, submitted build RIDs, build jobs, and supported job outputs; only dynamically resolved lineage absent from returned fields is gapped.
- Every relation kind is classified as dependency-flow or adjacent-structural. Edge orientation is intrinsic and immutable; only dependency-flow edges derive upstream/downstream per root, structural edges remain adjacent, and evidence merges without changing edge identity.
- A target-kind × dependency-surface matrix drives mandatory gaps for applicable cells that do not produce evidence.
- Query data types are walked from parameter/output roots through an SCC/fixed-point closure of reachable `typeReferences`, including unions, so mutually recursive entry points receive the same complete leaves; reachable `UnsupportedType` values are gapped.
- Full action/query metadata and reverse indices are built once per ontology/branch/read context per invocation and share global request/page/item/time budgets.
- Workshop and function claims are narrowed to related surfaces without advertising unsupported direct targets or hiding internal-wiring gaps.
- Compact output points to a same-invocation, content-digested local artifact and includes the top path/evidence summary.
- The dataset schedule reverse-index record always carries the pinned endpoint's documented possible one-hour staleness as a target-scoped partial gap, including on empty success; descendant records remain independently enforceable.
- Operation-level provenance serializes SDK namespace/method and invocation version plus exact preview, branch-argument, timestamp, and timeout values with consistent argument-state enums.
- A dependency-internal page method preserves the existing `DatasetService.get_schedules` command/formatter contract, while all dependency reads receive remaining-budget-derived request timeouts.
- Read-context provenance, deterministic failure classes, and keyed capability assumptions replace ambiguous or dangling `A*` references; every SDK-dependent plan claim cites a CAP row.
- Dataset orchestration coverage is split into per-instance conditional records for reverse index, schedule detail/action, trigger, affected resources, runs, submitted build, build jobs, and typed outputs; reverse-index staleness cannot complete a descendant record.
- Configured build-target evidence comes only from `Schedule.action.target`; the pinned `Build` response has no `target` field. Recursive resource-bearing triggers and project scope produce relations, while hidden/unknown variants produce specific gaps.

---

## Residual P1 Resolution Gates

| # | Executable correction | Targeted test gate |
|---|---|---|
| 1 | KTD-03/U2 register every relation kind as dependency-flow or adjacent-structural; edge IDs exclude evidence and merge evidence IDs. | Reciprocal-root table for action↔object, query↔object, schedule↔dataset, link A↔B, container↔member, plus two-evidence/one-edge assertion. |
| 2 | KTD-05/U3 compute SCC/fixed-point query closure and gap reachable `UnsupportedType` (CAP-04). | Dual-entry A↔B SCC returns X and Y from both roots; reachable opaque type gaps while unreachable opaque type does not. |
| 3 | CAP-06/KTD-08/KTD-09/U4 make schedule reverse-index freshness deterministically partial. | Fully paged empty success retains `schedule-index-may-be-stale`, `max_lag_seconds=3600`, and never becomes `covered-empty`. |
| 4 | U1/U7/U8 serialize immutable operation provenance with CAP IDs, SDK namespace/method/version, exact preview/branch states and values, timestamps, and timeout. | Exact-schema table covers preview, non-preview, explicit/default branch, and branchless operations; every evidence reference resolves. |
| 5 | CAP-15/CAP-16/U4 preserve `DatasetService.get_schedules` dictionaries and add `get_schedule_rids_page`; forward timeouts through all dependency reads. | Existing schedules-list command still passes dictionaries to its formatter; dependency wrappers assert exact page/branch/preview/timeout kwargs. |
| 6 | Dataset matrix, U4, U6, U8, and U9 all carry the same one-hour staleness semantics (CAP-06). | Empty and non-empty dataset results render the same deduplicated partial gap in compact, JSON, CSV, and artifact coverage. |
| 7 | CAP ledger plus `SDK_OPERATION_SPECS` is the closed authority for SDK-dependent claims (CAP-12). | Registry-completeness table fails for missing/dangling CAP IDs or branch/preview support that differs from the pinned signature. |
| 8 | CAP-09/U4 remove the nonexistent `Build.target`; configured targets/inputs come only from `Schedule.action.target`. | Exact pinned-model schema asserts `Build.model_fields` has no `target`, schema-valid build fixtures/wrapper output cannot supply it, and no collector reads or fabricates it. |
| 9 | KTD-08/KTD-09/U4/U6 create conditional per-instance records for all eight dataset sub-reads. | A stale-but-successful reverse index cannot mask deliberately uninvoked runs, jobs, or outputs collectors; each reports its own `collector-did-not-report`. |
| 10 | CAP-07/U4 recursively collect resource-bearing trigger variants and project scope, or gap the exact variant/locator. | Nested `and`/`or` fixtures emit every RID path; manual/time emit no resource edge; unknown/hidden variants gap; project scope is adjacent. |

---

## Final CTO Finding Resolution Map

| Final finding | Pinned source resolution | Executable plan/test resolution |
|---|---|---|
| CAP-09/U4 falsely used `Build.target` | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/models.py`: `Action.target` is declared on `Action`; the `Build` response declaration has no `target`; `CreateBuildRequest.target` is request-only. `.venv/lib/python3.11/site-packages/foundry_sdk/_core/model_base.py` allows extras, so an injected attribute is not declared-schema evidence. | CAP-09 and U4 remove build target from the wrapper/collector. `tests/test_services/test_orchestration.py` asserts the exact `Build.model_fields` contract excludes `target` and wrapper output cannot manufacture it; `tests/test_services/test_dependency.py` proves targets/inputs originate from `Schedule.action.target`. |
| One combined dataset cell could hide skipped reads and omitted trigger/scope references | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/models.py` declares `Schedule.action`, optional `trigger`, `scope_mode`, recursive `AndTrigger`/`OrTrigger`, six resource-bearing trigger leaf classes, `ProjectScope.project_rids`, submitted `ScheduleRunSubmitted.build_rid`, `Build.job_rids`, and typed `Job.outputs`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/schedule.py` and `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/build.py` expose the corresponding detail/affected-resource/runs/build/jobs reads. | KTD-08/KTD-09 and the dataset ledger define eight conditional surfaces. `tests/test_services/test_dependency.py` gates per-RID record creation, stale-parent isolation, omitted collectors, nested `and`/`or`, future/raw unknown discriminators, hidden triggers, and project-scope adjacency; `tests/test_services/test_orchestration.py` gates structured trigger/scope preservation. U6 completes every conditional record independently. |

---

## Actors

- **ACT-1 Ontology manager** evaluates blast radius before approving a semantic change.
- **ACT-2 Foundry builder** inspects a resource while estimating or implementing a change.
- **ACT-3 Autonomous agent** retrieves compact evidence before planning, review, or action.

All actors use the same graph and command family; only rendering differs.

---

## Verified Capability Assumptions

These IDs are the only capability-assumption references used below.

| ID | Verified fact at pinned SDK `1.95.0` | Implementation consequence | Evidence |
|---|---|---|---|
| CAP-01 | `ObjectType.get`, `get_full_metadata`, and `get_outgoing_link_type` accept `branch`; full metadata exposes `object_type`, `link_types`, `implements_interfaces`, `implements_interfaces2`, and `shared_property_type_mapping`. | Ontology structure is branch-aware and evidence-backed; preview failure becomes a gap. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/object_type.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/models.py` (`ObjectTypeFullMetadata`) |
| CAP-02 | Top-level `client.ontologies.ActionTypeFullMetadata` contains branch-aware `get/list`; its model contains `action_type: ActionTypeV2` and `full_logic_rules: List[ActionLogicRule]`, while `action_type.parameters` contains `ActionParameterV2`. It is not nested under `Ontology`. | Forward and reverse action references derive from full rules plus parameter types, including nested function rules and parameter-bound object/interface references. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/_client.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/action_type_full_metadata.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/models.py` (`ActionTypeFullMetadata`, `ActionLogicRule`, `ActionParameterV2`) |
| CAP-03 | `ActionTypeV2.operations: List[LogicRule]` is a shallow summary union distinct from `ActionLogicRule`. | `operations` may aid display only; dependency completeness and edges come from `full_logic_rules` plus parameters, with no list-index correlation. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/models.py` (`ActionTypeV2`, `LogicRule`) |
| CAP-04 | `QueryTypeV2` exposes parameters, output, and a recursive `type_references` map. `QueryTypeReferenceType.type_id` references that map; `QueryUnionType.union_types` is a list; `QueryDataType` includes `core_models.UnsupportedType`. | Compute a sound reachable closure across recursive components; gap reachable missing/unknown/`UnsupportedType` shapes rather than finalizing them as empty. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/models.py` (`QueryDataType`, `QueryTypeReferenceType`, `QueryUnionType`, `QueryTypeV2`); `.venv/lib/python3.11/site-packages/foundry_sdk/v2/core/models.py` (`UnsupportedType`) |
| CAP-05 | Nested `client.ontologies.Ontology.QueryType.list` accepts `branch`, while `QueryType.get` does not. | Branch-aware query resolution and reverse discovery use the once-per-context list cache rather than a branchless `get` call. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/ontology.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/query_type.py` |
| CAP-06 | `Dataset.get_schedules(dataset_rid, branch_name, page_size, page_token, request_timeout)` exists in SDK 1.95.0 and returns an iterator of schedule RID strings. Its generated docstring warns that recent schedule changes may take up to one hour to appear and that results are outdated meanwhile. Existing `DatasetService.get_schedules` incorrectly treats returned strings as objects and drops their values. | Preserve returned RIDs as evidence, but always mark this reverse-index basis partial/stale (including empty success) unless an independent freshness-complete source exists. Use a paged dependency seam rather than treating iterator completion as freshness proof. | `src/pltr/services/dataset.py`; `tests/test_services/test_dataset.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/datasets/dataset.py` (`Dataset.get_schedules`) |
| CAP-07 | `Schedule` exposes structured `action`, optional discriminated `trigger`, and discriminated `scope_mode`. Resource-bearing trigger leaves are `DatasetUpdatedTrigger`, `JobSucceededTrigger`, `NewLogicTrigger`, `TableUpdatedTrigger`, `ScheduleSucceededTrigger`, and `MediaSetUpdatedTrigger`; `AndTrigger`/`OrTrigger` recursively contain triggers, while manual/time leaves contain no resource RID. `ProjectScope.project_rids` is observable; the trigger docstring says omission can reflect permission. `Schedule.get_affected_resources` returns dataset/buildable RIDs; `Schedule.runs` returns `ScheduleRun`; a submitted run contains `result.build_rid`. | A returned schedule RID conditionally drives detail/action, recursive trigger, project-scope adjacency, affected-resource, and run evidence. Missing/unknown/malformed trigger or scope shapes are explicit gaps; omission is not treated as verified empty when permission may hide the trigger. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/schedule.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/models.py` (`Schedule`, `Action`, `Trigger`, `AndTrigger`, `OrTrigger`, resource-bearing trigger classes, `ProjectScope`, `AffectedResourcesResponse`, `ScheduleRunSubmitted`) |
| CAP-08 | `Build.jobs(build_rid)` returns jobs; `Job.outputs` contains discriminated `DatasetJobOutput` or `TransactionalMediaSetJobOutput`. Unsupported output types are omitted by the API. | Direct schedule/build traversal emits verified supported output edges and a partial gap noting API-omitted output kinds. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/build.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/models.py` (`Build`, `Job`, `JobOutput`) |
| CAP-09 | `Schedule.action.target` is the response-model source for manual/upstream/connecting targets; connecting targets expose configured `input_rids`. The pinned `Build` response declares `rid`, branch/timestamps/creator, fallback/retry/abort/status fields, `job_rids`, and optional `schedule_rid`, but no `target`. Target fields on create/replace request models are not build-response evidence. `Job.outputs` exposes only supported output kinds, and upstream targets do not enumerate the runtime-resolved upstream closure. | Emit configured target/input relations only from schedule action evidence. The build wrapper and collector have no target field. Emit typed outputs, and gap dynamically resolved upstream lineage and API-omitted output kinds instead of claiming complete physical lineage. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/models.py` (`Action`, `Build`, `CreateBuildRequest`, `BuildTarget`, `Job.outputs`); `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/build.py` |
| CAP-10 | No inspected SDK 1.95.0 surface exposes Workshop module/variable wiring or third-party-application internal ontology/function wiring. | Compass-resolved nodes retain metadata, but applicable Workshop/application internal relations always produce explicit unsupported gaps. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/widgets/`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/third_party_applications/`; `src/pltr/services/resource.py`; `src/pltr/services/third_party_applications.py` |
| CAP-11 | SDK calls expose typed authentication, permission, not-found/API-not-found, rate/QoS, timeout, proxy/connection/RPC, request-validation, and server failures. | Preserve typed failures until dependency-layer classification; never parse message strings to decide completeness. | `.venv/lib/python3.11/site-packages/foundry_sdk/_errors/__init__.py` |
| CAP-12 | `pyproject.toml` allows `foundry-platform-sdk>=1.95.0,<2.0.0`, while `uv.lock` and the local environment resolve `1.95.0`. | Tests use 1.95.0-shaped real model instances/fixtures; capability assumptions must be re-audited on an SDK update. | `pyproject.toml`; `uv.lock` |
| CAP-13 | SDK list calls return `ResourceIterator`; its first fetched page is exposed through `.data` and `next_page_token`, while normal iteration may fetch additional pages internally. | Budgeted scans reissue list calls one page at a time with explicit page tokens and never exhaust an uninstrumented iterator. | `.venv/lib/python3.11/site-packages/foundry_sdk/_core` (`ResourceIterator`, `PageIterator`); list client files cited above |
| CAP-14 | `PropertyV2` does not expose a backing dataset/column identifier. | Property-to-dataset-column is an unsupported matrix cell unless a different authenticated read supplies direct evidence. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/models.py` (`PropertyV2`) |
| CAP-15 | The current public `DatasetService.get_schedules(dataset_rid) -> List[Dict[str, Any]]` is called by `pltr dataset schedules list`, whose formatter iterates dictionaries with `schedule_rid`, `name`, `description`, `enabled`, and `created_time`; its service test asserts that shape. | Preserve this command/formatter contract. Add a distinct dependency-internal `get_schedule_rids_page(...)` seam instead of changing the public method to a page envelope. | `src/pltr/services/dataset.py`; `src/pltr/commands/dataset.py`; `src/pltr/utils/formatting.py` (`format_schedules`); `tests/test_services/test_dataset.py` |
| CAP-16 | The inspected generated SDK 1.95.0 ontology, dataset, schedule, build, filesystem-resource, and third-party-application read methods expose `request_timeout`; branch and preview kwargs vary by method. Full action/object metadata accepts preview and branch, query listing accepts branch but not preview, dataset schedule discovery accepts branch but not preview, schedule detail/affected-resource and third-party-application reads accept preview but no branch, and schedule runs/build/filesystem-resource reads are branchless and non-preview. | Every dependency SDK call receives the remaining-budget timeout, and operation provenance records only arguments the exact method supports: explicit/server-default/not-applicable for both branch and preview. | `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/action_type_full_metadata.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/object_type.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/query_type.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/datasets/dataset.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/schedule.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/build.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/filesystem/resource.py`; `.venv/lib/python3.11/site-packages/foundry_sdk/v2/third_party_applications/third_party_application.py` |

Capability trace rule: implementation steps and tests may assert SDK behavior only through a cited CAP ID above. Product invariants cite their requirement IDs. Any SDK upgrade or newly used method requires a new or revised CAP row before implementation; no prose-only capability assumption is executable authority (CAP-12).

---

## Requirements Traceability

| Requirement / flow | Planned coverage |
|---|---|
| R1 target addressability | U1 six resolvers; U3 ontology/action/query metadata; U4 dataset/resource resolution; U7 six CLI commands |
| R2 direct/transitive relations | U2 intrinsic graph primitives; U3-U4 collectors; U6 bounded traversal |
| R3 participants/orientation/class/path/evidence/read context | U1 operation provenance/evidence; U2 traversal-class/edge/path schema and evidence merge; enforced in U3-U6 |
| R4 verified-empty versus incomplete/stale coverage states | U1 coverage ledger/error taxonomy; U4 schedule-index staleness and conditional sub-read records; U5/U6 completion and budget gaps |
| R5 target-kind × surface enforcement | Coverage matrix and dataset conditional ledger below; U2/U4/U5 completion assertion |
| R6 compact result with path/evidence | U6 ranked paths; U8 formatter |
| R7 same-invocation graph reference | U8 atomic local artifact and digest |
| R8 artifact completeness | U8 full graph/coverage/error/provenance serialization |
| R9 deterministic readable assessment | U6 ranking/templates; U8 formatter |
| R10 optional intended change | U6 assessment; U7 shared `--change` |
| R11 impact ranking and verification | U6 `_assess_change` |
| R12 uncertainty | U6 maps all intersecting gaps into change uncertainty |
| R13-R14 operation-level branch/preview/SDK provenance | U1 immutable operation provenance; U3 exact action/object/query arguments; U4 exact dataset/orchestration arguments; U7/U8 serialization |
| R15 one-time reverse metadata | U3 context-keyed action/query indexes |
| R16 global budgets | U1 `DiscoveryBudget`; U3-U6 charge every request/page/item/time unit |
| R17 deterministic failures | U1 typed classifier; U7 stable exit/error payloads |
| R18 recursive query closure/opaque types | U3 SCC/fixed-point reference closure and reachable `UnsupportedType` gap tests |
| R19 stale dataset schedule reverse index | CAP-06; KTD-08/KTD-09; dataset matrix row; U4/U6/U8/U9 |
| R20 wrapper compatibility/request timeout | CAP-15/CAP-16; U1 timeout calculation; U4 page seam plus existing command regression |
| R21 conditional dataset sub-read enforcement | KTD-08/KTD-09; dataset conditional ledger; U4/U6 uninvoked-collector gates |
| R22 recursive trigger and project-scope evidence | CAP-07; dataset conditional ledger; U4 recursive trigger/scope collector and variant-gap gates |
| F1 resource query | U1-U8 without `--change` |
| F2 change-aware assessment | U1-U8 with `--change` |
| AE1 property coverage | U3 property collector + action/query indices + mandatory matrix gaps |
| AE2 action/query and related-function coverage | U3 full action metadata and cycle-safe query walker + matrix gaps |
| AE3 real but freshness-limited dataset chain | U4 paged dataset/orchestration wrappers, traversal, and deterministic stale-index gap |
| AE4 semantic-change ranking | U6 |
| AE5 large cone artifact and cutoff | U6 budget gaps + U8 same-invocation artifact |
| AE6 inaccessible/unsupported surface | U1/U5 |
| AE7 mutually recursive query references | U3 two-entry SCC closure and `UnsupportedType` tests |
| AE8 one-time indexes/global bounds | U1/U3 budget and cache assertions |
| AE9 compact path/evidence/artifact identity | U6/U8 rendering and artifact tests |
| AE10 relation class/identity/evidence merge | KTD-03; U2 reciprocal-root relation table |
| AE11 exact operation provenance | U1/U3/U4/U8 exact-schema tests |
| AE12 existing schedules command compatibility | CAP-15; U4 service and command regression tests |
| AE13 nested trigger/scope evidence and variant gaps | CAP-07; U4 recursive trigger and project-scope tests |
| AE14 stale-parent/omitted-child enforcement | KTD-08/KTD-09; U4/U6 conditional-record completion tests |

---

## Key Technical Decisions

**KTD-01 — Multi-namespace service, existing conventions.** Add `DependencyGraphService(BaseService)` in `src/pltr/services/dependency.py`; `_get_service()` returns `self.client`, matching the multi-namespace pattern in `src/pltr/services/connectivity.py`. Reuse existing wrappers where their returned fields are sufficient; extend wrappers where the dependency feature needs typed fields they currently discard.

**KTD-02 — Plain dictionaries with a strict documented schema.** Existing services return `Dict[str, Any]`, so no new model dependency is introduced. Constructors validate required fields and tests assert exact schemas.

**KTD-03 — Relation class controls traversal direction; evidence does not control identity.** Every registered `relation_kind` declares exactly one `traversal_class`:

- `dependency-flow`: input/provider is intrinsic `source`; dependent/consumer is intrinsic `target`. Action→object, query→object, and schedule→dataset relations use the appropriate semantic dependency-flow kind according to which participant provides input and which consumes/affects it.
- `adjacent-structural`: orientation exists only for stable storage. `container_to_member` stores container→member; `declared_source_to_target` stores Foundry's declared link A/source→B/target; `peer_canonical` orders peers by canonical node ID. None implies dependency flow.

For dependency-flow only, source→target is root-relative `downstream` and target→source is `upstream`. Every traversal of an adjacent-structural edge is `adjacent`, regardless of stored orientation or root. A path is overall `upstream` only when every non-adjacent step is upstream, `downstream` only when every non-adjacent step is downstream, and `adjacent` when any step is adjacent or upstream/downstream are mixed. `--direction` filters expansion by these derived values and never mutates stored edges.

The canonical edge ID hashes only `(source, target, relation_kind, intrinsic_orientation)`; `traversal_class` is validated from the relation-kind registry and therefore is not an independent identity input. Root, traversal direction, collector, read operation, and evidence IDs are excluded. Re-observing the same semantic relation unions and stable-sorts `evidence_ids` on its single edge. A conflicting traversal class or orientation for the same semantic relation fails normalization rather than creating a second edge (R3).

**KTD-04 — Full action rules and parameters are the dependency source.** Visit `ActionTypeFullMetadata.action_type.parameters` and every discriminant in `full_logic_rules`. The full-rule visitor follows parameter IDs back to parameter data types, recurses into `BatchedFunctionLogicRule.function_rule`, records `FunctionLogicRule.function_rid`, and records object/interface/link/property names from full rules and argument maps. A concrete parameter data type supplies a verified target; a generic `objectType` parameter that does not name a type produces an unresolved-reference gap. Shallow `action_type.operations` may be rendered as descriptive metadata but never creates or completes a dependency edge, and it is never joined to full rules by list position (CAP-02, CAP-03).

**KTD-05 — Reachability-based SCC/fixed-point query closure.** Start separately at each parameter data type and the output, recurse through array/set/struct/entry-set/aggregation/union members, and collect the reachable `typeReference` graph plus direct object/object-set/interface leaves. Run deterministic Tarjan SCC over the union of references reachable from those roots, condense it to a DAG, and compute each component's transitive leaf and gap closure in reverse topological order (or an equivalent monotone fixed point until no set changes). Never publish a per-reference memo while its SCC is incomplete. After closure, reattach leaves/gaps to each parameter/output root using a deterministic shortest witness path so root-specific field prefixes remain correct without infinite cycle paths. A missing reachable map entry emits `invalid-response`; a reachable `core_models.UnsupportedType` emits `unsupported-query-data-type` with its field locator; unknown reachable discriminants are unresolved; unreachable definitions are ignored. This makes entry through either member of a mutually recursive component yield the same complete leaves (CAP-04).

**KTD-06 — Per-invocation caches and reverse indices.** `AnalysisContext` owns caches keyed by `(profile_identity, ontology_rid, branch_read_context)`:

- one paginated top-level `client.ontologies.ActionTypeFullMetadata.list(..., branch=..., preview=True)` pass and indices by object type, interface, link type, property, parameter, and function RID;
- one paginated `client.ontologies.Ontology.QueryType.list(..., branch=...)` pass and indices by reachable object/interface type and query API name;
- direct resolver maps populated from those same lists.

Each cache is built at most once per key per CLI invocation, even when BFS revisits the ontology. There is no process-global or cross-invocation cache.

**KTD-07 — Global budgets, not per-collector caps.** `DiscoveryBudget` is shared by resolution, cache building, collectors, and BFS. Defaults: `max_requests=200`, `max_pages=100`, `max_items=10_000`, `max_nodes=150`, `max_depth=2`, `time_budget_seconds=60`; hard ceilings: `1000`, `500`, `100_000`, `1000`, `10`, `600`. Every SDK call charges a request; every fetched iterator page charges a page before its items are consumed; every raw item charges an item. Every dependency wrapper/raw SDK call accepts and forwards `request_timeout=min(configured_request_timeout, remaining_time)`, and the exact forwarded value is operation provenance. Exhaustion stops only the affected work, preserves collected evidence, and emits one deduplicated `budget-exhausted` partial gap per affected surface with counters and limit (CAP-16).

**KTD-08 — Coverage is a matrix-complete, conditionally expanding ledger.** Before collection, create a `CoverageRecord` for every applicable root target-kind × surface cell. Before dispatching the next collector, each returned schedule RID, submitted build RID, or job RID creates the conditional records made applicable by that value, linked to the evidence that established applicability. The dataset ledger uses eight distinct surfaces: `schedule-reverse-index`; per schedule RID, `schedule-detail-action`, `schedule-trigger`, `schedule-affected-resources`, and `schedule-runs`; per submitted `build_rid`, `submitted-build`; per returned build, `build-jobs`; and per returned job, `typed-outputs`. After collectors run, every static or conditional record must be `covered` (verified evidence exists), `covered-empty` (a freshness-complete successful read or known non-resource variant proved zero relationships), `partial`, `inaccessible`, `unsupported`, `unresolved`, or `budget-exhausted`. Every status except `covered`/`covered-empty` produces a first-class gap. Zero edges or complete pagination alone never proves absence. `Dataset.get_schedules` can never finalize its own reverse-index record as `covered` or `covered-empty`: returned RIDs are verified evidence inside that `partial` record and `schedule-index-may-be-stale` remains. Its status never propagates to descendants. An applicable record with no terminal collector report becomes `unresolved/collector-did-not-report` and fails completion even when an ancestor is partial. Records/gaps deduplicate by `(subject_node_id, surface, read_context_id)` and `(subject_node_id, surface, reason_code, read_context_id)` respectively, so different returned RIDs cannot mask one another (CAP-06, CAP-07, CAP-08).

**KTD-09 — Dataset-to-schedule traversal is real but only the reverse index is deterministically partial.** A dataset target calls dependency-internal `DatasetService.get_schedule_rids_page` with exact branch/page/timeout arguments and receives exact schedule RID strings. Every page operation records `known_limitations: [{reason_code: schedule-index-may-be-stale, max_lag_seconds: 3600}]`; only the dataset's `schedule-reverse-index` record retains that partial status after successful empty or non-empty pagination. Every returned schedule RID creates independent detail/action, trigger, affected-resource, and runs records before their collectors are dispatched. Every submitted run's `build_rid` creates `submitted-build`; a returned build creates `build-jobs`; and each returned job creates `typed-outputs`. Each must terminate independently, so the reverse-index gap cannot mask a skipped or failed descendant read. Schedule action targets, recursive trigger references, project-scope adjacency, affected resources, runs, submitted builds, jobs, and supported outputs remain evidence-backed edges. Upstream-target runtime closure and API-omitted output kinds remain additional explicit, surface-specific gaps. Co-output is adjacent build membership, never proof of causal lineage. No second freshness-complete reverse source exists in the inspected SDK, so U4 does not suppress the reverse-index staleness gap (CAP-06 through CAP-09, CAP-15, CAP-16).

**KTD-10 — Addressability is narrow and explicit.** There is no standalone `function`, `schedule`, or Workshop-variable command. Function RIDs found in full action rules and schedule RIDs returned for dataset targets remain related nodes. Workshop/application targets require a Compass-resolvable RID through `resource`; only generic metadata is verified unless a dedicated supported surface exists. Internal wiring gaps remain explicit (CAP-10).

**KTD-11 — Deterministic typed failures.** The dependency layer classifies original exceptions into `authentication`, `permission-denied`, `not-found`, `branch-not-found`, `rate-limited`, `timeout`, `connection`, `invalid-request`, `unsupported`, `invalid-response`, `budget-exhausted`, `artifact-write-failed`, `internal`, or `unknown`. Target-resolution, branch-resolution, and artifact failures are fatal structured errors. Sub-surface failures update the exact coverage cell/gap and allow independent collectors to continue. Classification is by exception type/status/name through the preserved exception chain, never message substring (CAP-11).

**KTD-12 — Same-invocation artifact is mandatory.** Before compact rendering, atomically write the complete result to a mode-`0600` JSON file. Use explicit `--graph-output PATH` when supplied; otherwise use `${XDG_STATE_HOME:-~/.local/state}/pltr/dependency/<analysis_id>.json`. `--output` controls only the requested rendering and never silently replaces the graph artifact. `analysis_id` and `sha256` derive from canonical serialized content with a documented non-self-referential digest boundary. Compact output prints `analysis_id`, absolute artifact path, digest, top path, and evidence summary. Artifact write failure is fatal because R7/R8 would otherwise be false.

**KTD-13 — Deterministic non-LLM assessment.** Ranking uses hop count, structural severity, coverage confidence, and fixed change keywords with stable tie-breaks. Text is templated. No language-model call is added.

---

## Graph, Evidence, Provenance, and Error Contracts

```text
ReadContext = {
  id, profile, host_fingerprint,
  ontology_rid?, requested_branch?, dataset_branch?,
  invocation_sdk_package, invocation_sdk_version, observed_at
}

ArgumentObservation = {
  mode: explicit|server-default|not-applicable,
  value: string|boolean|null
}

OperationProvenance = {
  id, read_context_id,
  sdk_namespace, sdk_method, capability_ids: [...], invocation_sdk_version,
  invoked_at, observed_at,
  branch_argument: ArgumentObservation,
  preview_argument: ArgumentObservation,
  request_timeout_seconds,
  known_limitations: [{reason_code, message, max_lag_seconds?}]
}

Node = {id, kind, display_name, identifiers, read_context_id, is_target}

Evidence = {
  id, operation_provenance_id, locator, field_path,
  response_discriminator?, raw_type
}

Edge = {
  id, source, target, relation_kind, traversal_class: dependency-flow|adjacent-structural,
  intrinsic_orientation,
  evidence_ids: [...], coverage: verified|partial
}

CoverageRecord = {
  target_kind, surface, subject_node_id, read_context_id,
  parent_record_id?, applicability_evidence_id?,
  status: covered|covered-empty|partial|inaccessible|unsupported|unresolved|budget-exhausted,
  attempted, complete, evidence_ids: [...], error_id?, reason?
}

PathStep = {
  edge_id, from_node, to_node,
  traversal_direction: upstream|downstream|adjacent,
  evidence_ids: [...]
}

CoverageGap = {
  surface, target, coverage: inaccessible|unsupported|unresolved|partial|budget-exhausted,
  reason_code, message, read_context_id,
  operation?, budget_snapshot?, retryable
}

FatalError = {
  error_class, target, operation, message, retryable, read_context_id
}
```

Deterministic exception mapping:

| Original failure | `reason_code` / `error_class` | Coverage for sub-surface | Retryable |
|---|---|---|---|
| `UnauthorizedError` | `authentication` | `inaccessible` | no |
| `PermissionDeniedError` | `permission-denied` | `inaccessible` | no |
| `NotFoundError` | `not-found` | `unresolved` | no |
| typed error with `name == "BranchNotFound"` | `branch-not-found` | `unresolved` | no |
| `ApiNotFoundError` | `unsupported` | `unsupported` | no |
| `RateLimitError`, `PalantirQoSException` | `rate-limited` | `partial` | yes |
| SDK `TimeoutError` | `timeout` | `partial` | yes |
| SDK `ConnectionError`, `ProxyError`, `PalantirRPCException` | `connection` | `partial` | yes |
| `BadRequestError`, `UnprocessableEntityError` | `invalid-request` | `unresolved` | no |
| `InternalServerError` | `internal` | `partial` | yes |
| Missing/unknown validated response field or discriminant | `invalid-response` | `unresolved` | no |
| `DiscoveryBudget` refusal | `budget-exhausted` | `partial` | yes with higher/narrower budget |
| Atomic graph-artifact write failure | `artifact-write-failed` | n/a; command-fatal | condition-dependent |
| Unmapped original exception | `unknown` | `unresolved` | no |

The same mapping yields a fatal `FatalError` when the failed operation is required to identify the root target. Python programming errors are not converted to coverage gaps. `unsupported` appears only in coverage/error enums; branch and preview argument enums use `not-applicable` when the SDK method has no such argument (R13-R14).

Evidence locators are stable logical paths such as `fullLogicRules[3].propertyArguments.employeeId`, `parameters.employee.dataType`, `typeReferences.EmployeeNode.unionTypes[1]`, `runs[0].result.buildRid`, or `jobs[2].outputs[0].datasetRid`. They do not contain credentials or raw response bodies.

`OperationProvenance` is immutable and serialized in the artifact. `sdk_namespace` is the concrete generated client path (for example `client.ontologies.ActionTypeFullMetadata`) and `sdk_method` is the invoked method (for example `list`). A closed `SDK_OPERATION_SPECS` registry declares the supporting CAP IDs and whether branch/preview arguments exist for every invoked method; constructors reject missing/dangling CAP IDs or kwargs outside that spec. `invocation_sdk_version` is resolved at command startup from the installed `foundry-platform-sdk` distribution and copied onto every operation; it is not inferred from the lockfile. For an accepted and passed argument, `mode=explicit` and `value` is exact. For an accepted but omitted argument, `mode=server-default` and `value=null`. For a method without that argument, `mode=not-applicable` and `value=null`. Requested branch stays only in `ReadContext`, so it cannot be confused with what a particular call received (CAP-12, CAP-16; R13-R14).

---

## Target-Kind × Dependency-Surface Coverage Matrix and Conditional Dataset Ledger

Legend: **D** direct supported evidence; **I** once-per-context reverse index; **C** conditional supported evidence when the resource resolves; **G** mandatory explicit gap; **N** structurally not applicable. `D/G` means supported subfields are emitted and the known omitted remainder is gapped. A failed D/I/C call becomes a typed gap. No applicable cell may finish empty without a gap.

| Target kind | Ontology structure/backing | Full action metadata | Query/related-function metadata | Dataset orchestration | Application internals | Workshop internals | Compass metadata |
|---|---|---|---|---|---|---|---|
| `object-type` | D/G (structure direct; backing dataset mapping unavailable) | I | I | G | G | G | C/G |
| `property` | D/G (link/interface direct; dataset-column lineage unavailable) | I | I | G | G | G | C/G |
| `link-type` | D | I | I | G | G | G | C/G |
| `action-type` | D (from full rules/parameters) | D | C/G (typed Function RID edge; internals/reverse consumers unavailable) | G | G | G | C/G |
| `query-type` | D (reachable data types) | I | D | G | G | G | C/G |
| `dataset` | G (ontology backing/column reverse mapping unavailable) | G | G | Conditional ledger below; no combined terminal status | G | G | D |
| `third-party-application` | G | G | G | G | G | G | D |
| `workshop-resource` | G | G | G | G | G | G | D |
| `generic-resource` | G when semantically applicable | G when semantically applicable | G when semantically applicable | G when semantically applicable | G when semantically applicable | G when semantically applicable | D |

Classification of a generic Compass resource is based on returned type metadata, never substring guessing alone. Unknown type metadata remains `generic-resource` and applicable relationship surfaces receive `unknown-resource-capabilities` gaps.

Dataset orchestration is not one matrix cell. The following records are created as soon as their applicability condition is observed, before collector dispatch:

| Conditional surface | Subject / applicability | Required conclusion | Evidence or specific-gap contract |
|---|---|---|---|
| `schedule-reverse-index` | Dataset target | Always `partial` for a successful read under CAP-06, including empty success; otherwise a typed specific gap | Returned schedule RID evidence plus `schedule-index-may-be-stale`; never terminalizes another row |
| `schedule-detail-action` | Each returned schedule RID | `covered`, `covered-empty`, or a specific gap | Schedule detail and configured target/input evidence only from `Schedule.action.target`; scope is inspected from the same response |
| `schedule-trigger` | Each returned schedule RID | `covered`, `covered-empty` only for a known non-resource trigger, or a specific gap | Recursive resource-bearing leaf evidence; permission-hidden, malformed, or unknown variants are locator-specific gaps |
| `schedule-affected-resources` | Each returned schedule RID | `covered`, `covered-empty`, or a specific gap | Exact affected buildable RID response or verified empty page/result |
| `schedule-runs` | Each returned schedule RID | `covered`, `covered-empty`, or a specific gap | Paged run evidence, including ignored/error/pending results without invented builds |
| `submitted-build` | Each submitted run `build_rid` | `covered` or a specific gap | `Build.get` response fields; the response has no target evidence |
| `build-jobs` | Each returned build | `covered`, `covered-empty`, or a specific gap | Paged jobs for that exact build RID |
| `typed-outputs` | Each returned job | `covered`, `covered-empty`, or a specific gap | Supported discriminated dataset/media-set outputs; API-omitted kinds retain their own partial gap |

For `schedule-detail-action`, `ProjectScope.project_rids` create adjacent-structural project relations; `UserScope` has no project RID and is a verified non-resource scope. An unknown or malformed scope variant creates `unknown-schedule-scope-variant` with its exact field locator. A record that was created but never invoked is `unresolved/collector-did-not-report`, regardless of the reverse-index status.

---

## Planned File Structure

```text
src/pltr/
  cli.py                                      register dependency app
  services/
    dependency.py                             graph engine, caches, collectors, budgets
    dataset.py                                preserve public command contract; add dependency RID pages
    orchestration.py                          structured read wrappers for dependency fields
  commands/
    dependency.py                             six read-only subcommands
  utils/
    dependency_artifacts.py                   atomic local JSON artifact
    formatting.py                             compact/full dependency rendering

tests/
  test_services/
    test_dependency.py                        graph/collector/cache/budget tests
    test_dataset.py                           schedule-RID wrapper regression
    test_orchestration.py                     real-shaped schedule/run/job output tests
  test_commands/
    test_dependency.py                        CLI/error/flag/artifact tests
    test_dataset.py                           existing schedules-list contract regression
  test_utils/
    test_dependency_artifacts.py              atomic path/digest/permission tests

docs/user-guide/commands.md
claude_skill/reference/dependency-commands.md
claude_skill/SKILL.md
README.md
```

---

## Implementation Units

### U1. Read context, typed failures, global budget, and target resolution

**Goal:** Establish the cross-cutting correctness primitives before collectors.

**Requirements:** R1, R3-R5, R13-R17; AE5, AE6, AE8, AE9

**Files:**
- `src/pltr/services/dependency.py` (new)
- `tests/test_services/test_dependency.py` (new)

**Implementation:**

1. Add `AnalysisContext` containing read contexts, immutable operation-provenance registry, per-invocation caches, evidence registry, and `DiscoveryBudget`. Define `SDK_OPERATION_SPECS` from the CAP ledger as the only allowed SDK-operation/argument-capability registry.
2. Build read-context IDs from non-secret profile name, host fingerprint, ontology/dataset context, requested branch, and the installed invocation SDK package/version. Keep branch argument state out of `ReadContext`; each SDK call records its own exact `ArgumentObservation` for branch and preview (CAP-12, CAP-16; R13-R14).
3. Implement the deterministic exception classifier in KTD-11. Preserve original SDK exceptions within this layer; do not classify wrapper-produced message strings.
4. Implement budget charging and `request_timeout` calculation. Reject values above hard ceilings before network access; construct operation provenance before each call and finalize its observation timestamp/limitations after the response (CAP-16).
5. Implement six resolvers. Branch-aware ontology query resolution comes from U3's list cache; action resolution uses full metadata; generic/dataset/application resources use `ResourceService` identity before subtype collection.
6. Target not-found/authentication/invalid-identifier failures return a fatal error and exit; a failure on a non-target surface becomes a gap.

**Tests:**

- Each resolver returns the exact node/read-context schema and every evidence item references one serialized operation-provenance record.
- Exact-schema cases cover: action/object preview `true` with explicit branch; query listing with explicit branch and preview `not-applicable`; an accepted but omitted branch/preview as `server-default`; dataset schedule discovery with explicit branch and preview `not-applicable`; schedule detail with preview `true` and branch `not-applicable`; and branchless/non-preview build/filesystem-resource reads with both arguments `not-applicable` (CAP-01, CAP-02, CAP-05, CAP-06, CAP-07, CAP-08, CAP-16).
- Every case asserts concrete SDK namespace/method, runtime-resolved `1.95.0` invocation version in the pinned test environment, exact argument values, invocation/read timestamps, and forwarded request timeout; requested branch remains separate.
- A table-driven registry-completeness test exercises every SDK operation named by U1/U3/U4/U5, asserts at least one existing CAP ID, verifies branch/preview support against that CAP's pinned signature, and fails on a dangling CAP ID or an operation introduced without a spec.
- Every SDK exception class in CAP-11 maps to the expected stable `error_class`, `coverage`, and `retryable` value.
- Target permission/not-found is fatal; the same failure in a sub-collector is a gap and independent work continues.
- Request/page/item/time ceilings stop before overrun and produce exact budget snapshots.
- No provenance/evidence/error payload contains a token or raw authorization header.

---

### U2. Intrinsic graph relations, root-relative paths, and coverage completion

**Goal:** Lock graph semantics before domain collectors produce edges.

**Requirements:** R2-R5; AE5, AE6, AE9

**Files:**
- `src/pltr/services/dependency.py` (extend)
- `tests/test_services/test_dependency.py` (extend)

**Implementation:**

1. Add strict constructors for Node, OperationProvenance, Evidence, Edge, PathStep, CoverageRecord, and CoverageGap plus a closed relation-kind registry that assigns each kind one traversal class.
2. Edge IDs hash only intrinsic `source`, `target`, `relation_kind`, and `intrinsic_orientation`; root, traversal direction, evidence, collector, and operation are excluded. Normalization merges and stable-sorts all independently discovered evidence IDs onto that edge.
3. BFS derives root-relative direction from traversal class at traversal time. Dependency-flow reverses downstream/upstream across reciprocal roots; adjacent-structural remains adjacent in both directions. `--direction=upstream|downstream` filters traversal steps; `adjacent` expands only for `both` unless explicitly selected by internal policy.
4. Sort collectors, neighbors, paths, gaps, and evidence by stable IDs before traversal/ranking.
5. Implement the coverage-matrix completion pass from KTD-08, including `covered-empty` proof, deduplication, and prohibition on unreported applicable cells.

**Tests:**

- Table-driven reciprocal-root cases cover action↔object, query↔object, and schedule↔dataset dependency-flow relations: each keeps one edge ID and reverses upstream/downstream between roots.
- Declared link A↔B, container↔member, and canonical peer relations keep one stable edge and remain adjacent from either root and traversal order.
- Two collectors/operations that independently observe the same intrinsic relation produce one edge whose sorted `evidence_ids` contains both IDs; changing evidence alone never changes the edge ID.
- `--direction=upstream` follows only root-relative upstream steps and never filters by a stored edge label.
- An applicable cell with neither evidence nor a terminal coverage status fails the internal completeness assertion; a successful freshness-complete zero-result read is `covered-empty`, while the CAP-06 schedule index remains partial even when fully paged and empty.
- Matrix G cells create exactly one deterministic gap per node/surface/context.

---

### U3. Ontology, full-action, and query-type collectors

**Goal:** Implement branch-aware ontology discovery and correct action/query metadata traversal.

**Requirements:** R1-R5, R13-R17; AE1, AE2, AE7, AE8

**Files:**
- `src/pltr/services/dependency.py` (extend)
- `tests/test_services/test_dependency.py` (extend)

**Implementation:**

1. Object type/property/link collectors use branch-aware `ObjectType.get_full_metadata` and `get_outgoing_link_type` (CAP-01). They emit link/interface/shared-property evidence. Property-to-dataset-column and object-type-to-backing-dataset cells receive capability gaps because those mappings are not returned by these models.
2. `_get_action_index(context)` paginates top-level `client.ontologies.ActionTypeFullMetadata.list` exactly once per cache key. For each entry, visit `action_type.parameters` and every `full_logic_rules` discriminant. Resolve parameter IDs through the same action's parameter map; recurse nested function rules; index object/interface/link/property/function references. Do not create edges from `action_type.operations` or zip/index-correlate the two rule lists. Unknown rule/argument/data-type variants or generic parameter types that cannot identify a concrete target emit shape-specific gaps.
3. `_get_query_index(context)` paginates `client.ontologies.Ontology.QueryType.list` exactly once per cache key. Direct query resolution uses that cache so branch provenance remains truthful (CAP-05).
4. `_build_query_reference_closure(query, roots)` follows arrays, sets, structs, entry sets, aggregations, and every union member; constructs the reachable reference graph; computes deterministic SCCs and the fixed-point leaf/gap closure defined by KTD-05; then emits root-specific evidence using canonical witness paths. No incomplete reference or SCC is memoized across roots. Missing reachable IDs emit `invalid-response`; reachable `UnsupportedType` emits `unsupported-query-data-type`; unreachable definitions are not scanned (CAP-04).
5. Function RIDs found in full action rules are related nodes. Standalone Function metadata and reverse consumers receive the applicable matrix gap rather than a direct target path.
6. All pagination is explicit and budget-charged; do not consume a `ResourceIterator` with an unbounded `list(...)`.

**Tests:**

- Real-shaped `ActionTypeFullMetadata` fixture with shallow `.operations` empty but `full_logic_rules` containing object modification/link/function rules still yields every expected edge.
- Parameter-bound modify/delete rules resolve a concrete object/interface type through `action_type.parameters`; a generic unnamed object-type parameter produces an unresolved-reference gap. Property argument keys and nested batched function RIDs are indexed.
- Every current `ActionLogicRule` discriminant is covered by a table-driven test; an unknown future discriminant produces a gap, not a crash or silent skip.
- Two BFS collectors in the same ontology/branch call `ActionTypeFullMetadata.list` once and `QueryType.list` once; a different branch receives a different cache entry.
- Two-entry SCC fixture `A = union[object X, ref B]`, `B = union[object Y, ref A]` is used once from a parameter rooted at A and once from an output rooted at B; both roots emit X and Y, terminate, preserve distinct evidence prefixes, and do not create back-edge dependencies.
- A reachable `UnsupportedType(unsupportedType=..., params=...)` produces one `unsupported-query-data-type` gap at the exact root-prefixed field locator and prevents `covered-empty`; the same shape in an unreachable map entry produces no gap (CAP-04).
- Missing reachable `typeReference` produces `invalid-response`; an unreachable missing entry in the map produces no gap.
- Struct, entry-set key/value, array/set, interface-object, object-set, and nested-union cases all emit evidence with exact field paths.
- Cache pagination charges every request/page/item and emits a partial reverse-index gap at any global budget boundary.

---

### U4. Executable dataset/schedule/run/build/output wrappers and collectors

**Goal:** Make the pinned dataset-to-schedule-to-output path executable without breaking the existing schedules command, and expose both model omissions and the reverse index's documented staleness.

**Requirements:** R1-R5, R13-R17; AE3, AE5, AE6, AE8

**Files:**
- `src/pltr/services/dataset.py` (repair schedule RID/branch/pagination result)
- `src/pltr/services/orchestration.py` (extend structured read results)
- `src/pltr/services/dependency.py` (extend)
- `tests/test_services/test_dataset.py` (extend)
- `tests/test_services/test_orchestration.py` (extend)
- `tests/test_services/test_dependency.py` (extend)
- `tests/test_commands/test_dataset.py` (extend existing schedule-list contract coverage)

**Implementation:**

1. Add dependency-internal `DatasetService.get_schedule_rids_page(dataset_rid, *, branch_name=None, page_size=None, page_token=None, request_timeout=None) -> {schedule_rids, next_page_token}`. It performs exactly one explicit SDK page request, reads RID strings from `.data`, preserves the page token, forwards every non-`None` kwarg including timeout, and preserves SDK causes with `raise ... from e` (CAP-06, CAP-13, CAP-16).
2. Preserve `DatasetService.get_schedules(dataset_rid) -> List[Dict[str, Any]]` for `pltr dataset schedules list`. Repair its string handling by adapting returned RIDs to dictionaries containing the existing formatter keys (`schedule_rid` plus nullable display fields); do not return the dependency page envelope from this method. Keep `src/pltr/commands/dataset.py` and `format_schedules` call shapes unchanged (CAP-15).
3. Extend `OrchestrationService.get_schedule(..., request_timeout=None)` formatting to preserve structured `action.target`, `trigger`, and `scope_mode` via declared model serialization, not `str(schedule.action)`, and forward `preview=True` plus timeout for dependency reads. Recursively visit `AndTrigger.triggers` and `OrTrigger.triggers`. Emit dependency-flow references for the declared resource fields on dataset-updated, job-succeeded, new-logic, table-updated, schedule-succeeded, and media-set-updated leaves; manual/time leaves prove no resource reference. Emit adjacent-structural relations for `ProjectScope.project_rids`; `UserScope` has no project RID. A missing trigger that cannot distinguish absence from the documented permission omission is `schedule-trigger-unobservable`; malformed fields and defensive raw/future discriminators become locator-specific `invalid-schedule-trigger` or `unknown-schedule-trigger-variant:<type>` gaps rather than pinned-model evidence (CAP-07, CAP-16).
4. Add `get_schedule_affected_resources(schedule_rid, preview=None, request_timeout=None)` wrapping raw `Schedule.get_affected_resources`; extend `get_schedule_runs(..., request_timeout=None)` to expose `result.type` and submitted `result.build_rid` with page tokens (CAP-07, CAP-13, CAP-16).
5. Extend `get_build(..., request_timeout=None)`, `get_build_jobs(..., request_timeout=None)`, and job formatting to preserve only declared response fields needed by traversal: build `rid`, `schedule_rid`, `branch_name`, `job_rids`, and `status`, plus job `rid`, `build_rid`, `job_status`, and discriminated `outputs` (`dataset_rid`/`media_set_rid`). The wrapper schema has no build `target` and must not synthesize one from Pydantic-allowed extras or request-model fields. Preserve original SDK causes in every touched wrapper and assert the raw calls' exact kwargs (CAP-08, CAP-09, CAP-16).
6. The dataset collector follows the exact bounded chain `Dataset.get_schedules` → `Schedule.get/get_affected_resources` → `Schedule.runs` → submitted `build_rid` → `Build.get/jobs` → typed `Job.outputs`, creating each applicable conditional record before dispatch, operation provenance for every SDK call, and:
   - schedule target/input relations only from structured `Schedule.action.target` data;
   - recursively discovered schedule-trigger resource relations and project-scope adjacency from structured `Schedule.trigger`/`scope_mode` data;
   - affected buildable-resource relations from `get_affected_resources` without assuming every RID is a dataset;
   - schedule → run relations;
   - submitted run → build relations;
   - build → job → supported output resource relations.
7. Immediately after the first successful schedule-RID page, mark only the target's `schedule-reverse-index` record `partial` and emit exactly one `schedule-index-may-be-stale` gap with `max_lag_seconds=3600`, whether pages return zero, one, or many RIDs. Every schedule-page provenance record carries the same documented limitation. Pagination completion does not remove it; only a future CAP-backed independent freshness-complete source may do so. Returned RIDs instantiate descendant records before dispatch, and neither this partial status nor this gap can complete them (CAP-06; R19, R21).
8. Exclusively within `Schedule.action.target`, connecting `input_rids` are configured inputs and manual/upstream/connecting `target_rids` are configured targets. The `Build` response contributes no target evidence. An upstream target does not enumerate its runtime-resolved closure, so emit `dataset-resolved-upstream-lineage`; co-output uses an adjacent-structural build-membership relation, not causal flow (CAP-09).
9. Ignored/error/pending schedule runs are evidence, not invented builds. API-omitted job output kinds produce a partial `unsupported-output-kinds` gap (CAP-07, CAP-08).

**Tests:**

- `get_schedule_rids_page` receives an SDK iterator page of RID strings and returns exact values/token; its raw call asserts dataset RID, explicit or omitted branch, page size/token, and computed `request_timeout` (CAP-06, CAP-13, CAP-16).
- Existing `get_schedules(dataset_rid)` still returns a list of dictionaries accepted by `format_schedules`; a command-level `pltr dataset schedules list` regression asserts the service return is passed unchanged to the formatter and no page envelope/string reaches it (CAP-15).
- In `tests/test_services/test_orchestration.py`, construct exact pinned `Schedule`, `ScheduleRunSubmitted`, `Build`, `Job`, `DatasetJobOutput`, and `TransactionalMediaSetJobOutput` models; wrapper results preserve every declared field used by dependency collectors.
- In `tests/test_services/test_orchestration.py`, assert `"target" not in Build.model_fields` and assert the exact declared build field set/wrapper output contains no target. Because `foundry_sdk._core.ModelBase` allows extras, never use an injected extra attribute as schema evidence; no fixture or collector may smuggle it into the wrapper contract (CAP-09).
- In `tests/test_services/test_dependency.py`, one schedule action with each manual/upstream/connecting target emits correct target/input/ignored evidence without treating ignored RIDs as dependencies; no build response is consulted for those relations.
- In `tests/test_services/test_dependency.py`, a pinned nested `and` containing `or` (and the reciprocal nesting) emits evidence-backed paths with exact field locators for every dataset/job/new-logic, table, schedule, and media-set leaf. Manual/time leaves create no resource edge. `ProjectScope.project_rids` creates adjacent project relations and `UserScope` creates none.
- In `tests/test_services/test_dependency.py`, a defensive raw adapter fixture explicitly labeled as a future/non-pinned discriminator produces `unknown-schedule-trigger-variant:<type>` at the exact locator; it is not constructed or claimed as a valid SDK 1.95.0 `Trigger`. A permission-unobservable `trigger=None` produces `schedule-trigger-unobservable`, not `covered-empty`.
- Submitted run follows its exact `build_rid`; ignored/error/pending runs never trigger a build call.
- Build jobs emit supported dataset/media-set outputs and preserve output locators.
- A fully successful empty schedule page produces zero schedule edges but retains `CoverageRecord.status=partial`, one `schedule-index-may-be-stale` gap whose message says results may lag by up to one hour, and operation provenance with `max_lag_seconds=3600`; it never produces `covered-empty` (CAP-06).
- A successful non-empty, fully paged schedule index verifies returned RID evidence but retains the identical deduplicated staleness gap. Pagination and one inaccessible build do not erase successful runs/outputs; they add typed gaps.
- A returned schedule RID instantiates `schedule-detail-action`, `schedule-trigger`, `schedule-affected-resources`, and `schedule-runs` before dispatch; a submitted build RID instantiates `submitted-build`, a returned build instantiates `build-jobs`, and each job instantiates `typed-outputs`. Parameterized omissions of each collector produce that subject/surface's `collector-did-not-report` even while `schedule-reverse-index` remains partial.
- A stale-but-successful non-empty reverse index with deliberately uninvoked runs, submitted-build, build-jobs, or typed-outputs collection fails conditional completion for the exact omitted surface; neither the stale gap nor evidence from a sibling RID masks it.
- End-to-end call-order assertions prove dataset schedule RID → run → submitted build → paged jobs → outputs with exact branch/page tokens and `request_timeout=min(configured_request_timeout, remaining_time)` on every raw SDK call (CAP-06 through CAP-09, CAP-16).
- Connecting inputs/targets emit configured relations; upstream targets emit target relations plus the resolved-closure gap; co-output stays adjacent.
- Wrapper tests patch the raw pinned SDK methods with real model instances or schema-valid fixtures, not unconstrained mocks with invented attributes, and assert exact supported kwargs so branchless/non-preview calls never receive invented arguments.

---

### U5. Compass resources, application/Workshop truthfulness, and matrix enforcement

**Goal:** Resolve generic RIDs without overclaiming internal dependency coverage.

**Requirements:** R1-R5, R13-R17; AE1, AE2, AE6

**Files:**
- `src/pltr/services/dependency.py` (extend)
- `tests/test_services/test_dependency.py` (extend)

**Implementation:**

1. Resolve generic filesystem and third-party-application RIDs through `DependencyGraphService._invoke_sdk`, passing the exact generated method kwargs and remaining timeout so operation provenance is complete. Do not route dependency reads through a wrapper that cannot accept/forward `request_timeout`, and do not pass the existing `ResourceService`'s `preview=True` to generated `filesystem.Resource.get`, which is non-preview in 1.95.0 (CAP-10, CAP-16).
2. Classify known resource kinds from returned structured type metadata. Do not infer a Workshop/application subtype solely from RID/name substrings.
3. Dataset, third-party application, Workshop, and unknown-resource rows are completed against the matrix. Generic metadata is evidence of node existence only.
4. Application-internal ontology/function wiring, Workshop module/variable wiring, and unknown-type relationship surfaces always receive explicit gaps unless a future, re-audited capability replaces the cell.
5. A supplied Workshop RID that resolves is a metadata-only target with gaps. A variable/name without a resolvable supported identifier is a fatal `unsupported-addressability` error with the same coverage explanation; no fuzzy search substitutes for identity.

**Tests:**

- Dataset/application/Workshop/unknown resource fixtures map to the correct matrix row.
- Third-party application metadata does not fabricate ontology/function edges and includes the internal-wiring gap.
- Workshop RID resolution yields metadata plus all applicable gaps; a non-RID variable name fails deterministically before graph traversal.
- Unknown resource types retain generic metadata and receive `unknown-resource-capabilities` gaps.
- Permission/not-found behavior differs correctly for the root versus an adjacent resource.

---

### U6. Budgeted BFS, deterministic ranking, and change-aware assessment

**Goal:** Compose U2-U5 without duplicate scans, false direction, or silent truncation.

**Requirements:** R2-R6, R9-R17; F1, F2; AE4-AE8

**Files:**
- `src/pltr/services/dependency.py` (extend)
- `tests/test_services/test_dependency.py` (extend)

**Implementation:**

1. `analyze(target, context, direction="both", change=None)` performs sorted BFS using the shared global budget. Node/depth limits are budget dimensions, not separate silent cutoffs.
2. Collector output is normalized/deduplicated before enqueue. Per-invocation action/query caches from U3 are reused at every frontier node.
3. Run static matrix and conditional-ledger completion before finalizing results. Schedule/run/build/job transit nodes are not new direct CLI target rows, but every returned schedule/build/job RID creates the scoped conditional records defined by KTD-08 before collector dispatch. Completion validates each record independently and emits `collector-did-not-report` for any uninvoked applicable collector. Dataset roots retain the U4 reverse-index staleness partial/gap after completion, even when schedule discovery returned no RIDs, but that status cannot satisfy a descendant record (CAP-06 through CAP-09; R19, R21-R22).
4. Record one or more root paths for ranked relationships. Compact entries include related node, hop count, root-relative direction, relation kind, path node labels/IDs, and first evidence locator plus SDK namespace/method from its operation provenance.
5. Rank by directness, fixed structural severity, verified-before-partial coverage, optional change keywords, then stable edge/path ID.
6. `_assess_change` returns `ranked_impacts`, `verification_needed`, and `uncertainty`. Uncertainty includes every applicable gap intersecting the target or ranked path, plus global budget gaps; it is never suppressed because verified impacts also exist.
7. Result contains `budget.used/limits`, `read_contexts`, `evidence`, `graph`, `paths`, the complete coverage ledger and derived gaps, deterministic errors, and summary counts.

**Tests:**

- Same intrinsic graph from opposite roots yields stable edges and opposite root-relative paths.
- Depth/node/request/page/item/time exhaustion each retains partial evidence and emits the exact budget gap.
- Reverse indices are each built once across a multi-hop traversal.
- Collector ordering does not change graph, path, ranking, or gap order.
- Top compact relationship contains path and evidence locator, not merely node/kind.
- Change intent ranks direct structural dependents first and includes matrix/budget uncertainty.
- No `change` omits `change_assessment`; an empty verified graph with gaps never claims "no impact."
- A dataset with an empty successful schedule reverse-index read renders "no returned schedule RIDs; schedule index may be stale for up to one hour" and remains partial rather than claiming no schedule consumers (CAP-06).
- A stale successful non-empty reverse-index record plus an uninvoked runs/jobs/typed-outputs collector fails conditional-ledger completion with the exact subject/surface `collector-did-not-report`; sibling coverage and the ancestor partial do not mask it.

---

### U7. Six-command CLI, branch/budget controls, and structured failures

**Goal:** Expose the six verified direct target kinds through thin Typer commands.

**Requirements:** R1, R6-R7, R10, R13, R16-R17; F1, F2

**Files:**
- `src/pltr/commands/dependency.py` (new)
- `src/pltr/cli.py` (register sub-app)
- `tests/test_commands/test_dependency.py` (new)

**Commands:**

- `object-type ONTOLOGY_RID OBJECT_TYPE`
- `property ONTOLOGY_RID OBJECT_TYPE PROPERTY`
- `link-type ONTOLOGY_RID OBJECT_TYPE LINK_TYPE`
- `action-type ONTOLOGY_RID ACTION_TYPE`
- `query-type ONTOLOGY_RID QUERY_TYPE`
- `resource RESOURCE_RID`

All commands accept `--branch` as requested read context; requested branch is stored in `ReadContext`, while each operation records an exact `explicit`, `server-default`, or `not-applicable` branch argument. Preview uses the same enum and records its exact boolean value when explicit; `unsupported` is never an argument state. Shared options: `--profile`, `--format table|json|csv`, `--output`, `--graph-output`, `--change`, `--direction`, `--depth`, `--max-nodes`, `--max-requests`, `--max-pages`, `--max-items`, `--time-budget-seconds`, and `--full` (CAP-16; R13-R14).

The shared runner creates one `AnalysisContext`, resolves once, analyzes once, writes the artifact once (U8), and then renders. It catches authentication setup errors separately and renders dependency fatal errors by stable `error_class`; no generic exception is mislabeled as a coverage result.

**Tests:**

- Each command passes exact identifiers, branch support, change, direction, and budget values to one service invocation.
- No `function`, `schedule`, or `workshop-variable` command is advertised; Workshop names without a Compass RID are rejected by `resource` validation.
- Values over every hard budget ceiling fail before service construction/network access.
- Fatal error classes render stable machine-readable JSON and concise table errors with exit code 1 and no traceback.
- A partial graph with gaps exits 0 and clearly reports partial coverage.
- CLI serialization preserves every operation-provenance record and never substitutes the requested branch for a branchless call's `not-applicable` value.
- `--output`, `--format`, and `--full` do not cause a second `analyze` call.

---

### U8. Same-invocation artifact and layered rendering

**Goal:** Preserve the complete graph and make compact output independently useful.

**Requirements:** R3, R6-R9; AE5, AE9

**Files:**
- `src/pltr/utils/dependency_artifacts.py` (new)
- `src/pltr/utils/formatting.py` (extend)
- `tests/test_utils/test_dependency_artifacts.py` (new)
- `tests/test_commands/test_dependency.py` (extend)

**Implementation:**

1. Canonically serialize the complete result (sorted keys and stable list ordering), calculate SHA-256 and `analysis_id`, write to a temporary sibling, `fsync`, chmod `0600`, and atomically replace the final artifact.
2. Resolve default state path via `XDG_STATE_HOME` or `~/.local/state`; create only the feature-specific directory. `--graph-output` overrides that path; `--output` remains independent.
3. Add `artifact: {analysis_id, path, sha256, created_at}` to the rendered result without hashing the self-referential path metadata; define and test the exact digest boundary. The hashed complete result includes immutable operation provenance, so SDK version/arguments/limitations affect the digest.
4. Compact table prints target/read context, deterministic assessment, top relationship path/evidence, gap summary by reason code, budget use, and artifact reference.
5. JSON contains complete nodes, edges, paths, evidence, coverage records, gaps, errors, operation provenance, budgets, and artifact metadata. CSV uses explicit row kinds (`node`, `edge`, `path`, `coverage`, `gap`, `error`, `evidence`, `operation-provenance`) rather than flattening only the summary.
6. `--full` expands table rendering only. It never controls discovery or artifact completeness.

**Tests:**

- Artifact content matches the graph returned by the same mocked service call; service analyze call count remains one.
- Default and `--graph-output` paths are exact; `--output` does not replace them; artifact permissions are `0600`; replacement is atomic.
- SHA-256/analysis ID are stable for identical canonical content and change when graph/provenance changes.
- Write failure exits before compact output and reports `artifact-write-failed`.
- Compact output contains a top path, evidence locator and SDK namespace/method, absolute artifact path, digest, gap count, and budget summary.
- JSON/CSV contain the full graph/coverage/errors/provenance rather than top-N only.
- Exact-schema artifact tests cover preview full-metadata, explicit/default branch, and branchless/non-preview operations; every evidence `operation_provenance_id` resolves, every operation has valid `capability_ids`, all enum values match the documented schema, and the installed invocation SDK version is present.
- Compact/JSON/CSV render a dataset's `schedule-index-may-be-stale` partial gap and one-hour message even when the successful reverse-index result is empty (CAP-06).

---

### U9. Documentation

**Goal:** Document addressability, flags, artifacts, and truthful coverage.

**Requirements:** R1, R6-R9, R13-R17

**Files:**
- `docs/user-guide/commands.md`
- `claude_skill/reference/dependency-commands.md` (new)
- `claude_skill/SKILL.md`
- `README.md`

Document all six commands, per-operation branch/preview/SDK provenance, global budgets, graph-output path/retention, dependency-flow versus adjacent-structural traversal, deterministic error classes, and the coverage matrix legend. Dataset examples must say that returned schedule RIDs are verified but the reverse index may lag by up to one hour, so empty success is partial rather than proof of no consumers. Examples must show the graph reference and must not claim Workshop internals, standalone Function reverse wiring, dynamically resolved upstream lineage, or application wiring are discoverable (CAP-06, CAP-16).

**Tests:** none; proofread Markdown and compare documented `--help` against U7 after implementation.

---

## Implementation Sequence and Verification Gates

1. U1 typed context/error/budget primitives.
2. U2 graph orientation/path/matrix primitives.
3. U3 full action/query collectors and one-time reverse indexes.
4. U4 compatible dataset page seam, orchestration wrapper repairs, timeout propagation, command regression, and freshness-limited schedule traversal.
5. U5 Compass/resource coverage completion.
6. U6 traversal/ranking/change assessment.
7. U7 CLI.
8. U8 artifact/rendering.
9. U9 docs.

Before implementation is considered complete, run focused unit tests after each unit, then the repository's lint/typecheck/test/static-analysis commands. This planning revision itself does not run tests or modify feature code.

---

## Risks and Mitigations

- **Preview/full-metadata drift:** action/object full metadata is preview. Unknown shapes and unavailable preview calls become capability gaps; CAP assumptions are re-audited on SDK upgrades.
- **Large ontologies:** global request/page/item/time budgets and once-per-context indices prevent unbounded scans and N× rescans.
- **Branch/preview ambiguity:** requested branch stays separate; every operation records explicit/server-default/not-applicable plus exact values, and branchless/non-preview reads never inherit arguments from another surface (CAP-16).
- **Partial permissions:** typed per-operation gaps preserve independent evidence; root failures remain fatal.
- **Artifact sensitivity:** artifacts contain metadata/evidence but no credentials/raw bodies, use `0600`, and are stored locally. Documentation states retention is operator-managed.
- **Dataset false completeness:** returned schedule RIDs, schedule-action targets/inputs, trigger/scope references, and outputs are verified evidence, but `schedule-index-may-be-stale` remains partial only on the schedule reverse-index record for every success—including empty success. Each returned RID's detail/action, trigger, affected-resource, runs, submitted-build, jobs, and typed-output records terminate independently; runtime-resolved upstream closure, API-omitted output kinds, physical-lineage gaps, and uninvoked collectors remain separate (CAP-06 through CAP-09).
- **Existing schedules command regression:** the dependency collector uses a separate page-oriented RID method; `DatasetService.get_schedules` retains dictionaries for the existing command/formatter and has a command-level regression (CAP-15).
- **Recursive query under-closure:** SCC/fixed-point closure is finalized before cross-root reuse, and dual-entry mutual-recursion tests prove both roots receive all leaves (CAP-04).
- **Loose mocks:** wrapper tests use schema-valid pinned-model shapes and assert actual generated method signatures/kwargs for corrected seams.

---

## Scope Boundaries

### Included

- Read-only dependency discovery for the six addressable command kinds.
- Full action rule/parameter metadata, reachable query type metadata, branch-aware reverse indices, and direct schedule/run/build/supported-output traversal.
- Explicit gaps for stale dataset schedule reverse indexing, unresolved dataset lineage/output omissions, reachable unsupported query types, Workshop/application internals, standalone Function consumers/bodies, permissions, unsupported shapes, and budgets.
- Deterministic change-aware assessment, provenance, evidence paths, and same-invocation local artifacts.

### Deferred

- Mutation, approval, remediation, or automatic execution.
- A standalone graph UI or server-side graph store.
- Workshop module/variable enumeration without a supported identifier/API.
- Direct standalone Function targets and arbitrary function implementation/body analysis.
- Direct schedule targets; schedules remain traversed from dataset schedule RIDs.
- Application-internal ontology/function wiring until an authenticated, pinned SDK surface exposes it.
- Changes to the external `palantir-mcp` npx package invoked by `src/pltr/commands/mcp.py`.

---

## Open Questions

- Retention/cleanup policy for `${XDG_STATE_HOME:-~/.local/state}/pltr/dependency` artifacts is operator-managed in this feature; a future maintenance command may add pruning.
- Default budget values are implementation defaults, not completeness guarantees. Changing them requires keeping the hard ceilings, budget accounting, and gap behavior intact.
- `CHANGELOG.md` remains outside U9 because it is stale relative to `pyproject.toml`; release preparation should decide whether to revive it separately.

---

## Sources / Research

- `docs/brainstorms/2026-07-17-foundry-dependency-analysis-requirements.md`
- `pyproject.toml`; `uv.lock`
- `src/pltr/services/base.py`
- `src/pltr/services/ontology.py`
- `src/pltr/services/functions.py`
- `src/pltr/services/dataset.py`
- `src/pltr/services/orchestration.py`
- `src/pltr/services/resource.py`
- `src/pltr/services/third_party_applications.py`
- `src/pltr/commands/ontology.py`
- `src/pltr/commands/functions.py`
- `src/pltr/commands/orchestration.py`
- `src/pltr/commands/resource.py`
- `src/pltr/utils/formatting.py`
- `src/pltr/utils/completion.py`
- `tests/test_services/test_dataset.py`
- `tests/test_services/test_orchestration.py`
- `tests/test_commands/test_dataset.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/action_type_full_metadata.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/action_type.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/query_type.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/object_type.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/ontologies/models.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/core/models.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/functions/query.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/functions/models.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/schedule.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/build.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/orchestration/models.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/datasets/dataset.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/filesystem/resource.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/v2/third_party_applications/third_party_application.py`
- `.venv/lib/python3.11/site-packages/foundry_sdk/_errors/__init__.py`
