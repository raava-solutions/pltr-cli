"""Tests for namespace discovery commands."""

from unittest.mock import patch

from typer.testing import CliRunner

from pltr.commands.namespace import app
from pltr.utils.pagination import PaginationMetadata, PaginationResult

runner = CliRunner()


def test_namespace_list_uses_agent_envelope() -> None:
    page = PaginationResult(
        data=[{"rid": "ri.compass.main.space.1", "type": "namespace"}],
        metadata=PaginationMetadata(next_page_token="next", has_more=True),
    )
    with (
        patch("pltr.commands.namespace.CompassService") as service_class,
        patch("pltr.commands.namespace.agent_mode_enabled", return_value=True),
    ):
        service_class.return_value.list_namespaces.return_value = page

        result = runner.invoke(app, ["--page-size", "5"])

    assert result.exit_code == 0
    assert '"operation": "list_foundry_namespaces"' in result.stdout
    assert '"next_page_token": "next"' in result.stdout


def test_namespace_list_error_returns_nonzero() -> None:
    with patch("pltr.commands.namespace.CompassService") as service_class:
        service_class.return_value.list_namespaces.side_effect = RuntimeError("denied")

        result = runner.invoke(app, [])

    assert result.exit_code == 1
    assert "denied" in result.stdout
