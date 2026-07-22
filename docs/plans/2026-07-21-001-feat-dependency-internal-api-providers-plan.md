---
date: 2026-07-21
status: active
origin: docs/brainstorms/2026-07-17-foundry-dependency-analysis-requirements.md
prior_plan: docs/plans/2026-07-17-001-feat-foundry-dependency-analysis-plan.md
topic: foundry-dependency-analysis-internal-api-providers
target_repo: pltr-cli
---

# feat: Full-Lifecycle Dependency Analysis via Internal-API Providers

## Summary

Extend the existing read-only `pltr dependency` feature so it performs full-lifecycle,
reverse-direction change-impact analysis — code line → transform → dataset → property/column →
object type → actions / functions / Workshop modules / applications — using Foundry's
undocumented INTERNAL APIs for the edges the public `foundry-platform-sdk` cannot see.

The public SDK is forward-declarative: a resource can name what it depends on, but nothing in
the package answers "what depends on *me*." This plan **generalizes the current SDK-only
dispatch** (`_invoke_sdk` + `SDK_OPERATION_SPECS`) into a **provider interface** with three
transports — the existing **SDK**, a new **Conjure-REST** transport, and a new
**GraphQL-over-SSE** transport — all feeding the *same* existing evidence / operation-provenance
/ coverage-record / coverage-gap / node / `_add_edge` machinery. That machinery already models
"unsupported surface → coverage gap," which is exactly the degradation mode we need for
undocumented-API drift.

Scope is a **single end-to-end vertical slice**: `code → transform → dataset → property →
object-type → apps`. It proves the provider architecture on real value before fanning out to the
other six reverse surfaces. The slice **augments, never replaces**: the public SDK path stays
authoritative for what it does cleanly (object-type structure, links, action types) and the new
public `includeDatasources` property→column mapping; internal APIs supply the reverse edges the
SDK cannot. Internal wins on overlap; public stays for stable structure.

Enforcement/gating remains **out of scope** (a separate agent harness owns it). The other reverse
surfaces (function-registry `usageHistory`, data-health, broader ontology-metadata reverse
indexes, full monocle V3 link taxonomy) are **explicit follow-ups**. Monocle **V2 is not
targeted** — V3 only.

---

## Adversarial Review — Binding Resolutions (2026-07-21)

A `cto` adversarial pass read the plan against the live `dependency.py`. Verdict:
**ready-with-P0-fixes.** These resolutions are binding and are reflected in the units/KTDs below;
where a resolution changes what gets built it is edited in place, and this list is the index.

**P0-1 — U1 seam is not a uniform signature.** `_invoke_sdk` (`dependency.py:1322`) takes a bound
SDK `call: Callable` that the uniform `invoke(...)` protocol lacks, and `OperationProvenance`
(`:208`) is a *frozen, SDK-shaped* required-field dataclass asserted field-by-field in
`test_dependency_sdk_contract.py:153-188`. Resolution: `Provider.invoke` is a **Union of
transport-specific signatures**, not one uniform signature — `SdkProvider` keeps `call`;
`_invoke_sdk` stays a byte-identical delegator so the direct-call contract test stays green.
`OperationProvenance` gains a **required `transport` field**; internal-op fields are `Optional`
with defaults **appended after** the existing positional fields so `:1361/:1388` construction and
the contract test are unaffected. (Edited in KTD-P2, U1, Extended-contracts block.)

**P0-2 — token expiry must be loud, not laundered.** The token is a short-lived user session
token. Caching it at client construction (original U2) means mid-run expiry `401`s every internal
call, which the original mapping folds into `inaccessible`/`inconclusive` and exits 0 — the one
signal that must be loud (re-auth) made silent. Resolution: fetch the token **per request** (as
`base.py:99` does); `401`/expired is a **distinct `token-expired` class** that surfaces
prominently and is never folded into `inconclusive`/`inaccessible`; the positive control fires on
the **first** internal call and a canary `401` aborts internal providers loudly. (Edited in
KTD-P2, U2.)

**P0-3 — the object→link merge as written is impossible.** `_add_edge` derives `edge_id` from
`(source,target,relation_kind,orientation)` and *raises* on a same-id/different-traversal-class
collision (`:1581`). A new `dependency-flow` `object-consumed-by-link` kind therefore cannot merge
with the existing `adjacent-structural` `declared-link` edge. Resolution: **drop
`object-consumed-by-link`**; the GraphQL link-type dependent rides the existing `declared-link`
intrinsic edge, contributing its internal evidence id through the normal evidence-union. The
"merge onto one edge id" language is corrected to this. (Edited in KTD-P5, U3, U6, new-kinds list.)

**P0-4 — the one sanctioned `covered-empty` needs a read-time discriminator.** ACP-01 `{}` may be
`covered-empty` **only** when, in the same run, (i) the ACP-01 positive control passed AND (ii)
dataset existence/accessibility is independently confirmed via a successful Compass GET (ACP-08);
otherwise `inconclusive`. It carries a distinct `reason_code: authoritative-empty-no-producer`
plus `positive_control_status=passed` + `existence_confirmed=true` in the artifact so a gate can
trust it. Enforced at the `_finish_coverage` chokepoint (P1-2), not by grep. (Edited in U5, U9.)

**P1-2 — enforce false-safety at a chokepoint, not by source-grep.** The U9 grep is brittle
theater (cannot scope out the legitimate SDK `covered-empty` at `:2152`, misses indirect writes).
Resolution: extend `_finish_coverage` (`:1624`) — if the record's op is internal
(`empty_is_inconclusive` / `transport != "sdk"`), **reject `covered-empty`** (raise), except the
P0-4 guarded ACP-01 path. Back it with per-ACP behavioral fixtures. (Edited in U9.)

**P1-3 — re-cut the slice; it is sequenced horizontally.** No CLI-visible internal edge appears
until U8 because U1+U2(full SSE/Conjure)+U3(all kinds)+all four collectors must land first.
Resolution: **Phase A** drives the cheapest real edge end-to-end — property→column via the public
`includeDatasources` GET (no SSE, no Conjure error taxonomy, no build2/stemma/AST): U1 → U2a
(GET-only Conjure client + `ResultSemantics`) → U3a (just `column-backs-property` + the
`inconclusive` status) → U4 → U8a (`--no-internal` + the property path, one edge + gap rendered).
**Phase B** adds the SSE/GraphQL client, build2, stemma/AST, and the remaining collectors. (Edited
in Implementation Sequence.)

**P1-1 — keep `inconclusive` but audit the ripple.** The model already uses `partial` for
"empty-success-can't-prove-absence" (`test_dependency.py:889`). A distinct `inconclusive` is kept
because a `200 []` with **zero** edges is a poor fit for `partial` (which implies *some* data) and
because a safety status must read unmistakably as "could not prove absence," not staleness.
**Binding:** U3 must include a ripple audit sweeping every closed-vocabulary consumer
(`_finish_coverage` set `:1633`, `_complete_coverage` `:1722`, matrix-completion tests `:1213/1388/1551`,
rendering severity) before the status is added.

