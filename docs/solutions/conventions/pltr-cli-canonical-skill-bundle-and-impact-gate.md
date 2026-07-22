---
title: Canonical skill bundle and Foundry change-impact gate
date: 2026-07-19
category: conventions
module: pltr-cli
problem_type: convention
component: assistant
severity: high
applies_when:
  - "installing or updating pltr-cli guidance for any AI client"
  - "before modifying Foundry ontology resources, actions, queries, datasets, or applications"
  - "before merge or deployment when a Foundry dependency impact must be reassessed"
related_components:
  - "AGENTS.md"
  - "CLAUDE.md"
  - "skills/pltr-cli/SKILL.md"
  - "skills/pltr-cli/workflows/change-impact-assessment.md"
  - "skills/pltr-cli/reference/dependency-commands.md"
  - "docs/user-guide/agent-skill.md"
tags:
  - canonical-skill-bundle
  - change-impact-gate
  - compare-artifact
  - needs-verification
---

# Canonical skill bundle and Foundry change-impact gate

## Context

`pltr-cli` needed one instruction surface that every agent client could consume, rather than parallel provider-specific skill trees that would drift. It also needed a repeatable pre-change practice that turns a Foundry resource change into an evidence-backed downstream impact assessment before merge or deployment.

## Guidance

Use `AGENTS.md` as the repository's canonical instruction file. Keep `CLAUDE.md` as a compatibility pointer only; it must not become another source of workflow or skill content. Maintain the complete, model-agnostic skill bundle under `skills/pltr-cli/`; client-specific installation may link or copy that bundle but must not fork its contents.

Before changing a Foundry ontology resource, action, query, dataset, or application:

1. Choose the narrowest direct dependency target.
2. Run the read-only assessment in agent mode and retain its graph artifact:

   ```bash
   pltr dependency <target-kind> <target> \
     --change "<intended change>" \
     --output-mode agent \
     --graph-output /private/tmp/<baseline>.json
   ```

3. Treat every `must_verify_before_merge` item as a gate. A coverage gap is uncertainty, not evidence of no impact.
4. After the change, rerun the same target with the retained baseline and CI mode:

   ```bash
   pltr dependency <same target-kind> <same target> \
     --compare-artifact /private/tmp/<baseline>.json \
     --output-mode ci
   ```

Agent mode provides a compact, reasoning-oriented summary; CI mode provides a minimal gate payload. Both render the same retained graph evidence rather than starting a second discovery pass. The comparison is valid only when it can establish stable graph identity; malformed or unusable comparison artifacts must fail closed.

## Why This Matters

A resource change can look local while its real blast radius crosses ontology, actions, queries, data, Workshop, applications, and other consumers. The baseline-plus-comparison workflow preserves the evidence required to distinguish known impact from unverified coverage.

The merge that established this convention dogfooded two Apex changes: a property rename produced 32 impacts with 23 required verifications, while an action-input change produced 11 impacts with 10 critical paths. An identical-baseline comparison reported no graph delta but still remained `needs-verification`; absence of a delta does not waive unresolved verification work.

## When to Apply

- Any proposed semantic change to a supported Foundry dependency target.
- Any agent workflow that plans, reviews, or deploys a Foundry resource change.
- Any CI check that compares a post-change dependency graph with a retained baseline.
- Any client installation or documentation update that could otherwise introduce a duplicate skill source.

## Examples

**Canonical packaging:** `AGENTS.md` points all repository agents to `skills/pltr-cli/`; `CLAUDE.md` only preserves compatibility for Claude Code. Other clients consume the same canonical bundle.

**Verification semantics:** `clean` exits 0. `needs-verification` exits 2 so CI can block promotion until required evidence is supplied. Invalid invocation or an unreadable/malformed comparison artifact exits 1, preserving fail-closed behavior.

**Comparison semantics:** A comparable identical baseline may have zero added, removed, or changed edges and zero new impacts. It still cannot be treated as safe when the assessment retains unresolved verification requirements.

## Related

- [`skills/pltr-cli/SKILL.md`](../../../skills/pltr-cli/SKILL.md)
- [`skills/pltr-cli/workflows/change-impact-assessment.md`](../../../skills/pltr-cli/workflows/change-impact-assessment.md)
- [`skills/pltr-cli/reference/dependency-commands.md`](../../../skills/pltr-cli/reference/dependency-commands.md)
- [`docs/user-guide/agent-skill.md`](../../user-guide/agent-skill.md)
- [`docs/user-guide/workflows.md`](../../user-guide/workflows.md)
- [PR #3](https://github.com/zaycruz/pltr-cli/pull/3)
