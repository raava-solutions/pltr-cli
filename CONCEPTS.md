# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning.

## Dependency analysis

### Dependency Graph
A retained, evidence-backed graph that represents a Foundry target's resolved upstream, downstream, and adjacent relationships, including the provenance needed to interpret each relationship.

### Change-Impact Assessment
A read-only evaluation that applies an intended change to a Dependency Graph and returns ranked impacts, affected consumers, release risk, coverage limits, and the verification work required before promotion.

### Comparison Artifact
A retained baseline Dependency Graph and assessment identity used to compare the same target after a change; it is accepted only when its graph identity and structure can be safely validated.

### Provider
A transport-specific source of dependency evidence behind one interface — `sdk`, `conjure-rest`, or `graphql-sse`. Every Provider feeds the same evidence, coverage-record, and edge machinery, so the graph model is transport-agnostic and the public SDK path and the internal-API paths compose into one Dependency Graph.

### Inconclusive
A coverage status meaning "could not prove absence" — distinct from a verified empty result. An empty, truncated, permission-denied, or expired-token response from an undocumented internal API becomes Inconclusive, never `covered-empty`. It exists so a silent API failure can never read as "no impact."

## Relationships

A Change-Impact Assessment reads a Dependency Graph. A Comparison Artifact preserves an earlier Dependency Graph so a later Change-Impact Assessment can identify the graph delta without rediscovering the baseline.