**Other binding amendments:** **P1-5** U2 uses a proper SSE frame parser (split on `\n\n`,
concatenate multi-line `data:` within a frame, ignore `:`-comments/keep-alives; any unfilled
`requestIndex` → `inconclusive`, never dropped). **P1-6** U5's AST parse is scoped to
string-literal `Input`/`Output` in `transforms.api`-style decorators; aliased imports, computed
paths, multi-output, and non-Python repos degrade to `unresolved` with a locator (test each).
**P1-7** internal providers get a **separate budget bucket** so internal fan-out (per-dependent
Compass GETs, per-app TPAS calls) cannot starve the authoritative SDK surfaces into
`budget-exhausted`; test that SDK surfaces still complete when the internal budget is exhausted.
**P1-8** ACP-05 pins the observed dependents page-boundary constant; `result_count == boundary`
is always `inconclusive` (a full-boundary page is structurally unprovable). **P1-9** verify from
the reference that ACP-07's `PUT .../entity-sdk-versions` is idempotent read-with-body before the
canary uses it; state it in the ACP entry; keep the canary config-gated. **P2-1** collapse
`contract-version-drift` into `response-shape-drift` (the `mcp` pin is a recorded string with no
runtime comparand; the real signal is the shape descriptor + canary).

---

## Decisions Already Made (design to these; do not re-litigate)

1. **Provider abstraction, reuse the graph model.** Generalize `_invoke_sdk` /
   `SDK_OPERATION_SPECS` into a `Provider` interface with at least three providers (SDK,
   Conjure-REST, GraphQL-SSE). All providers feed the same evidence + coverage-record +
   coverage-gap + node/edge machinery. Undocumented-API drift degrades to a coverage gap through
   that existing machinery, not a crash.
2. **Vertical slice first.** Build ONE end-to-end path, not all seven surfaces. The others are
   deferred.
3. **Augment, do not replace.** Keep the public SDK where it is the correct/stable source (object
   types, links, action types, and the PUBLIC `includeDatasources` property→column mapping). Use
   internal APIs for the reverse edges the SDK cannot see. Internal wins on overlap.

---

## Non-Negotiable Design Principles (baked into units + tests)

- **These APIs fail toward false safety.** `empty` or `truncated` results map to coverage status
  `inconclusive`, NEVER `covered-empty`/`safe`. Every internal endpoint carries a **positive
  control** (a canary that proves the request shape still resolves real data). Specific traps to
  encode: `ontology-metadata` silently ignores unknown request fields (a typo returns `200`
  empty); `objectTypeV2.dependents` has **no page argument and truncates silently** (treat a
  non-null `nextPageToken`, or any result at/above the first-page boundary, as `inconclusive`)
  while `actionType.dependents` paginates; `monocle --direction downstream` drops `adjacent`
  links; build2 walks require `branchFallbacks` (its absence yields `400`, not an
  authoritative-empty); Compass import reads return empty on permission denial (ambiguous →
  `inconclusive`).
- **Pin + shape-check + degrade loudly.** Pin the `@palantir/mcp` contract version the shapes were
  derived from (**v0.397.0**) plus the live-verification date (**2026-07-21**). On response-shape
  mismatch emit a coverage gap (`response-shape-drift`); do not crash and do not silently drop.
- **GraphQL SSE events arrive OUT OF ORDER.** Demux on `extensions.requestIndex`; never rely on
  arrival order.
- **Reuse per-edge `Evidence` + operation provenance.** Each new provider records provenance
  analogous to the CAP-backed SDK specs (namespace/method/version/timestamp) via an **ACP (API
  Contract Pin) ledger**. Extend `RELATION_KINDS` for the new edges rather than bypassing
  `_add_edge`.
- **Stay upstream-mergeable.** This is a fork (`origin=zaycruz`, `raava=raava-solutions`,
  `upstream=anjor`). Avoid gratuitous divergence that would make future upstream merges painful:
  additive `RELATION_KINDS`/node kinds/coverage surfaces, provider seam behind the existing
  service, no rename of public method contracts.

---

## Execution Posture

- **The false-safety tests are written test-first** as characterization of the "must not report
  safe" invariant: empty-vs-inconclusive, silent truncation, response-shape drift → gap, SSE
  out-of-order, `branchFallbacks`-missing → non-authoritative, permission→empty → ambiguous. These
  are the highest-value tests in the plan; they are authored in U2 and U9 before the collectors
  they guard exist, and the collectors are implemented to make them pass.
- Every other unit follows the repo's existing test-alongside discipline (see the prior plan's
  per-unit test blocks).

---

## Ledger: CAP corrections + new ACP entries

### CAP ledger corrections (from the internal-API sweep)

| ID | Prior claim (in `2026-07-17-001` plan) | Correction | Evidence |
|---|---|---|---|
| **CAP-14** | `PropertyV2` exposes no backing dataset/column; property→column is an **unsupported** matrix cell. | **RETIRED.** The public `GET /api/v2/ontologies/{ont}/objectTypes/{apiName}?includeDatasources=true&preview=true` returns `datasources[].definition.propertyMapping` — per-property physical column (`programId → program_id`, not derivable by convention; must be read). This cell becomes **covered** via the REST provider. | `reverse-indexes.md` §4 (live-verified 2026-07-21) |
| **CAP-10** | No SDK surface exposes Workshop module/variable wiring or third-party-application internal ontology/function wiring; those cells always gap. | **PARTIALLY RETIRED.** The **reverse** direction (object-type → consuming Workshop modules and applications) IS observable: GraphQL `objectTypeV2.dependents` (Workshop modules, link types) + TPAS `scopes.dataScope` + OSDK `entity-sdk-versions`. **Workshop *variables* remain NOT readable** (`Route:RouteNotMounted`) — that gap stands. | `graphql-gateway.md` §9.1; `application-layer.md`; `reverse-indexes.md` |
| **CAP-06** | Dataset→schedule reverse index is one-hour stale (partial). | **STANDS**, but is no longer the only lineage source. build2 `upstream/downstream-jobspecs` and `jobspecs/datasets/{rid}` give transform-plane lineage the schedule index never had. This is **additive**; the `schedule-index-may-be-stale` partial gap remains on the schedule surface and is not satisfied by build2 evidence. | `lineage-monocle-build2.md` |
| **CAP-16** | Per-operation branch/preview argument + `request_timeout` provenance for SDK methods. | **EXTENDED** to transport-tagged provenance: Conjure ops record HTTP verb + path template + request-shape descriptor; GraphQL ops record operation name + document hash + `variables`; both record the contract pin (`mcp@0.397.0`) and live-verification date. `request_timeout` continues to be forwarded on every call. | this plan, U1/U2/U3 |

### ACP ledger (new — one entry per internal endpoint the slice uses)

Each ACP is the *only* authority for an internal-API operation. It records: endpoint, verb,
request-shape descriptor, response discriminator, **positive control**, the **false-safety trap**,
and the contract pin (`mcp@0.397.0` + live-verified 2026-07-21). No internal operation may be
added to a provider without an ACP entry (mirrors the CAP discipline; enforced by the U9
registry-completeness test).

