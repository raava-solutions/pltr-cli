"""Tests for verified Compass discovery operations."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from pltr.services.compass import CompassService, UnsupportedCapabilityError


def _service() -> tuple[CompassService, Mock]:
    client = Mock()
    client.filesystem = Mock()
    with patch("pltr.services.base.AuthManager") as auth:
        auth.return_value.get_client.return_value = client
        service = CompassService()
        service._client = client
    return service, client


def test_list_namespaces_uses_verified_space_cursor() -> None:
    service, client = _service()
    iterator = SimpleNamespace(
        data=[SimpleNamespace(rid="ri.compass.main.space.1", display_name="One")],
        next_page_token="space-next",
    )
    client.filesystem.Space.list.return_value = iterator

    result = service.list_namespaces(page_size=10, page_token="space-prev")

    client.filesystem.Space.list.assert_called_once_with(
        page_size=10, page_token="space-prev"
    )
    assert result.data[0]["rid"] == "ri.compass.main.space.1"
    assert result.data[0]["type"] == "namespace"
    assert result.metadata.next_page_token == "space-next"


def test_list_namespaces_empty_page_is_not_an_error() -> None:
    service, client = _service()
    client.filesystem.Space.list.return_value = SimpleNamespace(
        data=[], next_page_token=None
    )

    result = service.list_namespaces()

    assert result.data == []
    assert result.metadata.has_more is False


def test_project_templates_fail_closed_without_public_catalog() -> None:
    service, _ = _service()

    with pytest.raises(UnsupportedCapabilityError, match="no list-project-templates"):
        service.list_project_templates()


def test_malformed_namespace_page_is_reported() -> None:
    service, client = _service()
    client.filesystem.Space.list.return_value = SimpleNamespace(
        data={"not": "a list"}, next_page_token=None
    )

    with pytest.raises(RuntimeError, match="SDK page data must be a list"):
        service.list_namespaces()


def test_namespace_permission_error_is_preserved_as_runtime_error() -> None:
    service, client = _service()
    client.filesystem.Space.list.side_effect = PermissionError("denied")

    with pytest.raises(RuntimeError, match="denied"):
        service.list_namespaces()
