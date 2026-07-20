"""Tests for resource graph commands."""

from unittest.mock import patch

from typer.testing import CliRunner

from pltr.commands.lineage import app

runner = CliRunner()


def test_lineage_graph_agent_output_contains_coverage() -> None:
    graph = {
        "root_rid": "ri.foundry.main.dataset.1",
        "nodes": [],
        "edges": [],
        "coverage": {"gaps": ["incomplete"]},
        "pagination": {"has_more": False},
    }
    with (
        patch("pltr.commands.lineage.LineageService") as service_class,
        patch("pltr.commands.lineage.agent_mode_enabled", return_value=True),
    ):
        service_class.return_value.get_resource_graph.return_value = graph

        result = runner.invoke(app, ["ri.foundry.main.dataset.1"])

    assert result.exit_code == 0
    assert '"operation": "get_resource_graph"' in result.stdout
    assert "incomplete" in result.stdout


def test_lineage_graph_forwards_limits() -> None:
    graph = {"nodes": [], "edges": [], "coverage": {}, "pagination": {}}
    with patch("pltr.commands.lineage.LineageService") as service_class:
        service_class.return_value.get_resource_graph.return_value = graph

        result = runner.invoke(
            app,
            [
                "ri.foundry.main.dataset.1",
                "--direction",
                "upstream",
                "--max-depth",
                "3",
                "--max-nodes",
                "20",
                "--max-edges",
                "30",
                "--page-size",
                "4",
                "--page-token",
                "resource-graph-after:foundry:edge:child:ri.foundry.main.dataset.1:ri.foundry.main.dataset.2",
            ],
        )

    assert result.exit_code == 0
    service_class.return_value.get_resource_graph.assert_called_once_with(
        "ri.foundry.main.dataset.1",
        direction="upstream",
        max_depth=3,
        max_nodes=20,
        max_edges=30,
        page_size=4,
        page_token="resource-graph-after:foundry:edge:child:ri.foundry.main.dataset.1:ri.foundry.main.dataset.2",
    )
