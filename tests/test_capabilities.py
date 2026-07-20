"""Tests for the native agent-first capability manifest."""

from dataclasses import replace

import pytest

from pltr.capabilities import (
    CAPABILITIES,
    ManifestValidationError,
    capability_manifest,
    validate_capabilities,
)


def test_baseline_contains_all_tools_and_workflows() -> None:
    manifest = capability_manifest()

    assert manifest["catalog"]["tool_count"] == 72
    assert manifest["catalog"]["workflow_count"] == 1
    assert manifest["counts"]["total"] == 73
    assert {item["capability_id"] for item in manifest["capabilities"]} >= {
        "get_resource_graph",
        "preview_transform",
    }


def test_duplicate_capability_ids_are_rejected() -> None:
    duplicate = replace(CAPABILITIES[1], capability_id=CAPABILITIES[0].capability_id)

    with pytest.raises(ManifestValidationError, match="duplicate capability ids"):
        validate_capabilities((CAPABILITIES[0], duplicate, *CAPABILITIES[2:]))


def test_missing_command_mapping_is_rejected() -> None:
    invalid = replace(CAPABILITIES[0], command="")

    with pytest.raises(ManifestValidationError, match="command is required"):
        validate_capabilities((invalid, *CAPABILITIES[1:]))


def test_missing_api_evidence_is_rejected() -> None:
    invalid = replace(CAPABILITIES[0], api_evidence="")

    with pytest.raises(ManifestValidationError, match="api_evidence is required"):
        validate_capabilities((invalid, *CAPABILITIES[1:]))


def test_invalid_status_is_rejected() -> None:
    invalid = replace(CAPABILITIES[0], status="stale")

    with pytest.raises(ManifestValidationError, match="status is invalid"):
        validate_capabilities((invalid, *CAPABILITIES[1:]))


def test_unsupported_capability_requires_a_reason() -> None:
    invalid = replace(CAPABILITIES[0], status="unsupported")

    with pytest.raises(
        ManifestValidationError, match="blocked_reason is required for unsupported"
    ):
        validate_capabilities((invalid, *CAPABILITIES[1:]))


def test_blocked_capability_can_be_recorded_with_a_reason() -> None:
    blocked = replace(
        CAPABILITIES[0],
        status="blocked",
        blocked_reason="SDK capability audit is pending",
    )

    validate_capabilities((blocked, *CAPABILITIES[1:]))
    manifest = capability_manifest((blocked, *CAPABILITIES[1:]))
    assert (
        manifest["counts"]["blocked"]
        == sum(entry.status == "blocked" for entry in CAPABILITIES) + 1
    )