| ID | Operation | Endpoint (verb) | Positive control / false-safety trap |
|---|---|---|---|
| **ACP-01** | build2 producing job specs for a dataset | `GET /build2/api/jobspecs/datasets/{datasetRid}` | Returns job specs **keyed by branch**; `{}` = "not built by a transform" (a real answer). Trap: none for this GET, but graph walks need `branchFallbacks`. |
| **ACP-02** | build2 downstream/upstream/connecting walks | `POST /build2/api/jobspecs/branches/{branch}/{downstream,upstream,connecting}-jobspecs` | `branchFallbacks` (a **map**, `{"branches":[]}`) is **required**; its absence → `400 InvalidArgument`, which is **not** authoritative-empty → `inconclusive`. Positive control: `d9069f13` downstream depth 1 → 1 job spec. Filter to `inputType/outputType == "foundry"`. |
| **ACP-03** | stemma source + blame | `GET /stemma/api/repos/{rid}/paths/contents/{path}` (base64 `fileContents`) + `/blame/{path}` (`blameRows`) | Positive control: a known repo path returns non-empty base64. Local Python AST parse of `@transform(Input(...),Output(...))`; output paths → RIDs via `GET /compass/api/resources?path=<url-encoded>`. |
| **ACP-04** | property → dataset column (PUBLIC) | `GET /api/v2/ontologies/{ont}/objectTypes/{apiName}?includeDatasources=true&preview=true` | `datasources[].definition.propertyMapping` keyed by property apiName. Retires CAP-14. Empty `datasources` → `inconclusive`, not "no backing." |
| **ACP-05** | object type → consumers (GraphQL) | `POST /graphql-gateway/api/bulk`, op `GetObjectTypeDependents` | SSE; demux on `extensions.requestIndex`. `dependents` has **no page arg**; non-null `nextPageToken` ⇒ `inconclusive` (silent truncation). SELECT `rid name description path type parent projectRid` on `ResourceMetadata`; **never** rely on `_id` (Relay cache key). Positive control: `1ca5ae2e` → 11 dependents. |
| **ACP-06** | object type → consumers (corroborating) | `POST /monocle/api/links/graphV3` (+ `hierarchyV3`) with `BranchSpec` tagged union | Target **V3** (V2 is dead client code). One hop only; a RID monocle does not index is **silently dropped** (no node). `downstream` direction drops `adjacent` links → never "safe." Decode link unions defensively (3/9 variants never observed). |
| **ACP-07** | which apps actually break | `PUT /third-party-application-service/api/application-sdks/{appRid}/entity-sdk-versions` (body `{"entityRids":[…]}`); `GET /applications`, `/applications/{rid}` | **Verb is PUT but the Conjure method is `bulkGetEntitySdkVersions` — a read-with-body, NON-mutating (P1-9, verified in `application-layer.md`).** Per-object-type `{oldest,latest}` generated-OSDK range. App on an OSDK older than a property rename breaks differently than a live one; `listSdks: []` ⇒ breaks live, not via stale bundle. Positive control (config-gated): known app → non-empty `sdkVersions`. |
| **ACP-08** | universal consumer namer | `GET /compass/api/resources/{rid}?decoration=path` | Names ANY bare consumer RID (workshop module, notepad, app, dataset): `name`, `path`, `inTrash`/`directlyTrashed`. Trap: batch endpoint shape unverified — use single GET. |

**Deferred ACP surfaces (documented, NOT wired in this slice):** function-registry
`usageHistory` (execution telemetry, absence ≠ no dependency, nanosecond timestamps truncate to
µs), `ontology-metadata` reverse indexes beyond what the slice needs (unknown-field-ignored trap),
`branch-service` dependency-graph (response payload unverified), build2 `-nodes` endpoints and
`jobspecs/events` (service-root permission — not usable from a user token), data-health.

---

## Requirements Traceability

Traces to `docs/brainstorms/2026-07-17-foundry-dependency-analysis-requirements.md`. This slice
strengthens reverse-direction coverage while preserving the prior plan's evidence/coverage
discipline.

| Requirement / decision | Planned coverage |
|---|---|
| R2 downstream consumers & effects | U5 (object→consumers), U4 (transform/dataset), U3 (property→column) now truly observable, not gapped |
| R3 participants/orientation/class/path/evidence | U1 provider provenance; U3 new `RELATION_KINDS`; edges emitted through `_add_edge` unchanged |
| R4 verified-empty vs incomplete/stale/inaccessible | U2 false-safety primitives (empty/truncated → `inconclusive`); U9 characterization suite |
| R5 target-kind × surface enforcement | U3 new coverage surfaces; U9 completion assertion + registry-completeness |
| R12 uncertainty never suppressed by non-empty result | U2 truncation/permission → `inconclusive` folded into change uncertainty; U8 rendering |
| R13–R14 immutable operation provenance | U1 transport-tagged provenance; ACP ledger analog to CAP; U9 provenance-resolves test |
| R17 deterministic failure classes | U2 Conjure/GraphQL/SSE error taxonomy extends `classify_exception` |
| "one canonical dependency model" | All providers write one `AnalysisContext`; internal-wins-on-overlap merge in U3 |
| "coverage is evidence-backed & mechanically enforced" | U2 positive controls; U9 registry-completeness gate |
| "assessment, not action" (still holds) | Enforcement/gating OUT of scope; read-only transports only |

---

## Key Technical Decisions

**KTD-P1 — Provider seam is a pure refactor first.** Introduce a `Provider` protocol and a
`transport`-tagged `OperationSpec` superset of the frozen `SDKOperationSpec` (`src/pltr/services/
dependency.py:79`). `_invoke_sdk` (`:1322`) becomes the `SdkProvider.invoke` implementation with
**byte-identical behavior** (same budget charge, same `request_timeout` forwarding, same
`OperationProvenance` construction, same fatal/non-fatal semantics). No collector changes in the
seam unit; every existing test must pass untouched. This keeps upstream merge pain minimal.

**KTD-P2 — One internal transport client, two transports, reusing auth.** Add
`FoundryInternalClient` that retrieves `host`/`token` **per request** (like
`BaseService._make_request`, `src/pltr/services/base.py:99`, which re-reads the credential each
call) — NOT cached at construction, so a token refreshed mid-run is picked up and an expired one
is detected — via `CredentialStorage().get_profile(profile)`. It does **not** call
`raise_for_status()` (the intentional Conjure `400`/`422` oracle responses and `200`-empty
semantics must be inspected, not raised). **`401`/token-expired is a distinct loud class**
(`token-expired`), never folded into `inaccessible`/`inconclusive`; a canary `401` on the first
internal call aborts internal providers with a visible re-auth banner rather than emitting an
all-`inconclusive` graph (P0-2). It exposes `conjure(verb, path, body)` and
`graphql(operation_name, document, variables_list)`. The GraphQL method builds the batched
persisted-operation envelope, reads the SSE body with a **proper frame parser** (split on `\n\n`,
concatenate multi-line `data:` fields within a frame, skip `:`-comments/keep-alives), and
**demuxes on `extensions.requestIndex`** into a result array of `len(requests)` — any index left
unfilled → `inconclusive`, never silently dropped (P1-5). `requests` uses the standard headers
incl. `fetch-user-agent: hubble/6.525.9 forge-graphql-client/0.0.0`. Internal providers charge a
**separate budget bucket** from the SDK path so internal fan-out cannot exhaust the authoritative
SDK budget (P1-7).

**KTD-P3 — False safety is a first-class result classifier, not per-collector logic.** A
`ResultSemantics` helper takes `(OperationSpec, response)` and returns one of
`ok | empty | truncated | shape-drift | permission-ambiguous`. `empty`/`truncated`/
`permission-ambiguous` map to coverage status **`inconclusive`** (a status already expressible as
a non-`covered`/`covered-empty` gap; introduce `inconclusive` as an explicit coverage/gap reason
so it renders distinctly from `partial`). `shape-drift` emits `response-shape-drift`. Each
`OperationSpec` carries a `positive_control` callable; a run may (config-gated) fire the canary to
distinguish "endpoint drifted" from "genuinely no data." **No collector is allowed to write
`covered-empty` from an internal-provider response** — enforced by a U9 test that greps the
provider result path.

**KTD-P4 — Contract pinning + shape descriptors.** Each `OperationSpec` for an internal op names
its ACP id, the `@palantir/mcp` pin (`0.397.0`), the live-verification date (`2026-07-21`), and a
minimal **shape descriptor** (required keys / discriminator fields for the response). Shape-check
validates the descriptor, not the whole payload (Conjure services add fields — e.g.
`totalActionTypeCount` absent from the shipped `.d.ts`; parse permissively). A missing required
discriminator ⇒ `response-shape-drift` gap; extra fields are ignored.

