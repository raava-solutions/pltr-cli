"""
Tests for dataset CLI commands.
"""

import pytest
from unittest.mock import Mock, patch
from typer.testing import CliRunner

from pltr.commands.dataset import app
from pltr.auth.base import ProfileNotFoundError, MissingCredentialsError

runner = CliRunner()


@pytest.fixture
def mock_dataset_service():
    """Mock DatasetService for command tests."""
    with patch("pltr.commands.dataset.DatasetService") as mock_service_class:
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        yield mock_service


@pytest.fixture
def sample_dataset():
    """Sample single dataset for testing."""
    return {
        "rid": "ri.foundry.main.dataset.test",
        "name": "Test Dataset",
        "description": "A test dataset",
        "created_time": "2023-01-01T00:00:00Z",
        "created_by": "test.user@example.com",
        "last_modified": "2023-01-02T00:00:00Z",
        "size_bytes": 1024000,
        "schema_id": "test-schema-id",
        "parent_folder_rid": "ri.foundry.main.folder.parent",
    }


# Tests for 'get' command
def test_dataset_stats_success_and_pagination(mock_dataset_service):
    mock_dataset_service.get_dataset_stats.return_value = {
        "dataset_rid": "ri.foundry.main.dataset.test",
        "file_count": 2,
        "size_bytes": 10,
        "warnings": [],
        "pagination": {"has_more": True, "next_page_token": "next"},
    }

    result = runner.invoke(
        app,
        [
            "stats",
            "ri.foundry.main.dataset.test",
            "--page-size",
            "5",
            "--page-token",
            "previous",
            "--fetch-all",
            "--format",
            "agent",
        ],
    )

    assert result.exit_code == 0
    mock_dataset_service.get_dataset_stats.assert_called_once_with(
        "ri.foundry.main.dataset.test",
        branch="master",
        page_size=5,
        page_token="previous",
        max_pages=1,
        fetch_all=True,
    )
    assert '"schema_version": "pltr-agent-v1"' in result.stdout
    assert '"next_page_token": "next"' in result.stdout


def test_get_dataset_success(mock_dataset_service, sample_dataset):
    """Test successful dataset retrieval."""
    mock_dataset_service.get_dataset.return_value = sample_dataset

    result = runner.invoke(app, ["get", "ri.foundry.main.dataset.test"])

    assert result.exit_code == 0
    mock_dataset_service.get_dataset.assert_called_once_with(
        "ri.foundry.main.dataset.test"
    )


def test_get_dataset_json_format(mock_dataset_service, sample_dataset):
    """Test dataset retrieval with JSON format."""
    mock_dataset_service.get_dataset.return_value = sample_dataset

    result = runner.invoke(
        app, ["get", "ri.foundry.main.dataset.test", "--format", "json"]
    )

    assert result.exit_code == 0


def test_get_dataset_csv_format(mock_dataset_service, sample_dataset):
    """Test dataset retrieval with CSV format."""
    mock_dataset_service.get_dataset.return_value = sample_dataset

    result = runner.invoke(
        app, ["get", "ri.foundry.main.dataset.test", "--format", "csv"]
    )

    assert result.exit_code == 0


def test_get_dataset_with_profile(mock_dataset_service, sample_dataset):
    """Test dataset retrieval with specific profile."""
    mock_dataset_service.get_dataset.return_value = sample_dataset

    result = runner.invoke(
        app, ["get", "ri.foundry.main.dataset.test", "--profile", "test-profile"]
    )

    assert result.exit_code == 0


def test_get_dataset_profile_not_found(mock_dataset_service):
    """Test dataset retrieval with non-existent profile."""
    mock_dataset_service.get_dataset.side_effect = ProfileNotFoundError(
        "Profile not found"
    )

    result = runner.invoke(app, ["get", "ri.foundry.main.dataset.test"])

    assert result.exit_code == 1
    assert "Profile not found" in result.stdout


def test_get_dataset_missing_credentials(mock_dataset_service):
    """Test dataset retrieval with missing credentials."""
    mock_dataset_service.get_dataset.side_effect = MissingCredentialsError(
        "Missing token"
    )

    result = runner.invoke(app, ["get", "ri.foundry.main.dataset.test"])

    assert result.exit_code == 1
    assert "Missing token" in result.stdout


