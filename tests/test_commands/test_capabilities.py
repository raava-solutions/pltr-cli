"""Tests for the native capability inspection command."""

import json

from typer.testing import CliRunner

from pltr.cli import app


runner = CliRunner()


def test_capabilities_agent_output_is_stable_json() -> None:
    result = runner.invoke(app, ["capabilities", "--format", "agent"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "pltr-agent-v1"
    manifest = payload["data"]
    assert manifest["schema_version"] == "foundry-agent-capabilities-v1"
    assert manifest["catalog"]["tool_count"] == 72
    assert manifest["catalog"]["workflow_count"] == 1
    assert manifest["counts"]["total"] == 73
    assert manifest["capabilities"][0].keys() >= {
        "capability_id",
        "kind",
        "group",
        "command",
        "service",
        "api_evidence",
        "status",
        "mutation_risk",
        "output_contract",
        "test_reference",
    }


def test_capabilities_table_output_contains_group_summary() -> None:
    result = runner.invoke(app, ["capabilities", "--format", "table"])

    assert result.exit_code == 0, result.stdout
    assert "Native Foundry CLI Capabilities" in result.stdout
    assert "Catalog:" in result.stdout
    assert "Tools: 72" in result.stdout
    assert "Workflows: 1" in result.stdout


def test_capabilities_can_write_agent_output_to_file(tmp_path) -> None:
    output = tmp_path / "capabilities.json"

    result = runner.invoke(
        app,
        ["capabilities", "--format", "agent", "--output", str(output)],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["data"]["counts"]["total"] == 73