**KTD-P5 — Internal wins on overlap; public stays for structure.** Edge merge policy in `_add_edge`
is unchanged (evidence unions onto one edge id). Merge only happens when two providers observe the
**same intrinsic relation** — i.e. the same `(source, target, relation_kind, orientation)`, since
`_add_edge` (`:1577`) derives `edge_id` from exactly those and *raises* on a same-id collision with
a different traversal class (`:1581`). The GraphQL link-type dependent (P0-3) is therefore emitted
under the **existing `declared-link` intrinsic edge**, contributing its internal evidence id via
the normal union — it does NOT introduce a separate `dependency-flow` link kind (that would be a
different `edge_id` and could never merge). Where only internal can see a genuinely new reverse
edge (object→app/workshop, transform→dataset, column→property), internal is the sole evidence.
Object-type structure, links, and action types continue to come from the SDK collectors already in
the file.

**KTD-P6 — New relation/node kinds are additive.** Extend `RELATION_KINDS` (`:541`) and the node
kinds with the slice edges (below). Emit every new edge through `_add_edge` (`:1563`) so the
conflicting-orientation guard and evidence-merge invariant continue to hold. Code *lines* are
carried as **evidence locators** (blame row + AST span) on the `repo-builds-dataset` edge, not as
separate nodes, to avoid node-count explosion.

**KTD-P7 — Providers are opt-in per invocation, degrade loudly.** New CLI flags gate internal
providers (default on for the slice target kinds, with `--no-internal` to fall back to SDK-only).
When an internal provider is unreachable (route not mounted, permission, drift), its surface
records an `inconclusive`/`inaccessible` gap and the SDK-derived graph still returns — never a
hard failure of the whole command.

---

## High-Level Technical Design

### Provider abstraction

```text
                         ┌─────────────────────────────────────────────┐
                         │            DependencyGraphService            │
                         │   analyze() · collectors · _add_edge() ...   │
                         └───────────────┬─────────────────────────────┘
                                         │ invoke(op, params, target, fatal, limitations)
                         ┌───────────────▼───────────────┐
                         │        Provider (protocol)      │
                         │  transport, invoke() -> Result  │
                         └──┬───────────────┬───────────┬──┘
        ┌───────────────────┘               │           └────────────────────┐
┌───────▼────────┐              ┌───────────▼──────────┐         ┌────────────▼───────────┐
│  SdkProvider   │              │  ConjureRestProvider │         │   GraphQlSseProvider   │
│ (== _invoke_sdk│              │  GET/POST/PUT + path  │         │ /graphql-gateway/bulk  │
│  behavior)     │              │  Conjure err taxonomy │         │ SSE demux by           │
│ SDK_OPERATION_ │              │  400/422/403/200-empty│         │ extensions.requestIndex│
│   SPECS        │              │  ACP-01/02/03/04/07/08│         │  ACP-05                │
└───────┬────────┘              └───────────┬──────────┘         └────────────┬───────────┘
        │                                   │                                 │
        │        ProviderResult{ payload, operation_provenance_id,            │
        │          result_semantics: ok|empty|truncated|shape-drift|perm,     │
        │          positive_control_status }                                  │
        └───────────────────────────────────┴─────────────────────────────────┘
                                         │  ONE shared model
                         ┌───────────────▼───────────────────────────────┐
                         │  AnalysisContext: operation_provenance ·        │
                         │  evidence · nodes · edges(_add_edge) ·          │
                         │  coverage_records · gaps · DiscoveryBudget      │
                         └─────────────────────────────────────────────────┘
```

Every provider produces a `ProviderResult` and writes evidence/edges/coverage into the same
`AnalysisContext`. `FoundryInternalClient` is the single HTTP surface behind
`ConjureRestProvider` and `GraphQlSseProvider`; monocle graphV3 (ACP-06) is a Conjure-REST op.

### Extended contracts (additive to the prior plan's Graph/Evidence/Provenance section)

```text
OperationSpec (superset of SDKOperationSpec)
  transport: "sdk" | "conjure-rest" | "graphql-sse"
  capability_ids: (CAP-*, ...)         # sdk ops (unchanged)
  contract_pins:  (ACP-*, ...)         # internal ops; each ACP -> {mcp_version, verified_on}
  # sdk:        namespace, method, branch: bool, preview: bool           (unchanged)
  # conjure:    http_verb, path_template, request_shape, response_shape  descriptors
  # graphql:    operation_name, document_sha256, response_shape descriptor
  positive_control: Callable | None
  empty_is_inconclusive: bool = True   # internal ops; forbids covered-empty

ProviderResult
  payload, operation_provenance_id,
  result_semantics: "ok"|"empty"|"truncated"|"shape-drift"|"permission-ambiguous",
  positive_control_status: "not-run"|"passed"|"failed"

# OperationProvenance (frozen, :208) gains a REQUIRED `transport` field + Optional internal-op
# fields (verb+path / op-name+doc-hash + request vars) appended AFTER the existing positional
# fields, so _invoke_sdk's positional construction (:1361/:1388) and test_dependency_sdk_contract.py
# (:153-188, asserts every SDK field + request_timeout==29) stay green (P0-1). sdk ops keep
# branch/preview ArgumentObservation; internal-op fields are None for sdk ops.

CoverageRecord.status adds: "inconclusive"   # empty/truncated/permission-ambiguous from internal APIs
CoverageGap.coverage adds:  "inconclusive"   # renders distinctly from "partial" (ripple audit: U3)
CoverageGap.reason_code new: response-shape-drift · silent-truncation · endpoint-empty-inconclusive
                             · permission-ambiguous-empty · branchfallbacks-missing · route-not-mounted
                             · monocle-not-indexed · token-expired · authoritative-empty-no-producer
                             # (contract-version-drift folded into response-shape-drift, P2-1 — the
                             #  mcp pin is a recorded string with no runtime comparand)
```

### New relation/node kinds (added to `RELATION_KINDS` and node-kind vocabulary)

```text
relation kinds (all dependency-flow, source = provider, target = consumer):
  code-repo-builds-dataset      # ACP-01/02/03; code line carried as evidence locator on this edge
  transform-builds-dataset      # ACP-01/02 (jobspec output)
  dataset-feeds-transform       # ACP-02 (jobspec foundry input)
  column-backs-property         # ACP-04 (column provides -> property consumes)
  object-consumed-by-app        # ACP-05/07
  object-consumed-by-workshop   # ACP-05
  # NOTE (P0-3): NO object-consumed-by-link kind. GraphQL link-type dependents attach their
  # internal evidence id to the EXISTING declared-link edge via _add_edge's evidence union.

node kinds added: code-repo (ri.stemma.main.repository.*), transform-jobspec
  (ri.foundry.main.jobspec.*), dataset-column (synthetic id: datasetRid#column),
  application (ri.third-party-applications.main.application.*),
  workshop-module (ri.workshop.main.module.*), compass-folder (project/parent RIDs).
```

---

## Planned File Structure

