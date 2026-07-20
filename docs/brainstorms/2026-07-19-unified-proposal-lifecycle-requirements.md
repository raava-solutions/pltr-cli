---
date: 2026-07-19
topic: unified-proposal-lifecycle
---

# Unified Proposal Lifecycle Requirements

## Summary

Add a typed `pltr proposal` workflow for Foundry code-repository pull requests and Ontology Global Proposals. Users can raise, inspect, review, comment on, decide, complete, or close proposals from the CLI without confusing the two proposal systems.

---

## Problem Frame

`pltr` has no proposal lifecycle today. It offers generic Foundry discovery and dataset branch operations, but neither is a code-repository or Ontology proposal workflow. The published MCP surface covers only part of the desired lifecycle, leaving users to switch tools or the Foundry UI for review and completion.

---

## Key Decisions

- **One typed command family.** The CLI uses the `proposal` noun and requires users to select the proposal type, rather than hiding the distinction between code-repository pull requests and Global Proposals.
- **Complete lifecycle is the product goal.** Both proposal types support their meaningful create, read, review, comment, decision, and terminal actions through the CLI.
- **Feasibility gates unsupported writes.** Approval decisions, code-repository merges, and Global Proposal acceptance require verified Foundry API semantics and permissions before implementation commits to them.
- **Merge safety is opt-out, not opt-in.** Completion actions require interactive confirmation by default; `--yes` enables intentional non-interactive automation.

---

## Actors

- A1. **Author** raises a proposal, tracks its state, responds to review, and completes or closes it.
- A2. **Reviewer** inspects a proposal, reads its change context, comments, and records an approval or requested-changes decision where the type supports it.
- A3. **Automation** runs the same lifecycle non-interactively with explicit confirmation bypass and machine-readable results.

---

## Key Flows

- F1. Raise and inspect
  - **Trigger:** A1 has a code-repository branch or a Global Branch ready for review.
  - **Actors:** A1
  - **Steps:** A1 selects the proposal type, raises the proposal, then retrieves its status and review context.
  - **Outcome:** The CLI returns an unambiguous proposal identity and current state.

- F2. Review and comment
  - **Trigger:** A2 receives a proposal identity.
  - **Actors:** A2
  - **Steps:** A2 retrieves the proposal, reviews its change context, adds general or inline comments where meaningful, then records a review decision when supported.
  - **Outcome:** The proposal exposes its review state and comments to subsequent CLI users.

- F3. Complete or close
  - **Trigger:** A1 has a review-ready proposal.
  - **Actors:** A1, A3
  - **Steps:** The CLI refreshes proposal state immediately before a terminal action, presents the exact target for confirmation, then performs the type-appropriate merge, accept, or close action.
  - **Outcome:** The CLI never reports a terminal action as successful when it was blocked, stale, unauthorized, or unsupported.

---

## Requirements

**Unified command contract**

- R1. Every proposal command requires an explicit proposal type: code-repository pull request or Ontology Global Proposal.
- R2. Users can create, list, and retrieve proposals of either type through the unified command family.
- R3. Proposal retrieval exposes the current lifecycle state, author, review activity, and change context appropriate to its type.
- R4. Users can add review comments to both proposal types when Foundry supports comments for that type.
- R5. Users can record approval and requested-changes decisions when Foundry supports review decisions for that type.

**Terminal actions and safety**

- R6. Users can merge code-repository pull requests, accept Global Proposals, and close either proposal type when the corresponding Foundry action is verified and authorized.
- R7. Before a terminal action, the CLI refreshes proposal state and rejects actions that are no longer valid, including stale, blocked, or unauthorized proposals.
- R8. Terminal actions prompt for confirmation by default and accept `--yes` for non-interactive automation.
- R9. An unsupported type-action combination fails clearly without switching to the Foundry UI or reporting simulated success.

**Automation and consistency**

- R10. Every networked proposal command supports the existing profile-selection convention.
- R11. Machine-readable output contains only stable structured data, including success and failure results.
- R12. Proposal failures distinguish authentication, authorization, validation, conflict, unsupported capability, and remote-service failure categories with nonzero exits.

---

## Acceptance Examples

- AE1. **Covers R1, R2, R3.**
  - **Given:** An author has selected `code-pr`.
  - **When:** They raise and retrieve a proposal.
  - **Then:** The CLI returns the created proposal and its review-ready state without treating it as a Global Proposal.

- AE2. **Covers R4, R5.**
  - **Given:** A reviewer retrieves a proposal with review capability.
  - **When:** They add a comment and request changes.
  - **Then:** Later retrieval shows the comment and decision in the proposal's review state.

- AE3. **Covers R6, R7, R8.**
  - **Given:** A code-repository pull request is mergeable at initial inspection.
  - **When:** Its head changes before the author confirms merge.
  - **Then:** The CLI refreshes state, rejects the stale action, and performs no merge.

- AE4. **Covers R6, R9.**
  - **Given:** A Global Proposal does not expose a verified acceptance action.
  - **When:** A user requests acceptance.
  - **Then:** The CLI returns an unsupported-capability failure and does not redirect to the UI or claim success.

---

## Success Criteria

- An authenticated user can complete every Foundry-supported lifecycle action for each selected proposal type through `pltr`.
- A script can execute the same supported actions with `--yes` and consume clean structured output.
- Terminal actions cannot silently operate on stale, blocked, unauthorized, or unsupported proposals.

---

## Scope Boundaries

- Dataset branches, transactions, widget repositories, GitHub contributor pull requests, and alias-definition merging remain separate concepts.
- The CLI does not infer proposal type from resource identifiers or command arguments.
- No UI fallback, fake completion, or silently degraded terminal action is permitted.

---

## Dependencies / Assumptions

- A direct Foundry API feasibility discovery must verify callable APIs, authentication scopes, and terminal semantics for review decisions, code-repository merging, and Global Proposal acceptance before those actions are implemented.
- The CLI can reuse its existing authentication, profile-selection, structured-output, and destructive-action confirmation conventions.

---

## Sources / Research

- `src/pltr/cli.py` — current command registration has no proposal lifecycle surface.
- `src/pltr/commands/dataset.py` — dataset branch operations are adjacent but distinct; also provides destructive-action confirmation precedent.
- `src/pltr/commands/mcp.py` — MCP launcher delegates to an external, unpinned package.
- `src/pltr/utils/formatting.py` — existing structured-output conventions.
- Palantir Foundry MCP available tools: https://www.palantir.com/docs/foundry/palantir-mcp/available-tools/
- Palantir Code Repositories navigation: https://www.palantir.com/docs/foundry/code-repositories/navigation/
- Palantir Code Repositories branch settings: https://www.palantir.com/docs/foundry/code-repositories/branch-settings/
