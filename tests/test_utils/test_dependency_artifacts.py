import json
import os
import hashlib
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from pltr.utils.dependency_artifacts import (
    ArtifactWriteError,
    artifact_identity,
    default_artifact_path,
    serialize_dependency_result,
    write_dependency_artifact,
)


def result_fixture():
    return {
        "target": {"id": "object:Employee", "kind": "object-type"},
        "read_contexts": [
            {
                "id": "ctx-1",
                "profile": "prod",
                "host_fingerprint": "f9137f6af01050c3",
            }
        ],
        "graph": {
            "nodes": [
                {"id": "object:Employee"},
                {"id": "query:findEmployee"},
            ],
            "edges": [
                {
                    "id": "edge-1",
                    "source": "query:findEmployee",
                    "target": "object:Employee",
                }
            ],
        },
        "paths": [
            {
                "id": "path-1",
                "node_ids": ["object:Employee", "query:findEmployee"],
            }
        ],
        "coverage_records": [
            {
                "id": "coverage-1",
                "surface": "query-metadata",
                "status": "partial",
            }
        ],
        "gaps": [
            {
                "id": "gap-1",
                "reason_code": "unsupported",
                "locator": "query.output.type",
            }
        ],
        "errors": [{"id": "error-1", "error_class": "timeout", "message": "timed out"}],
        "evidence": [
            {
                "id": "ev-1",
                "operation_provenance_id": "op-1",
                "locator": "objectType",
            }
        ],
        "operation_provenance": [
            {
                "id": "op-1",
                "sdk_namespace": "client.ontologies.ObjectType",
                "sdk_method": "get_full_metadata",
                "capability_ids": ["CAP-01", "CAP-16"],
                "invocation_sdk_version": "1.95.0",
                "invoked_at": "2026-07-17T10:00:00+00:00",
                "observed_at": "2026-07-17T10:00:01+00:00",
                "branch_argument": {"mode": "explicit", "value": "dev"},
                "preview_argument": {"mode": "explicit", "value": True},
                "request_timeout_seconds": 30.0,
                "known_limitations": [],
            }
        ],
        "budget": {
            "used": {"requests": 1, "pages": 1, "items": 2, "nodes": 2},
            "limits": {"requests": 200, "pages": 100, "items": 10000, "nodes": 150},
        },
    }


def test_serialize_dependency_result_preserves_internal_transport_and_inconclusive():
    result = {
        "operation_provenance": [
            {
                "id": "operation-acp-04",
                "transport": "conjure-rest",
                "acp_id": "ACP-04",
            }
        ],
        "coverage": [
            {
                "id": "coverage-sdk",
                "surface": "query-related-function-metadata",
                "status": "partial",
            },
            {
                "id": "coverage-acp-04",
                "surface": "property-column-mapping",
                "status": "inconclusive",
            },
        ],
        "gaps": [
            {
                "id": "gap-acp-04",
                "surface": "property-column-mapping",
                "coverage": "inconclusive",
                "reason_code": "response-shape-drift",
            }
        ],
    }

    serialized = serialize_dependency_result(result)

    assert serialized["operation_provenance"][0]["transport"] == "conjure-rest"
    assert [record["status"] for record in serialized["coverage"]] == [
        "partial",
        "inconclusive",
    ]
    assert serialized["gaps"][0]["coverage"] == "inconclusive"


def independent_payload_digest(document):
    payload = {key: value for key, value in document.items() if key != "artifact"}
    agent = payload.get("agent")
    if isinstance(agent, dict):
        payload["agent"] = {
            key: value for key, value in agent.items() if key != "artifact_reference"
        }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_identity_excludes_only_artifact_metadata():
    result = result_fixture()
    first = artifact_identity(result)
    result["artifact"] = {"path": "/different/path", "created_at": "later"}
    assert artifact_identity(result) == first
    result["operation_provenance"][0]["branch_argument"]["value"] = "main"
    assert artifact_identity(result) != first


def test_default_path_uses_xdg_state_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert (
        default_artifact_path("dep-123")
        == (tmp_path / "pltr" / "dependency" / "dep-123.json").resolve()
    )


def test_write_is_atomic_complete_and_mode_0600(tmp_path):
    destination = tmp_path / "nested" / "graph.json"
    with patch("os.replace", wraps=os.replace) as replace:
        metadata = write_dependency_artifact(result_fixture(), destination)

    replace.assert_called_once()
    temporary, final = replace.call_args.args
    assert Path(temporary).parent == destination.parent
    assert Path(final) == destination
    if os.name != "nt":
        assert oct(destination.stat().st_mode & 0o777) == "0o600"
    document = json.loads(destination.read_text())
    expected = result_fixture()
    assert {
        key: value for key, value in document.items() if key != "artifact"
    } == expected
    assert document["artifact"] == metadata
    assert metadata["path"] == str(destination.resolve())
    expected_digest = independent_payload_digest(document)
    assert metadata["sha256"] == expected_digest
    assert metadata["analysis_id"] == f"dep-{expected_digest[:20]}"