```text
src/pltr/
  services/
    dependency.py                 provider seam refactor; register new OperationSpecs, RELATION_KINDS,
                                  node kinds, coverage surfaces; new collectors call providers
    dependency_providers.py       (new) Provider protocol, SdkProvider (== _invoke_sdk), ConjureRestProvider,
                                  GraphQlSseProvider, OperationSpec, ProviderResult, ResultSemantics
    foundry_internal_client.py    (new) FoundryInternalClient: conjure()/graphql(), SSE demux,
                                  Conjure error taxonomy, host/token reuse, no raise_for_status
    dependency_internal_specs.py  (new) ACP ledger: internal OperationSpecs + shape descriptors + positive controls
  commands/
    dependency.py                 wire provider toggles (--no-internal / --providers), render new edges/gaps
  utils/
    dependency_artifacts.py       serialize transport-tagged provenance + ACP ids + new coverage statuses

tests/
  test_services/
    test_dependency_providers.py       (new) provider seam parity; SDK provider == old behavior
    test_foundry_internal_client.py    (new) SSE out-of-order demux; Conjure 400/422/403/200-empty taxonomy
    test_dependency_internal_falsesafety.py (new, TEST-FIRST) empty/truncated -> inconclusive; shape-drift -> gap;
                                            branchfallbacks-missing; permission-ambiguous; monocle-not-indexed
    test_dependency_edges_internal.py  (new) per-edge collectors: ACP-01..08 fixtures -> exact edges/evidence
  test_commands/
    test_dependency.py                 provider toggles; degraded-mode exit 0 with gaps; artifact renders new edges
  test_utils/
    test_dependency_artifacts.py       transport-tagged provenance + ACP ids serialize

docs/user-guide/commands.md
skills/pltr-cli/reference/dependency-commands.md
README.md
```

---

## Implementation Units

### U1. Provider seam — generalize `_invoke_sdk` / `SDK_OPERATION_SPECS`

**Goal:** Turn the SDK-only dispatch into a `Provider` interface with a transport-tagged
`OperationSpec`, with the SDK provider preserving byte-identical behavior.

**Requirements:** R3, R13–R14, R17; KTD-P1

**Files:** `src/pltr/services/dependency_providers.py` (new); `src/pltr/services/dependency.py`
(extract); `tests/test_services/test_dependency_providers.py` (new)

**Approach:**
1. Define a `Provider` protocol whose `invoke` is a **Union of transport-specific signatures**, not
   one uniform signature (P0-1): `SdkProvider.invoke` retains the bound `call: Callable` that
   `_invoke_sdk` requires (`:1322` — the collector resolves the SDK method off `self.client`);
   Conjure/GraphQL providers take verb+path / op-name+doc instead. `OperationSpec` is a superset of
   the frozen `SDKOperationSpec` (keep `SDKOperationSpec` as the `sdk` variant so existing specs and
   their `__post_init__` CAP validation are untouched).
2. Move the body of `_invoke_sdk` (`dependency.py:1322`) into `SdkProvider.invoke` **verbatim** —
   same `budget.request_timeout`, `budget.charge("requests")`, `_argument_observation`,
   `OperationProvenance` construction (`:1361/:1388`), fatal/non-fatal branching. `_invoke_sdk`
   stays as a thin byte-identical delegator so existing collectors AND
   `test_dependency_sdk_contract.py:153-188` (which calls `_invoke_sdk` directly and asserts every
   provenance field) keep passing untouched.
3. Add the **required `transport` field** to `OperationProvenance` and append Optional internal-op
   fields after the existing positional fields (P0-1) — `sdk` for the SDK provider.
4. `ProviderResult` wraps `(payload, operation_provenance_id, result_semantics,
   positive_control_status)`; for SDK ops `result_semantics="ok"` and controls are `not-run`
   (SDK behavior is unchanged).
5. No `RELATION_KINDS`, collector, or CLI change in this unit.

**Test scenarios:**
- Golden parity: for each existing `SDK_OPERATION_SPECS` entry, `SdkProvider.invoke` produces the
  same `OperationProvenance` fields, timeout, and budget charge as the pre-refactor `_invoke_sdk`
  (snapshot the provenance dict).
- The registry-completeness test from the prior plan still passes unchanged.
- `branch`/`preview` rejection for methods that don't accept them still raises `ValueError`.

---

### U2. Internal transport client + false-safety / pin / shape-check primitives (TEST-FIRST)

**Goal:** One HTTP client for Conjure-REST and GraphQL-SSE that never fails toward false safety,
with the false-safety invariants characterized before collectors exist.

**Requirements:** R4, R12, R17; KTD-P2, KTD-P3, KTD-P4

**Dependencies:** U1

**Files:** `src/pltr/services/foundry_internal_client.py` (new);
`src/pltr/services/dependency_providers.py` (extend: `ConjureRestProvider`, `GraphQlSseProvider`,
`ResultSemantics`); `src/pltr/services/dependency_internal_specs.py` (new: ACP registry);
`tests/test_services/test_foundry_internal_client.py` (new);
`tests/test_services/test_dependency_internal_falsesafety.py` (new, **authored first**)

**Execution note:** Author `test_dependency_internal_falsesafety.py` first — it characterizes the
"must not report safe" invariant before the collectors it guards exist.

**Approach:**
1. `FoundryInternalClient(profile)` reuses `CredentialStorage().get_profile(profile)` → `host`,
   `token` (mirroring `BaseService._make_request`). Methods: `conjure(verb, path, *, json_body,
   expected)` returning `(status, parsed, raw)` **without** `raise_for_status`; and
   `graphql(operation_name, document, variables_list) -> list[dict]` of length
   `len(variables_list)`, filled by `extensions.requestIndex`.
2. GraphQL envelope: `{"operations": {"0": document}, "requests":[{hash,name,variables},...]}`,
   headers incl. `Accept: text/event-stream`, `fetch-user-agent: hubble/6.525.9
   forge-graphql-client/0.0.0`. Parse two error planes: non-2xx → Conjure JSON
   (`errorCode`/`errorName`/`errorInstanceId`); 200 → per-event `errors`. Surface
   `errorInstanceId`.
3. Conjure error taxonomy (extends `classify_exception`): `400 Default:InvalidArgument` (empty
   `parameters`) → missing-required-field / `branchfallbacks-missing`; `422
   Conjure:UnprocessableEntity` → `invalid-request` / shape; `403 …PermissionDenied` →
   `inaccessible`; `200` empty `[]`/`{}` → **`inconclusive`** (never `covered-empty`); `Route:
   RouteNotMounted` → `route-not-mounted` gap.
4. `ResultSemantics(spec, response)` classifies `ok|empty|truncated|shape-drift|
   permission-ambiguous`. Truncation rule per ACP-05: non-null `nextPageToken` on a page-argument-
   less field ⇒ `truncated` ⇒ `inconclusive`. Shape descriptor check per KTD-P4 ⇒ `shape-drift`.
5. ACP registry in `dependency_internal_specs.py`: one `OperationSpec` per ACP-01…08 with
   verb/path/op-name, `document_sha256`, `contract_pins={mcp:0.397.0, verified_on:2026-07-21}`,
   shape descriptor, and a `positive_control` callable (config-gated; off by default in tests).
6. Providers construct `OperationProvenance` with transport-tagged arguments and charge the budget
   / forward `request_timeout` exactly like the SDK provider.

**Test scenarios (false-safety, written first):**
- **SSE out-of-order:** a 4-event body delivered `requestIndex` `1,0,2,3` demuxes to correct order;
  a null field (`objectTypeV2: null`) does not abort siblings.
- **Empty ≠ safe:** a `200 []`/`{}` from any internal op yields `result_semantics="empty"` →
  coverage `inconclusive`, never `covered-empty`; a U9-level grep test asserts no internal path
  can write `covered-empty`.
- **Silent truncation:** `dependents` with a non-null `nextPageToken` → `truncated` →
  `inconclusive`; `actionType.dependents` (paginated) → `ok` with continuation, distinct handling.
