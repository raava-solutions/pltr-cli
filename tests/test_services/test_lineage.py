"""Tests for bounded native resource graphs."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from pltr.services.lineage import LineageService


def _service() -> tuple[LineageService, Mock]:
    client = Mock()
    client.filesystem = Mock()
    with patch("pltr.services.base.AuthManager") as auth:
        auth.return_value.get_client.return_value = client
        service = LineageService()
        service._client = client
    return service, client


def test_graph_has_stable_node_and_edge_ids_and_explicit_coverage() -> None:
    service, client = _service()
    root = SimpleNamespace(
        rid="ri.compass.main.folder.root",
        type="FOLDER",
        display_name="Root",
        path="/Root",
        parent_folder_rid=None,
    )
    child = SimpleNamespace(
        rid="ri.foundry.main.dataset.child",
        type="DATASET",
        display_name="Child",
        path="/Root/Child",
        parent_folder_rid="ri.compass.main.folder.root",
    )
    client.filesystem.Resource.get.return_value = root
    client.filesystem.Folder.children.return_value = [child]

    result = service.get_resource_graph("ri.compass.main.folder.root", max_depth=1)

    assert [node["id"] for node in result["nodes"]] == sorted(
        node["id"] for node in result["nodes"]
    )
    assert result["edges"][0]["id"].startswith("foundry:edge:child:")
    assert result["edges"][0]["source"] == "foundry:rid:ri.compass.main.folder.root"
    assert result["coverage"]["complete"] is False
    assert any("transformation" in gap for gap in result["coverage"]["gaps"])


def test_graph_paginates_edges_with_bounded_output() -> None:
    service, client = _service()
    root = SimpleNamespace(
        rid="ri.compass.main.project.root",
        type="PROJECT",
        display_name="Project",
        parent_folder_rid=None,
    )
    child_one = SimpleNamespace(rid="ri.foundry.main.dataset.a", type="DATASET")
    child_two = SimpleNamespace(rid="ri.foundry.main.dataset.b", type="DATASET")
    client.filesystem.Resource.get.return_value = root
    client.filesystem.Folder.children.return_value = [child_one, child_two]

    first = service.get_resource_graph(root.rid, max_depth=1, page_size=1)
    second = service.get_resource_graph(
        root.rid,
        max_depth=1,
        page_size=1,
        page_token=first["pagination"]["next_page_token"],
    )

    assert len(first["edges"]) == 1
    assert first["pagination"]["has_more"] is True
    assert len(second["edges"]) == 1
    assert first["edges"][0]["id"] != second["edges"][0]["id"]


def test_graph_includes_project_reference_edges() -> None:
    service, client = _service()
    project = SimpleNamespace(
        rid="ri.compass.main.project.root", type="PROJECT", parent_folder_rid=None
    )
    reference = SimpleNamespace(
        resource_rid="ri.foundry.main.dataset.imported", type="filesystem"
    )
    item = SimpleNamespace(reference=reference)
    client.filesystem.Resource.get.side_effect = [
        project,
        SimpleNamespace(
            rid=reference.resource_rid, type="DATASET", display_name="Imported"
        ),
    ]
    client.filesystem.Project.Reference.list.return_value = [item]

    result = service.get_resource_graph(project.rid, max_depth=1)

    assert any(edge["relation"] == "reference" for edge in result["edges"])


def test_graph_root_permission_error_is_actionable() -> None:
    service, client = _service()
    client.filesystem.Resource.get.side_effect = PermissionError("denied")

    with pytest.raises(RuntimeError, match="denied"):
        service.get_resource_graph("ri.foundry.main.dataset.denied")


def test_graph_rejects_malformed_page_token() -> None:
    service, _ = _service()

    with pytest.raises(ValueError, match="invalid resource graph page_token"):
        service.get_resource_graph("ri.foundry.main.dataset.1", page_token="bad")
