---
title: Reverse-engineering undocumented internal APIs
date: 2026-07-21
category: best-practices
module: pltr-cli
problem_type: best_practice
component: assistant
severity: high
applies_when:
  - "a capability seems missing from a public SDK but the vendor UI clearly does it"
  - "you need the request or response schema of an undocumented service"
  - "a feasibility verdict says a data source is unreachable"
tags: [reverse-engineering, undocumented-api, foundry, sourcemap, conjure, graphql, oracle]
related_components:
  - "src/pltr/services/foundry_internal_client.py"
---

# Reverse-engineering undocumented internal APIs

## Context

The public `foundry-platform-sdk` has no reverse-dependency ("what depends on me") capability. An
initial feasibility scan concluded Workshop, application, and function reverse-wiring were
"permanently undiscoverable," and that verdict was recorded and carried through three plan
documents. It was wrong. The verdict was scoped to one surface — the public Python SDK — and
reported as if it were scoped to the whole platform. The internal APIs expose all of it.

## Guidance

**A feasibility verdict is only as wide as the surface you searched.** Before you declare a
capability impossible, name the surface you checked and state that the verdict is scoped to it.
Then test at least one other surface. Four techniques recovered the whole internal API here:

1. **Vendor agent tooling ships its own API map.** The vendor's own MCP server installs
   unminified with sourcemaps that contain the original TypeScript
   (`~/.npm/_npx/*/node_modules/@palantir/mcp`). It listed 831 internal endpoints across 27
   services. Endpoint paths were read from source, not guessed.

2. **Watch the product's own web app.** The UI already shows the data you want (here, a per-object
   "N apps" usage count). Read its network traffic and its static JS bundles. The bearer token
   does not authenticate the single-page app, but its content-addressed bundles are still
   fetchable, and they name every API path and GraphQL operation the app calls. This is how a
   GraphQL gateway was found that all REST probing had missed.

3. **The Conjure type-confusion oracle.** Conjure services leak their request schema through
   status codes: an unknown field returns `400`; a known field with a wrong-typed value returns
   `422`; the last missing required field returns `200`. Iterate candidate field names against
   this. It found a required `branchFallbacks` map after 45 guessed names had failed. Trap: some
   services deserialize strictly (an unknown key returns `422`), which breaks the oracle — detect
   that first.

4. **The GraphQL validation-error oracle.** When introspection is deliberately crippled (returns
   a stub schema), the validator still sees the real schema. `FieldUndefined` leaks the parent
   type's real name, `SubselectionRequired` leaks a field's exact type, `MissingFieldArgument`
   leaks required arguments — and all validation errors return at once, so about 70 candidate
   fields can be probed per request. This recovered 21 real query root fields where introspection
   admitted to one.

## Why This Matters

Five capability verdicts were wrong because of one scoping error, and the error survived three
plan documents because nobody re-tested it. A false "impossible" is as costly as a false "done":
it removes real work from scope. Blind path-guessing against a Conjure service is near-worthless
(it returns a bare `InvalidArgument` with no field hint), so reading the source or watching real
traffic is not just faster — it is the only reliable path.

Corollary caveat: everything found this way is undocumented and unstable. Pin the source version
the shapes came from, shape-check every response, and degrade loudly on drift (see
[fail-toward-false-safety-undocumented-apis](../architecture-patterns/fail-toward-false-safety-undocumented-apis.md)).

## When to Apply

- The public SDK or documented API lacks a capability that the vendor's own product clearly has.
- You need the exact request or response schema of an internal service and no docs exist.
- A prior "this is not possible" verdict was made against a single surface and never re-tested.

## Examples

Type-confusion oracle — read the required field name from the status code:

```
POST /build2/api/jobspecs/branches/master/downstream-jobspecs
{"datasetRids":[...]}                          -> 400  (a required field is missing)
{"datasetRids":[...], "branchFallbacks":[]}    -> 422  (branchFallbacks is the wrong type)
{"datasetRids":[...], "branchFallbacks":{...}} -> 200  (branchFallbacks is a map, not a list)
```

Validation-error oracle — the crippled introspection stub still validates against the real schema:

```
query { objectTypeV2(identifier:{rid:$rid}) { notARealField } }
-> error: "FieldUndefined: 'notARealField' on type 'ObjectTypeV2'"
   (leaks the real parent type name and, across a batch, ~70 candidate fields at once)
```