- **Shape drift:** a response missing a required discriminator → one `response-shape-drift` gap at
  the operation locator; no crash, payload not dropped.
- **`branchFallbacks` missing:** a build2 walk without `branchFallbacks` → `400` mapped to
  `branchfallbacks-missing` (retryable), NOT authoritative-empty.
- **Permission→empty:** a Compass import read returning empty under `403`-shaped emptiness →
  `permission-ambiguous` → `inconclusive`.
- **Contract-version drift:** a spec whose `mcp` pin ≠ the recorded shape emits
  `contract-version-drift`.
- Conjure taxonomy table maps `400/422/403/200-empty/RouteNotMounted` to the expected
  class/coverage/retryable.

---

### U3. Graph-model extension + coverage surfaces + ledger corrections

**Goal:** Register the slice's new relation kinds, node kinds, and coverage surfaces; wire ACP
provenance into the artifact; land the CAP-14/CAP-10/CAP-06/CAP-16 corrections.

**Requirements:** R3, R5, R13–R14; KTD-P5, KTD-P6

**Dependencies:** U1

**Files:** `src/pltr/services/dependency.py` (extend `RELATION_KINDS`, node kinds, coverage
surfaces, merge policy note); `src/pltr/utils/dependency_artifacts.py` (serialize transport-tagged
provenance + ACP ids + `inconclusive`); `tests/test_services/test_dependency.py` (extend)

**Approach:**
1. **Ripple audit first (P1-1):** before adding the `inconclusive` status, sweep every consumer of
   the closed coverage vocabulary — the `_finish_coverage` status set (`:1633-1642`),
   `_complete_coverage` (`:1722`, checks `complete and status is not None`), the matrix-completion
   tests (`:1213`, `:1388`, `:1551`), and any rendering severity/ordering — and confirm each admits
   the new status. Justification for a distinct status over reusing `partial`: a `200 []` with zero
   edges is a poor fit for `partial` (which implies *some* data obtained), and a safety status must
   read as "could not prove absence," not staleness.
2. Add the six new `RELATION_KINDS` (all `dependency-flow`, provider→consumer orientation — note
   NO `object-consumed-by-link`, P0-3) and the new node kinds. Confirm `_add_edge`'s
   unregistered-kind rejection and conflicting-traversal-class guard (`:1581`) cover the new kinds.
3. Add coverage surfaces: `transform-dataset-lineage`, `property-column-mapping`,
   `object-type-consumers`, `consumer-osdk-impact`. Extend the target-kind × surface matrix:
   `property` gains **covered** `property-column-mapping` (retires CAP-14 `G`); `object-type`
   gains **covered/inconclusive** `object-type-consumers` and `consumer-osdk-impact`; `dataset`
   gains `transform-dataset-lineage`.
4. Serialize the `transport`-tagged `OperationProvenance` and ACP ids in the artifact; render
   `inconclusive` distinctly from `partial`.
5. Document the CAP corrections inline (CAP-14 retired; CAP-10 partial; CAP-06 stands with build2
   as additive; CAP-16 extended). Workshop-variables gap remains explicit.

**Test scenarios:**
- Each new relation kind round-trips through `_add_edge` with correct traversal class/orientation;
  two providers observing the same object→link edge merge onto one edge id with both evidence ids.
- Matrix: property `property-column-mapping` cannot finish empty without a gap; object-type
  consumer surfaces accept `inconclusive` as a terminal-with-gap status.
- Artifact round-trips ACP ids, `mcp` pin, `verified_on`, and transport-tagged provenance;
  `inconclusive` renders separately from `partial`.

---

### U4. Edge — property → dataset column (public `includeDatasources`)

**Goal:** Emit `column-backs-property` edges from the public property→column mapping; retire
CAP-14.

**Requirements:** R2–R5; ACP-04; AE1, AE4

**Dependencies:** U2, U3

**Files:** `src/pltr/services/dependency.py` (collector); `src/pltr/services/dependency_internal_specs.py`
(ACP-04 spec); `tests/test_services/test_dependency_edges_internal.py` (new)

**Approach:**
1. `ConjureRestProvider` op ACP-04: `GET /api/v2/ontologies/{ont}/objectTypes/{apiName}?
   includeDatasources=true&preview=true`. Read `datasources[].definition` where `type=="dataset"`;
   for each `propertyMapping[apiName] = {type:"column", column}` emit a `dataset-column` node and a
   `column-backs-property` edge (column source → property target), evidence locator
   `datasources[i].definition.propertyMapping.<apiName>`.
2. Empty `datasources` → `inconclusive` (`property-column-mapping`), never "no backing."
3. Property target resolution stays on the SDK path (augment, not replace); only the column edge
   comes from the REST provider.

**Test scenarios:**
- Fixture with `programId → program_id` emits the exact column edge with the non-convention name.
- Empty `datasources` → `inconclusive` gap, not `covered-empty`.
- Shape drift (missing `propertyMapping`) → `response-shape-drift`, existing property structure
  still returned.

---

### U5. Edge — code repo → transform → dataset (build2 + stemma + AST)

**Goal:** Resolve a dataset to its producing transform, its building code repo, and the transform
source line; emit `transform-builds-dataset`, `dataset-feeds-transform`, `code-repo-builds-dataset`.

**Requirements:** R2–R5; ACP-01, ACP-02, ACP-03, ACP-08; AE3

**Dependencies:** U2, U3

**Files:** `src/pltr/services/dependency.py` (collector + AST helper);
`src/pltr/services/dependency_internal_specs.py` (ACP-01/02/03);
`tests/test_services/test_dependency_edges_internal.py` (extend)

**Approach:**
1. ACP-01 `GET /build2/api/jobspecs/datasets/{datasetRid}` → JobSpec keyed by branch. `inputSpecs`
   where `inputType=="artifacts"` → `datasetLocator.datasetRid` is the stemma repo RID
   (`code-repo` node, `code-repo-builds-dataset` edge). `inputSpecs`/`outputSpecs` where
   `type=="foundry"` → data-lineage `dataset-feeds-transform` / `transform-builds-dataset`. Filter
   non-`foundry` input/output types (build plumbing → false edges).
2. Transform-source-to-line: ACP-03 `GET /stemma/api/repos/{rid}/paths/contents/{path}` (base64
   `fileContents`) + `/blame/{path}` (`blameRows`) + a **local Python AST parse** of
   `@transform(Input(...), Output(...))`. **Scope the parse explicitly (P1-6):** only
   string-literal `Input`/`Output` paths in canonical `transforms.api`-style decorators are
   resolved; aliased decorator imports, other decorators (`@transform_df`/`@incremental`/…),
   computed/f-string/config paths, multi-output beyond the literal forms, and non-Python repos
   (Java/SQL/Mesa) degrade to `unresolved` **with a locator** — never a guess. For a multi-line
   decorator, the edge's blame locator is the `Output(...)` argument's row. Output paths resolve to
   RIDs via ACP-08-style `GET /compass/api/resources?path=<url-encoded>`. Carry the matched
   `@transform` span + blame row as **evidence locators** on the `code-repo-builds-dataset` edge
   (no separate code-line node).
3. Downstream fan-out (`POST …/downstream-jobspecs` with required `branchFallbacks:{branches:[]}`)
   is **deferred** unless a target needs it; if invoked, `branchFallbacks` omission → gap, not
   empty.
