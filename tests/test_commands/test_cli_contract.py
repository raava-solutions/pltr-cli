"""CLI-level tests for native agent execution behavior."""

import json

from typer.testing import CliRunner

from pltr.cli import app


runner = CliRunner()


def test_global_agent_flag_returns_structured_auth_error() -> None:
    result = runner.invoke(app, ["--agent", "resource", "list"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "pltr-agent-v1"
    assert payload["errors"]
    assert payload["errors"][0]["type"] == "error"


def test_non_interactive_mutation_requires_explicit_confirmation() -> None:
    result = runner.invoke(
        app,
        [
            "--agent",
            "--non-interactive",
            "resource",
            "delete",
            "ri.compass.main.resource.example",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "pltr-agent-v1"
    assert "explicit --force" in payload["errors"][0]["message"]


def test_mcp_command_is_not_registered() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert " mcp " not in f" {result.stdout} "
