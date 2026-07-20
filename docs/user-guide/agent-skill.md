# Agent Skill

This repository includes one model-agnostic skill bundle that teaches coding agents to work effectively with Palantir Foundry through `pltr`.

## What is This?

`skills/pltr-cli/` is the canonical source for command references, workflows, and operating rules. Agent-specific instruction files point to it instead of maintaining duplicate Claude, Codex, or other provider copies.

## Installation

### Option 1: Use Within This Repository

Agents working in the repository follow `AGENTS.md` and load `skills/pltr-cli/SKILL.md` as needed.

### Option 2: Install for Another Client

Link or copy `skills/pltr-cli/` into that client's supported skill directory. Keep this repository directory as the source of truth; do not edit an installed provider copy independently.

## Prerequisites

Before using the skill, ensure you have:

1. **A coding agent with skill-file support**
2. **pltr-cli installed**:
   ```bash
   pip install pltr-cli
   # or
   pipx install pltr-cli
   ```
3. **Authentication configured**:
   ```bash
   pltr configure configure
   pltr verify
   ```

## Usage

Ask the agent a Foundry or `pltr` question. The skill should activate from the task context.

### Example Prompts

**Getting Started:**
- "How do I configure authentication for pltr?"
- "Help me verify my Foundry connection"

**Data Operations:**
- "How do I query a dataset?"
- "Download files from dataset ri.foundry.main.dataset.abc123"
- "Execute SQL query to count rows in my table"

**Orchestration:**
- "Help me set up a daily build schedule"
- "Show me how to monitor build jobs"
- "Create a schedule that runs at 2 AM"

**Permissions:**
- "Grant viewer access to john.doe on my dataset"
- "Set up team permissions for a new project"
- "Audit who has access to this resource"

**Workflows:**
- "Help me create an ETL pipeline script"
- "How do I do cohort analysis with SQL?"
- "Set up data quality monitoring"

**Change impact:**
- "Assess the impact of renaming this ontology property before changing it."
- "Show every known application, action, query, and dataset affected by this object type."
- "Compare this branch's dependency graph with the retained baseline and gate the merge."

## Skill Structure

```
skills/pltr-cli/
├── SKILL.md                    # Main skill file
├── reference/                  # On-demand command contracts
│   ├── dependency-commands.md # Dependency and impact analysis
│   └── ...                    # Other pltr command groups
└── workflows/                  # Multi-step operating workflows
    ├── change-impact-assessment.md # Pre-change baseline and post-change gate
    ├── data-analysis.md
    ├── data-pipeline.md
    └── permission-management.md
```

## How It Works

The skill uses on-demand loading. When a Foundry task arrives:

1. The agent reads `skills/pltr-cli/SKILL.md`.
2. It loads only the relevant reference and workflow files.
3. Before a Foundry resource change, it runs the read-only change-impact assessment and retains the graph artifact.
4. It uses the compact agent contract for reasoning and the CI contract for post-change gating.

This keeps routine context small without discarding the complete evidence graph.

## Customization

You can extend the skill by:

1. **Adding reference files**: Create new `.md` files in `reference/` for additional topics
2. **Adding workflows**: Create new `.md` files in `workflows/` for common patterns
3. **Modifying SKILL.md**: Update the main skill file to reference new content

## Troubleshooting

### Skill Not Activating

If the agent does not use the skill:

1. Verify that the client can discover or has been pointed to `skills/pltr-cli/SKILL.md`.
2. Check that `SKILL.md` has valid YAML frontmatter.
3. Use trigger terms such as "Foundry", "`pltr`", "dependency", "impact", "ontology", or "dataset".

### Incorrect Commands

If the agent suggests incorrect commands:

1. The CLI may have changed—check `pltr --help`.
2. Update the relevant canonical file under `skills/pltr-cli/reference/`.

## Contributing

To improve the skill:

1. Test commands and verify they work
2. Update reference files with correct syntax
3. Add common patterns to workflow files
4. Submit a PR with your improvements

## Related Documentation

- [Quick Start Guide](./quick-start.md) - Get started with pltr-cli
- [Command Reference](./commands.md) - Complete command documentation
- [Common Workflows](./workflows.md) - Real-world usage patterns
- [Authentication Guide](./authentication.md) - Setup and security