4. **ACP-01 `{}` gating (P0-4):** `GET jobspecs/datasets/{rid}` returning `{}` may be `covered-empty`
   ONLY when, in the same run, the ACP-01 positive control passed AND the dataset's
   existence/accessibility is independently confirmed via a successful ACP-08 Compass GET; the record
   then carries `reason_code=authoritative-empty-no-producer` + `positive_control_status=passed` +
   `existence_confirmed=true`. Absent either condition → `inconclusive`. This is the sole sanctioned
   internal `covered-empty` and it is reachable only through the `_finish_coverage` guarded path (U9).

**Test scenarios:**
- `d9069f13`-shaped fixture: `artifacts` input → repo edge; `foundry` output → dataset edge;
  non-`foundry` specs produce no edge.
- `{}` from ACP-01 (dataset not built by a transform) → `covered-empty` is allowed **only** for
  this GET (a real answer per the reference), documented as the one non-inconclusive empty; a
  build2 *walk* empty stays `inconclusive`.
- AST parse extracts Input/Output paths; a malformed `@transform` → `unresolved` gap with locator,
  not a crash; Compass path→RID resolution failure → gap.

---

### U6. Edge — object type → consumers (GraphQL dependents + monocle corroboration)

**Goal:** Emit `object-consumed-by-workshop` / `object-consumed-by-app` edges from
`GetObjectTypeDependents` (link-type dependents attach to the existing `declared-link` edge, P0-3),
corroborated by monocle graphV3; never report "safe" on truncation.

**Requirements:** R2–R5, R12; ACP-05, ACP-06; AE1, AE6

**Dependencies:** U2, U3

**Files:** `src/pltr/services/dependency.py` (collector);
`src/pltr/services/dependency_internal_specs.py` (ACP-05/06);
`tests/test_services/test_dependency_edges_internal.py` (extend)

**Approach:**
1. ACP-05 GraphQL `GetObjectTypeDependents` (SSE): SELECT `rid name description path type{name}
   parent{rid name path} projectRid` on `ResourceMetadata`; classify each dependent by `type.name`
   (`Module` → `object-consumed-by-workshop`; app RIDs → `object-consumed-by-app`). **Link-type
   dependents attach their internal evidence id to the EXISTING `declared-link` edge** via
   `_add_edge`'s evidence union — NOT a new relation kind (P0-3). **Never** read `_id`.
2. Truncation (P1-8): a non-null `nextPageToken` OR `result_count == the pinned page-boundary
   constant` (ACP-05; `dependents` has no page arg and can truncate with no token) ⇒
   `object-type-consumers` surface is **`inconclusive`** with a `silent-truncation` gap even though
   real edges were emitted (R12: uncertainty not suppressed by a non-empty result). A full-boundary
   page is treated as structurally unprovable.
3. ACP-06 monocle `graphV3` (V3 only; `BranchSpec` tagged union) as corroboration: a RID monocle
   does not index is silently dropped → do not treat missing as absent; decode link unions
   defensively. Monocle is alternate/secondary evidence merged onto existing edges.

**Test scenarios:**
- `1ca5ae2e`-shaped response (Module ×5, Link type ×6) emits typed edges with names/paths and
  merges link edges with SDK evidence.
- Non-null `nextPageToken` → real edges **plus** `inconclusive` truncation gap.
- SSE out-of-order batch (reuse U2 harness) demuxes correctly; `objectTypeV2: null` → not-found,
  no sibling effect.
- Monocle `graphV3` downstream that drops adjacent links does not flip the surface to
  `covered-empty`.

---

### U7. Consumer characterization — which apps actually break (TPAS OSDK + Compass namer)

**Goal:** For app consumers, attach the per-object-type OSDK `{oldest,latest}` range and name every
bare consumer RID.

**Requirements:** R2–R4, R11–R12; ACP-07, ACP-08; AE4

**Dependencies:** U6

**Files:** `src/pltr/services/dependency.py` (collector);
`src/pltr/services/dependency_internal_specs.py` (ACP-07/08);
`tests/test_services/test_dependency_edges_internal.py` (extend)

**Approach:**
1. For each `object-consumed-by-app` edge, ACP-07 `PUT /third-party-application-service/api/
   application-sdks/{appRid}/entity-sdk-versions` body `{"entityRids":[<otRid>]}` → per-OT
   `{oldest,latest}` OSDK range; attach as edge evidence/attributes. `listSdks: []` ⇒ annotate
   "breaks live, not via stale bundle." `GET /applications/{rid}` supplies name, subdomains,
   scopes.
2. ACP-08 universal namer `GET /compass/api/resources/{rid}?decoration=path` names any bare
   consumer RID (workshop module, notepad, app, dataset): `name`, `path`, `inTrash`. Use single GET
   (batch shape unverified).
3. Empty `sdkVersions`/permission → `inconclusive` (`consumer-osdk-impact`), never "no impact."

**Test scenarios:**
- Fixture: OT with `{oldest:0.4.0, latest:0.6.0}` annotates the app edge; a rename impact renders
  "breaks app X (OSDK 0.4.0–0.5.x, subdomain …)".
- `listSdks: []` app → "breaks live" annotation.
- Bare RID of each consumer kind resolves to name+path+trashed via ACP-08; a not-found RID →
  `unresolved` gap, not a fabricated name.

---

### U8. Command-surface wiring — `pltr dependency` consumes the providers

**Goal:** Let the existing commands drive the new providers, with degraded-mode reporting and
provider toggles, without breaking SDK-only behavior.

**Requirements:** R6–R9, R12, R17; F1, F2; KTD-P7

**Dependencies:** U4, U5, U6, U7

**Files:** `src/pltr/commands/dependency.py` (extend); `tests/test_commands/test_dependency.py`
(extend)

**Approach:**
1. Add shared options: `--no-internal` (SDK-only fallback), `--providers sdk,conjure,graphql`
   (subset selection), and (config-gated) `--positive-controls` to fire canaries. Default: internal
   providers ON for the slice target kinds.
2. The shared runner constructs `FoundryInternalClient(profile)` once and injects it into the
   Conjure/GraphQL providers on the `DependencyGraphService`; one `AnalysisContext`, one `analyze`,
   one artifact write (unchanged).
3. Degraded mode: any internal-provider `inconclusive`/`inaccessible`/`route-not-mounted`/
   `contract-version-drift` records a gap and the command still exits 0 with the SDK-derived graph;
   only target-resolution/artifact failures are fatal.
4. Rendering: compact/JSON/CSV include the new edges, their transport-tagged provenance, and the
   `inconclusive` gaps distinctly from `partial`.

**Test scenarios:**
- `--no-internal` produces exactly the pre-slice graph (no internal ops invoked).
- An unreachable internal endpoint (route-not-mounted) → exit 0, visible degraded gap, SDK graph
  intact.
- `--providers` subset restricts which transports run; provenance reflects only invoked transports.
- One `analyze`/one artifact write regardless of format/`--full` (prior invariant preserved).

---

### U9. Coverage / verification — positive-control harness + false-safety characterization + registry completeness

**Goal:** Mechanically enforce the false-safety invariant end-to-end and the ACP/CAP registry
completeness across all providers.

**Requirements:** R4, R5, R14, R17; all AEs touching coverage

**Dependencies:** U2, U4, U5, U6, U7

**Files:** `tests/test_services/test_dependency_internal_falsesafety.py` (extend);
`tests/test_services/test_dependency_providers.py` (extend); `tests/test_utils/
test_dependency_artifacts.py` (extend)