def test_get_dataset_error(mock_dataset_service):
    """Test dataset retrieval with error."""
    mock_dataset_service.get_dataset.side_effect = Exception("Dataset not found")

    result = runner.invoke(app, ["get", "ri.foundry.main.dataset.test"])

    assert result.exit_code == 1
    assert "Failed to get dataset" in result.stdout


# Tests for 'create' command
def test_create_dataset_success(mock_dataset_service, sample_dataset):
    """Test successful dataset creation."""
    mock_dataset_service.create_dataset.return_value = sample_dataset

    result = runner.invoke(
        app, ["create", "New Dataset", "--parent-folder", "ri.compass.main.folder.test"]
    )

    assert result.exit_code == 0
    assert "Successfully created dataset" in result.stdout
    mock_dataset_service.create_dataset.assert_called_once_with(
        name="New Dataset", parent_folder_rid="ri.compass.main.folder.test"
    )


def test_create_dataset_with_parent_folder(mock_dataset_service, sample_dataset):
    """Test dataset creation with parent folder."""
    mock_dataset_service.create_dataset.return_value = sample_dataset

    result = runner.invoke(
        app,
        ["create", "New Dataset", "--parent-folder", "ri.foundry.main.folder.parent"],
    )

    assert result.exit_code == 0
    mock_dataset_service.create_dataset.assert_called_once_with(
        name="New Dataset", parent_folder_rid="ri.foundry.main.folder.parent"
    )


