"""Tests for native project discovery commands."""

from unittest.mock import Mock, patch

from typer.testing import CliRunner

from pltr.commands.project import app
from pltr.services.compass import UnsupportedCapabilityError
from pltr.utils.pagination import PaginationMetadata, PaginationResult

runner = CliRunner()


def _page() -> PaginationResult:
    return PaginationResult(
        data=[{"rid": "ri.compass.main.project.1", "display_name": "One"}],
        metadata=PaginationMetadata(next_page_token="next", has_more=True),
    )


def test_project_imports_forwards_pagination() -> None:
    with patch("pltr.commands.project.ProjectService") as service_class:
        service = Mock()
        service.get_project_imports.return_value = _page()
        service_class.return_value = service

        result = runner.invoke(
            app,
            [
                "imports",
                "ri.compass.main.project.1",
                "--page-size",
                "10",
                "--page-token",
                "previous",
            ],
        )

    assert result.exit_code == 0
    service.get_project_imports.assert_called_once_with(
        "ri.compass.main.project.1",
        reference_type=None,
        page_size=10,
        page_token="previous",
    )


def test_project_search_agent_output_is_enveloped() -> None:
    with (
        patch("pltr.commands.project.ProjectService") as service_class,
        patch("pltr.commands.project.agent_mode_enabled", return_value=True),
    ):
        service = Mock()
        service.search_projects.return_value = _page()
        service_class.return_value = service

        result = runner.invoke(app, ["search", "project"])

    assert result.exit_code == 0
    assert '"schema_version": "pltr-agent-v1"' in result.stdout
    assert '"next_page_token": "next"' in result.stdout


def test_project_templates_report_public_api_blocker() -> None:
    with patch("pltr.commands.project.CompassService") as service_class:
        service_class.return_value.list_project_templates.side_effect = (
            UnsupportedCapabilityError("template catalog unavailable")
        )

        result = runner.invoke(app, ["templates"])

    assert result.exit_code == 2
    assert "template catalog unavailable" in result.stdout