**Approach / Test scenarios:**
1. **Chokepoint guard, not grep (P1-2):** extend `_finish_coverage` (`:1624`) so that when a record's
   op is internal (`empty_is_inconclusive` / `transport != "sdk"`) it **rejects `covered-empty`**
   (raises `ValueError`), except the P0-4 guarded ACP-01 path (canary passed + existence confirmed).
   This makes the false-safety invariant a *data* invariant enforced at one point, not a lexical
   hope. Back it with per-ACP behavioral fixtures: feed each ACP op `{}`/`[]`/truncated/
   permission-empty and assert `record.status != "covered-empty"` (only ACP-01 under its full guard
   may be `covered-empty`).
2. **Registry completeness:** every internal op referenced by a collector has an ACP entry with a
   valid `mcp` pin + `verified_on`, a shape descriptor, and a positive control; a dangling ACP id
   or an op without a spec fails the test (mirrors the CAP registry-completeness gate).
3. **Positive-control contract:** each ACP `positive_control` is a callable with the documented
   canary signature (executed only under `--positive-controls`; unit-tested with a stub that a
   drifted response makes fail → `contract-version-drift`).
4. **Provenance resolves:** every new edge's evidence references a resolvable transport-tagged
   `OperationProvenance` carrying ACP id, verb/path or op-name+doc-hash, timestamps, and forwarded
   timeout.
5. **SSE ordering / branchFallbacks / monocle-not-indexed** regression cases folded in as
   permanent guards.

---

### U10. Documentation

**Goal:** Document the provider architecture, the internal-API surfaces, the false-safety contract,
and the CAP/ACP ledger.

**Requirements:** R6–R9, R13–R14

**Dependencies:** U8

**Files:** `docs/user-guide/commands.md`; `skills/pltr-cli/reference/dependency-commands.md`;
`README.md`

**Approach:** Document the three transports, `--no-internal`/`--providers`, the
empty/truncated → `inconclusive` rule (why an internal "no results" is never "no impact"), the ACP
ledger and `mcp@0.397.0` pin, the Workshop-variables known gap, and that enforcement/gating and the
non-slice surfaces are out of scope.

**Test scenarios:** Test expectation: none — documentation only; proofread and compare `--help` output to U8.

---

## Implementation Sequence and Verification Gates

Re-cut into two phases (P1-3) so **one real internal edge reaches the CLI before** the drift-prone
SSE/build2/AST platform is built. Phase A proves the provider architecture end-to-end on the
cheapest real edge (property→column, public GET — no SSE, no Conjure error taxonomy, no
build2/stemma/AST); Phase B fans out.

**Phase A — prove the seam on one edge (CLI-visible value):**
1. U1 — provider seam (pure refactor; every existing test passes untouched).
2. **U2a** — Conjure **GET-only** client: per-request host/token, no `raise_for_status`, the
   `token-expired`/`401` loud class, and `ResultSemantics` (empty→`inconclusive`, shape-drift). No
   SSE/GraphQL yet. Type skeletons land first (signatures + ACP schema, `NotImplementedError`),
   then the client-level characterization tests go red→green (P1-4). Separate internal budget bucket.
3. **U3a** — the `column-backs-property` kind + `property-column-mapping` surface + the
   `inconclusive` status **with its ripple audit** (the rest of U3's kinds/surfaces land in Phase B).
4. U4 — property→column edge (retires CAP-14).
5. **U8a** — wire `--no-internal` and the property path only; render one internal edge + the
   `inconclusive` gap from CLI to artifact. **Phase A ships a working vertical slice here.**

**Phase B — fan out the remaining edges:**
6. **U2b** — extend the client with the SSE/GraphQL transport (proper frame parser, demux on
   `requestIndex`) + the full Conjure error taxonomy + build2 `branchFallbacks`.
7. U3 (remainder) — the build2/object/app relation kinds, node kinds, and coverage surfaces.
8. U5 — code→transform→dataset edge (build2 + stemma + scoped AST).
9. U6 — object-type→consumers edge (GraphQL + monocle V3).
10. U7 — consumer OSDK characterization + Compass namer.
11. U8 (remainder) — `--providers`, degraded mode across all surfaces.
12. U9 — coverage/verification harness (`_finish_coverage` chokepoint guard + per-ACP fixtures).
13. U10 — docs.

After each unit run its focused tests, then the repo's lint/typecheck/test suite. This planning
revision runs no tests and modifies no feature code.

---

## Risks and Mitigations

- **Undocumented-API drift.** Pin `mcp@0.397.0` + `verified_on`; shape-check each response;
  drift → `response-shape-drift`/`contract-version-drift` gap, never a crash or silent drop.
- **False safety.** Empty/truncated/permission-empty → `inconclusive`; positive controls per
  endpoint; a source-grep test forbids `covered-empty` from internal responses.
- **SSE ordering.** Demux on `extensions.requestIndex`; permanent regression test.
- **build2 `branchFallbacks`.** Required map; omission → non-authoritative gap, not empty.
- **Monocle blind spots.** V3 only; not-indexed RIDs silently dropped → not treated as absent;
  link unions decoded defensively.
- **Upstream merge pain.** Provider seam is additive behind the existing service; new
  `RELATION_KINDS`/node kinds/coverage statuses are additive; no public method contract renamed.
- **Auth reuse.** New client reuses `get_profile` host/token but drops `raise_for_status` so the
  intentional Conjure `400`/`422`/`200`-empty semantics are inspected, not raised.

---

## Scope Boundaries

### Included
- Provider abstraction (SDK + Conjure-REST + GraphQL-SSE) feeding one graph/coverage model.
- The single vertical slice: code → transform → dataset → property/column → object-type → apps.
- False-safety primitives, contract pinning, shape-check, positive controls, SSE demux.
- CAP-14 retirement; CAP-10/CAP-06/CAP-16 corrections; ACP ledger.

### Out of scope / Deferred to Follow-Up Work
- **Enforcement/gating** (separate agent harness) — OUT.
- **Non-slice reverse surfaces** — function-registry `usageHistory`, data-health, broader
  ontology-metadata reverse indexes, full monocle V3 link taxonomy — DEFERRED.
- **Monocle V2** — NOT targeted (V3 only).
- Workshop **variables** (`Route:RouteNotMounted`) — permanent explicit gap on this stack.
- build2 `-nodes` endpoints and `jobspecs/events` (service-root permission) — not usable from a
  user token.
- Any mutation surface across the internal services.

---

## Open Questions (assumptions taken)

- **Streaming vs full-body SSE read.** Assumed a full-body read of the SSE response (batch sizes
  here are small) rather than an incremental stream, matching the reference's minimal client. If a
  future surface returns large batches, revisit with `requests(stream=True)`.
- **Positive-control execution cost.** Assumed positive controls are config-gated (off by default)
  so normal runs make no extra network calls; a canary fires only under `--positive-controls` or a
  scheduled drift check.
- **ACP vs CAP naming.** Introduced a parallel **ACP** ledger for internal endpoints rather than
  overloading CAP (which is defined against pinned local SDK source). If maintainers prefer one
  ledger, ACP rows can fold into CAP with a `transport` column.
- **`inconclusive` as a new coverage status.** Assumed adding `inconclusive` (distinct from
  `partial`) is preferable to reusing `partial`, because false-safety needs a status that reads as
  "we could not prove absence," separate from the schedule staleness `partial`.
- **Dataset-column node identity.** Assumed synthetic id `datasetRid#column` for `dataset-column`
  nodes; if a physical column RID is later available, migrate the identity.
- **`/api/v2` includeDatasources transport.** Treated as a Conjure-REST-provider op even though it
  is a public route, to keep one HTTP surface; if the pinned SDK later exposes
  `include_datasources`, move it to the SDK provider without changing the edge.