def test_create_dataset_json_format(mock_dataset_service, sample_dataset):
    """Test dataset creation with JSON output format."""
    mock_dataset_service.create_dataset.return_value = sample_dataset

    result = runner.invoke(
        app,
        [
            "create",
            "New Dataset",
            "--parent-folder",
            "ri.compass.main.folder.test",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0


def test_create_dataset_with_profile(mock_dataset_service, sample_dataset):
    """Test dataset creation with specific profile."""
    mock_dataset_service.create_dataset.return_value = sample_dataset

    result = runner.invoke(
        app,
        [
            "create",
            "New Dataset",
            "--parent-folder",
            "ri.compass.main.folder.test",
            "--profile",
            "test-profile",
        ],
    )

    assert result.exit_code == 0


def test_create_dataset_profile_not_found(mock_dataset_service):
    """Test dataset creation with non-existent profile."""
    mock_dataset_service.create_dataset.side_effect = ProfileNotFoundError(
        "Profile not found"
    )

    result = runner.invoke(
        app, ["create", "New Dataset", "--parent-folder", "ri.compass.main.folder.test"]
    )

    assert result.exit_code == 1
    assert "Profile not found" in result.stdout


def test_create_dataset_missing_credentials(mock_dataset_service):
    """Test dataset creation with missing credentials."""
    mock_dataset_service.create_dataset.side_effect = MissingCredentialsError(
        "Missing token"
    )

    result = runner.invoke(
        app, ["create", "New Dataset", "--parent-folder", "ri.compass.main.folder.test"]
    )

    assert result.exit_code == 1
    assert "Missing token" in result.stdout


def test_create_dataset_error(mock_dataset_service):
    """Test dataset creation with error."""
    mock_dataset_service.create_dataset.side_effect = Exception("Creation failed")

    result = runner.invoke(
        app, ["create", "New Dataset", "--parent-folder", "ri.compass.main.folder.test"]
    )

    assert result.exit_code == 1
    assert "Failed to create dataset" in result.stdout


# Tests for 'preview' command
def test_preview_dataset_success(mock_dataset_service):
    """Test successful dataset preview."""
    mock_dataset_service.preview_data.return_value = [
        {"id": 1, "name": "test1"},
        {"id": 2, "name": "test2"},
    ]

    result = runner.invoke(app, ["preview", "ri.foundry.main.dataset.test"])

    assert result.exit_code == 0
    mock_dataset_service.preview_data.assert_called_once_with(
        "ri.foundry.main.dataset.test", limit=10
    )


def test_preview_dataset_with_limit(mock_dataset_service):
    """Test dataset preview with custom limit."""
    mock_dataset_service.preview_data.return_value = [
        {"id": 1, "name": "test1"},
    ]

    result = runner.invoke(
        app, ["preview", "ri.foundry.main.dataset.test", "--limit", "5"]
    )

    assert result.exit_code == 0
    mock_dataset_service.preview_data.assert_called_once_with(
        "ri.foundry.main.dataset.test", limit=5
    )


def test_preview_dataset_with_invalid_limit(mock_dataset_service):
    """Test dataset preview with invalid (zero or negative) limit."""
    # Test with zero limit
    result = runner.invoke(
        app, ["preview", "ri.foundry.main.dataset.test", "--limit", "0"]
    )
    assert result.exit_code == 2  # Typer returns 2 for validation errors

    # Test with negative limit
    result = runner.invoke(
        app, ["preview", "ri.foundry.main.dataset.test", "--limit", "-5"]
    )
    assert result.exit_code == 2  # Typer returns 2 for validation errors


def test_preview_dataset_json_format(mock_dataset_service):
    """Test dataset preview with JSON format."""
    mock_dataset_service.preview_data.return_value = [
        {"id": 1, "name": "test1"},
    ]

    result = runner.invoke(
        app, ["preview", "ri.foundry.main.dataset.test", "--format", "json"]
    )

    assert result.exit_code == 0


def test_preview_dataset_csv_format(mock_dataset_service):
    """Test dataset preview with CSV format."""
    mock_dataset_service.preview_data.return_value = [
        {"id": 1, "name": "test1"},
    ]

    result = runner.invoke(
        app, ["preview", "ri.foundry.main.dataset.test", "--format", "csv"]
    )

    assert result.exit_code == 0


def test_preview_dataset_with_output_file(mock_dataset_service, tmp_path):
    """Test dataset preview with output file."""
    mock_dataset_service.preview_data.return_value = [
        {"id": 1, "name": "test1"},
    ]

    output_file = tmp_path / "preview.json"

    result = runner.invoke(
        app,
        [
            "preview",
            "ri.foundry.main.dataset.test",
            "--format",
            "json",
            "--output",
            str(output_file),
        ],
    )

    assert result.exit_code == 0
    assert "Preview saved to" in result.stdout


def test_preview_dataset_empty(mock_dataset_service):
    """Test preview of empty dataset."""
    mock_dataset_service.preview_data.return_value = []

    result = runner.invoke(app, ["preview", "ri.foundry.main.dataset.test"])

    assert result.exit_code == 0
    assert "Dataset is empty" in result.stdout


def test_preview_dataset_with_profile(mock_dataset_service):
    """Test dataset preview with specific profile."""
    mock_dataset_service.preview_data.return_value = [
        {"id": 1, "name": "test1"},
    ]

    result = runner.invoke(
        app, ["preview", "ri.foundry.main.dataset.test", "--profile", "test-profile"]
    )

    assert result.exit_code == 0


def test_preview_dataset_profile_not_found(mock_dataset_service):
    """Test dataset preview with non-existent profile."""
    mock_dataset_service.preview_data.side_effect = ProfileNotFoundError(
        "Profile not found"
    )

    result = runner.invoke(app, ["preview", "ri.foundry.main.dataset.test"])

    assert result.exit_code == 1
    assert "Profile not found" in result.stdout


def test_preview_dataset_missing_credentials(mock_dataset_service):
    """Test dataset preview with missing credentials."""
    mock_dataset_service.preview_data.side_effect = MissingCredentialsError(
        "Missing token"
    )

    result = runner.invoke(app, ["preview", "ri.foundry.main.dataset.test"])

    assert result.exit_code == 1
    assert "Missing token" in result.stdout


def test_preview_dataset_error(mock_dataset_service):
    """Test dataset preview with error."""
    mock_dataset_service.preview_data.side_effect = Exception("Preview failed")

    result = runner.invoke(app, ["preview", "ri.foundry.main.dataset.test"])

    assert result.exit_code == 1
    assert "Failed to preview dataset" in result.stdout


def test_schedule_list_passes_public_dictionary_contract_to_formatter(
    mock_dataset_service,
):
    schedules = [
        {
            "schedule_rid": "ri.orchestration.main.schedule.one",
            "name": None,
            "description": None,
            "enabled": None,
            "created_time": None,
        }
    ]
    mock_dataset_service.get_schedules.return_value = schedules

    with patch("pltr.commands.dataset.formatter.format_schedules") as format_schedules:
        result = runner.invoke(
            app,
            ["schedules", "list", "ri.foundry.main.dataset.input"],
        )

    assert result.exit_code == 0
    mock_dataset_service.get_schedules.assert_called_once_with(
        "ri.foundry.main.dataset.input"
    )
    format_schedules.assert_called_once_with(schedules, "table", None)
