# Foundry Change-Impact Assessment Workflow

Use this workflow before changing a Foundry resource and again before merge or deployment. It is read-only and optimized for compact agent context while retaining a complete evidence artifact.

## Contract

This workflow guarantees that the agent:

- assesses the intended change against observed upstream, downstream, and adjacent relationships;
- keeps provenance, coverage gaps, and uncertainty visible;
- preserves a complete baseline artifact for audit and comparison;
- converts the result into concrete merge and deployment verification work;
- reruns the same target after the change and gates on the diff.

It does not approve, apply, or remediate a Foundry change.

## Phase 1: Select the narrowest target

Use the command matching the resource being changed:

```bash
pltr dependency object-type ONTOLOGY_RID OBJECT_TYPE
pltr dependency property ONTOLOGY_RID OBJECT_TYPE PROPERTY
pltr dependency link-type ONTOLOGY_RID OBJECT_TYPE LINK_TYPE
pltr dependency action-type ONTOLOGY_RID ACTION_TYPE
pltr dependency query-type ONTOLOGY_RID QUERY_TYPE
pltr dependency resource RESOURCE_RID
```

Prefer `property`, `link-type`, `action-type`, or `query-type` over a broader object/resource target when the exact target is addressable. Use `resource` for Compass-resolvable datasets and applications. Do not invent direct Function, schedule, or Workshop-variable targets; use a resolvable surrounding resource and preserve the reported gaps.

## Phase 2: Capture the pre-change baseline

Describe the intended change concretely and classify it explicitly when possible:

```bash
pltr dependency object-type "$ONTOLOGY_RID" "$OBJECT_TYPE" \
  --profile "$PROFILE" \
  --branch "$BRANCH" \
  --change "rename proposalName" \
  --change-type rename \
  --direction both \
  --depth 3 \
  --output-mode agent \
  --format json \
  --graph-output ./artifacts/change-impact-before.json \
  --output ./artifacts/change-impact-before-agent.json
```

Allowed change types:

- `rename`
- `type-change`
- `optional-to-required`
- `required-to-optional`
- `remove-delete`
- `action-input-change`
- `query-output-change`

Free-text `--change` provides context. Explicit `--change-type` wins over inference and should be used whenever one enum matches. Omit `--branch` only when server-default branch semantics are intentional; provenance records the distinction.

## Phase 3: Turn the agent block into work

Read the compact `agent` block first. Inspect the complete graph artifact only for paths or evidence needed to resolve the assessment.

Required interpretation order:

1. `status` and `summary`
2. `change.change_type` and `change.change_type_source`
3. `blast_radius.score` and group counts
4. `release_risk.score`
5. `verification.must_verify_before_merge`
6. `verification.should_verify_before_deploy`
7. `coverage_completeness`
8. `action_query_contracts`
9. `artifact_reference`

Rules:

- `needs-verification` is a gate, not a warning to ignore.
- Resolve relevant `must_verify_before_merge` items before merge or obtain explicit operator acceptance.
- Convert `should_verify_before_deploy` into release checks.
- Review action inputs, writes/deletes, affected fields, query inputs/outputs, likely consumers, and unresolved consumers when the target touches their contracts.
- A coverage gap is uncertainty. Never translate it to “no downstream impact.”
- A high score prioritizes review; it is not probability and does not replace the underlying paths and evidence.

## Phase 4: Apply the change outside this workflow

Make only the intended change through the repository or the appropriate Foundry branch/proposal process. The dependency workflow itself remains read-only.

Carry the baseline artifact path and analysis ID in the implementation or review record. Do not discard the artifact after rendering the compact summary.

## Phase 5: Compare and gate

Rerun the same target, profile, branch, direction, depth, and budgets. Compare against the retained baseline:

```bash
pltr dependency object-type "$ONTOLOGY_RID" "$OBJECT_TYPE" \
  --profile "$PROFILE" \
  --branch "$BRANCH" \
  --change "rename proposalName" \
  --change-type rename \
  --direction both \
  --depth 3 \
  --compare-artifact ./artifacts/change-impact-before.json \
  --output-mode ci \
  --graph-output ./artifacts/change-impact-after.json
```

CI exit contract:

- `0`: clean
- `2`: needs verification
- `1`: fatal invocation, discovery, rendering, or artifact failure

Review added edges, removed edges, changed coverage, newly introduced impacts, `possibly_budget_truncated`, and comparability. A removed edge is not a verified deletion when the current run was budget-truncated or otherwise coverage-incomplete.

## Output Format

Report:

1. target and intended change;
2. status, blast-radius score, and release-risk score;
3. direct and transitive impacts, grouped by urgency;
4. merge and deployment verification items;
5. coverage limitations;
6. baseline/current artifact paths and analysis IDs;
7. post-change diff and CI exit result.

## Anti-Patterns

- Changing Foundry first and assessing impact afterward
- Using only a resource name when a narrower target is available
- Omitting `--graph-output` and losing the evidence artifact
- Treating missing or truncated evidence as absence
- Reading the entire graph into agent context before the compact agent block
- Using a score as a substitute for paths, provenance, or verification
- Running mutation commands as part of this read-only workflow
