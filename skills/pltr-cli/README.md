# pltr-cli Agent Skill

This directory is the canonical, model-agnostic skill bundle for working with Palantir Foundry through `pltr`.

## Installation

Use `skills/pltr-cli/` directly in this repository. For another agent client, install or link this same directory into that client's skill path; do not maintain provider-specific copies.

## Structure

```
skills/pltr-cli/
├── SKILL.md                    # Main skill definition
├── reference/                  # Command references loaded on demand
│   ├── dependency-commands.md # Dependency and impact-analysis contract
│   └── ...                    # Other pltr command groups
└── workflows/                  # Multi-step operating workflows
    ├── change-impact-assessment.md # Mandatory pre/post-change gate
    ├── data-analysis.md
    ├── data-pipeline.md
    └── permission-management.md
```

## Usage

Ask any supported coding agent about Foundry tasks:

- "Assess the impact of renaming this ontology property."
- "Which applications and actions depend on this object type?"
- "Compare the post-change dependency graph with the baseline."
- "How do I query a dataset?"

The agent should load this skill and use the change-impact workflow before proposing or making a Foundry resource change.

## Documentation

See [docs/user-guide/agent-skill.md](../../docs/user-guide/agent-skill.md) for installation and usage guidance.
