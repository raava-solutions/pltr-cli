"""Parity contracts for dependency transport providers."""

from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pltr.services.dependency import (
    SDK_OPERATION_SPECS,
    AnalysisContext,
    DependencyGraphService,
    DiscoveryBudget,
)
from pltr.services.dependency_providers import ProviderResult, SdkProvider


def _context() -> AnalysisContext:
    return AnalysisContext.create(
        profile="test",
        host="https://example.test",
        budget=DiscoveryBudget(time_budget_seconds=60),
        request_timeout_seconds=29,
    )


@pytest.mark.parametrize(
    "operation",
    [
        "object-type.get-full-metadata",
        "dataset.get-schedules",
        "build.get",
    ],
)
def test_sdk_provider_matches_legacy_delegator_provenance_and_budget(operation):
    spec = SDK_OPERATION_SPECS[operation]
    provider_context = _context()
    delegator_context = _context()
    provider_call = Mock(return_value={"operation": operation})
    delegator_call = Mock(return_value={"operation": operation})
    kwargs = {}
    if spec.branch:
        kwargs["branch"] = "feature"
    if spec.preview:
        kwargs["preview"] = True

    provider_result = SdkProvider(provider_call).invoke(
        provider_context, operation, kwargs, target="target"
    )
    payload, delegator_operation_id = DependencyGraphService(
        client=SimpleNamespace()
    )._invoke_sdk(
        delegator_context,
        operation,
        delegator_call,
        kwargs,
        target="target",
    )

    assert provider_result.payload == payload
    assert provider_call.call_args.kwargs == delegator_call.call_args.kwargs
    assert provider_call.call_args.kwargs["request_timeout"] == 29
    assert (
        provider_context.budget.used_requests
        == delegator_context.budget.used_requests
        == 1
    )
    provider_provenance = asdict(
        provider_context.operation_provenance[provider_result.operation_provenance_id]
    )
    delegator_provenance = asdict(
        delegator_context.operation_provenance[delegator_operation_id]
    )
    for dynamic_field in ("id", "invoked_at", "observed_at"):
        provider_provenance.pop(dynamic_field)
        delegator_provenance.pop(dynamic_field)
    assert provider_provenance == delegator_provenance
    assert provider_provenance["transport"] == "sdk"


@pytest.mark.parametrize(
    ("operation", "kwargs", "message"),
    [
        ("build.get", {"branch": "feature"}, "does not accept branch"),
        ("query-type.list", {"preview": True}, "does not accept preview"),
    ],
)
def test_sdk_provider_rejects_unsupported_branch_and_preview(
    operation, kwargs, message
):
    with pytest.raises(ValueError, match=message):
        SdkProvider(Mock()).invoke(_context(), operation, kwargs, target="target")


def test_sdk_provider_result_has_unchanged_sdk_semantics():
    result = SdkProvider(Mock(return_value={"ok": True})).invoke(
        _context(), "build.get", {}, target="target"
    )

    assert isinstance(result, ProviderResult)
    assert (result.result_semantics, result.positive_control_status) == (
        "ok",
        "not-run",
    )