def test_identical_content_has_stable_digest_and_analysis_id(tmp_path):
    first = write_dependency_artifact(result_fixture(), tmp_path / "first.json")
    second = write_dependency_artifact(result_fixture(), tmp_path / "second.json")
    assert first["sha256"] == second["sha256"]
    assert first["analysis_id"] == second["analysis_id"]


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("graph", "nodes"),
        ("graph", "edges"),
        ("paths", None),
        ("coverage_records", None),
        ("gaps", None),
        ("errors", None),
        ("evidence", None),
        ("operation_provenance", None),
    ],
)
def test_identity_covers_every_retained_evidence_collection(collection, field):
    baseline = result_fixture()
    changed = deepcopy(baseline)
    target = changed[collection][field] if field is not None else changed[collection]
    target.append({"id": "additional-record"})
    assert artifact_identity(changed) != artifact_identity(baseline)


@pytest.mark.parametrize(
    "field",
    ["target", "read_contexts", "budget"],
)
def test_identity_covers_every_other_retained_field(field):
    baseline = result_fixture()
    changed = deepcopy(baseline)
    if isinstance(changed[field], list):
        changed[field].append({"id": "additional-record"})
    else:
        changed[field]["digest_probe"] = "changed"
    assert artifact_identity(changed) != artifact_identity(baseline)


def test_write_failure_is_typed(tmp_path):
    destination = tmp_path / "graph.json"
    with patch("os.replace", side_effect=OSError("read only")):
        with pytest.raises(ArtifactWriteError) as error:
            write_dependency_artifact(result_fixture(), destination)
    assert error.value.error_class == "artifact-write-failed"
    assert not list(tmp_path.iterdir())


def test_artifact_provenance_schema_and_evidence_references_are_exact(tmp_path):
    result = result_fixture()
    result["evidence"] = [
        {
            "id": "ev-1",
            "operation_provenance_id": "op-1",
            "locator": "objectType",
            "field_path": "objectType",
            "raw_type": "ObjectTypeFullMetadata",
        }
    ]
    destination = tmp_path / "graph.json"
    write_dependency_artifact(result, destination)
    document = json.loads(destination.read_text())
    operations = {item["id"]: item for item in document["operation_provenance"]}
    assert {
        item["operation_provenance_id"] for item in document["evidence"]
    } <= operations.keys()
    for operation in operations.values():
        assert operation["capability_ids"]
        assert operation["invocation_sdk_version"] == "1.95.0"
        assert operation["invoked_at"] and operation["observed_at"]
        assert operation["request_timeout_seconds"] == 30.0
        for argument in ("branch_argument", "preview_argument"):
            assert operation[argument]["mode"] in {
                "explicit",
                "server-default",
                "not-applicable",
            }


def test_agent_block_round_trips_additively_without_losing_nested_values(tmp_path):
    result = result_fixture()
    result["agent"] = {
        "schema_version": "dependency-agent-v1",
        "status": "needs-verification",
        "impacts": [
            {
                "impact_id": "impact-1",
                "member_path_ids": ("path-1", "path-2"),
                "all_member_evidence_ids": {"ev-1", "ev-2"},
            }
        ],
        "verification": {
            "must_verify_before_merge": [{"reason": "budget-truncation"}],
            "should_verify_before_deploy": [],
            "unsupported_manual_surfaces": [],
        },
        "diff": {
            "added_edges": ["edge-2"],
            "removed_edges": [{"edge_id": "edge-3", "possibly_budget_truncated": True}],
        },
    }

    serialized = serialize_dependency_result(result)
    destination = tmp_path / "agent-graph.json"
    metadata = write_dependency_artifact(serialized, destination)
    document = json.loads(destination.read_text())

    artifact_reference = document["agent"].pop("artifact_reference")
    assert artifact_reference == {
        "artifact_id": metadata["analysis_id"],
        "path": metadata["path"],
        "sha256": metadata["sha256"],
    }
    assert document["agent"] == serialized["agent"]
    assert document["agent"]["impacts"][0]["member_path_ids"] == [
        "path-1",
        "path-2",
    ]
    assert document["agent"]["impacts"][0]["all_member_evidence_ids"] == [
        "ev-1",
        "ev-2",
    ]
    assert {
        key: value
        for key, value in document.items()
        if key not in {"agent", "artifact"}
    } == {key: value for key, value in serialized.items() if key != "agent"}


def test_agent_artifact_reference_is_excluded_from_identity_and_replaced_on_write(
    tmp_path,
):
    result = result_fixture()
    result["agent"] = {
        "schema_version": "dependency-agent-v1",
        "artifact_reference": {
            "artifact_id": "dep-stale",
            "path": "/stale/path.json",
            "sha256": "stale",
        },
    }
    identity = artifact_identity(result)
    result["agent"]["artifact_reference"] = {
        "artifact_id": "dep-other",
        "path": "/other/path.json",
        "sha256": "other",
    }
    assert artifact_identity(result) == identity

    destination = tmp_path / "graph.json"
    metadata = write_dependency_artifact(result, destination)
    document = json.loads(destination.read_text())
    assert artifact_identity(document) == identity
    assert document["agent"]["artifact_reference"] == {
        "artifact_id": metadata["analysis_id"],
        "path": metadata["path"],
        "sha256": metadata["sha256"],
    }
