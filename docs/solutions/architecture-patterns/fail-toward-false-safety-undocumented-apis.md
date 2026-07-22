---
title: Fail toward false safety when consuming undocumented APIs
date: 2026-07-21
category: architecture-patterns
module: pltr-cli
problem_type: architecture_pattern
component: assistant
severity: high
applies_when:
  - "building a feature on undocumented or unstable third-party APIs"
  - "an empty or truncated API response could be read as proof of absence"
  - "designing a coverage, impact, or safety model where a wrong answer causes harm"
tags: [false-safety, undocumented-api, coverage, inconclusive, chokepoint, degrade-loudly]
related_components:
  - "src/pltr/services/dependency.py"
  - "src/pltr/services/foundry_internal_client.py"
  - "src/pltr/services/dependency_providers.py"
---

# Fail toward false safety when consuming undocumented APIs

## Context

The `pltr dependency` feature answers "what breaks if I change X" using Foundry's undocumented
internal APIs. These APIs share one dangerous property: **they fail toward false safety.** A
request that quietly failed and a target that is genuinely safe both return an empty result. If
the tool treats empty as "no impact," it reports "safe to change" when it did not actually look.

Three concrete traps were found on these APIs:

1. `ontology-metadata` endpoints silently ignore an unknown request field — a typo returns `200`
   with an empty body.
2. `objectTypeV2.dependents` (GraphQL) has no page argument and truncates silently, while the
   near-identical `actionType.dependents` paginates.
3. `monocle --direction downstream` drops all `adjacent` links, so a change with real dependents
   returns zero impacts.

## Guidance

Make "we could not prove absence" a first-class result, and make it structurally impossible for
that result to read as "safe."

1. **Add an explicit `inconclusive` status.** Do not reuse a "partial" or "empty" status. Empty,
   truncated, permission-denied, and expired-token all map to `inconclusive`. `inconclusive`
   means "unproven," which is different from "no impact."
2. **Enforce at one chokepoint, not per call site.** Put the rule where every coverage record is
   finalized (here, `_finish_coverage`). If a record comes from an undocumented source and the
   status is about to be set to `covered-empty`, raise. A grep-based test cannot enforce a data
   invariant; a chokepoint can.
3. **Pin the contract and shape-check every response.** Record the source version the response
   shape came from (here, `@palantir/mcp` v0.397.0). Validate only the required discriminator
   keys, not the whole payload — undocumented services add fields. On a missing key, emit a
   coverage gap (`response-shape-drift`), never a crash and never a silent drop.
4. **Carry a positive control per endpoint.** A canary that proves the request still returns real
   data tells you "the endpoint drifted" apart from "there is genuinely no data." Keep it
   config-gated so normal runs make no extra calls.
5. **Make degradation loud, never silent.** An expired session token is the trap that hides best:
   it turns every call into an error that folds into `inconclusive`, and the command exits `0`
   looking legitimate. Give token-expiry its own class and a visible banner. Fetch the token per
   request, not once at construction, so mid-run expiry is caught.

## Why This Matters

For a safety or impact tool, the worst failure is a confident wrong "all clear." Every trap above
produces exactly that. A reviewer might question a zero; an agent will proceed. The tool's whole
reason to exist is to refuse false safety, so the refusal must be a structural invariant, not a
convention a future edit can break.

The same failure mode appeared three separate times in one investigation (direction-filter drop,
silent-empty on a typo, silent truncation) and once more in the build itself (a design that
laundered token-expiry into `inconclusive`). Treat "empty equals safe" as the default bug of this
whole class of work.

## When to Apply

- Any feature built on APIs you do not own and cannot rely on for stability.
- Any place an empty or truncated response is one of the possible answers and being wrong is
  costly.
- Reverse-engineered, internal, or preview APIs where the response shape can change without notice.

## Examples

Chokepoint guard — an internal source can never finish `covered-empty`:

```python
# in _finish_coverage, where every coverage record is finalized
if status == "covered-empty" and (
    record.transport != "sdk" or record.empty_is_inconclusive
):
    raise ValueError("internal coverage cannot be covered-empty")
```

Result classification — empty and truncated both degrade, never "safe":

```python
# ResultSemantics(spec, (status, payload, raw)) -> ok | empty | truncated | shape-drift | ...
if isinstance(payload, Mapping) and payload.get("nextPageToken") is not None:
    return "truncated"          # -> coverage "inconclusive", never covered/covered-empty
```

Token-expiry is loud, not laundered:

```python
# 401 gets its own class; it is NOT folded into inaccessible/inconclusive
# and the command surfaces a visible banner:
#   DEGRADED [token-expired]: re-authenticate before relying on internal coverage
```
