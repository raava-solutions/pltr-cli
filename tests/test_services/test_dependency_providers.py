"""Parity contracts for dependency transport providers."""

from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pltr.services.dependency import (
    SDK_OPERATION_SPECS,
    AnalysisContext,
    DependencyGraphService,
    DependencyTarget,
    DiscoveryBudget,
)
from pltr.services.dependency_internal_specs import (
    ACP_OPERATION_SPECS,
    CONJURE_POST_OPERATION_SPECS,
    CONSUMER_CHARACTERIZATION_OPERATION_SPECS,
    GRAPHQL_OPERATION_SPECS,
    TRANSFORM_LINEAGE_GET_OPERATION_SPECS,
)
from pltr.services.dependency_providers import (
    ConjureRestProvider,
    ProviderResult,
    SdkProvider,
)
from pltr.services.foundry_internal_client import GraphQLResult


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


def _all_internal_specs():
    specs = {}
    for registry in (
        ACP_OPERATION_SPECS,
        TRANSFORM_LINEAGE_GET_OPERATION_SPECS,
        CONJURE_POST_OPERATION_SPECS,
        CONSUMER_CHARACTERIZATION_OPERATION_SPECS,
        GRAPHQL_OPERATION_SPECS,
    ):
        specs.update(registry)
    return specs


@pytest.mark.parametrize("acp_id", [f"ACP-{index:02d}" for index in range(1, 9)])
def test_every_acp_invocation_records_resolvable_transport_provenance(acp_id):
    spec = _all_internal_specs()[acp_id]
    internal_client = SimpleNamespace(
        conjure=Mock(return_value=(200, {}, "{}")),
        graphql=Mock(
            return_value=GraphQLResult(
                data={
                    "objectTypeV2": {
                        "rid": "ri.object-type.target",
                        "dependents": {"values": [], "nextPageToken": None},
                    }
                }
            )
        ),
    )
    provider = ConjureRestProvider(internal_client)
    service = DependencyGraphService(
        client=SimpleNamespace(),
        conjure_provider=provider,
    )
    context = AnalysisContext.create(
        profile="test",
        host="https://example.test",
        request_timeout_seconds=17,
    )

    if acp_id in TRANSFORM_LINEAGE_GET_OPERATION_SPECS:
        service._invoke_transform_lineage_get(
            context,
            spec,
            spec.path,
            target="dataset:target",
        )
    elif acp_id in CONJURE_POST_OPERATION_SPECS:
        service._invoke_conjure_post(context, spec, {})
    elif acp_id in CONSUMER_CHARACTERIZATION_OPERATION_SPECS:
        service._invoke_consumer_internal_query(
            context,
            spec,
            spec.path,
            {},
            target="object-type:target",
        )
    elif acp_id in GRAPHQL_OPERATION_SPECS:
        node = service._add_node(
            context,
            "object-type",
            "Target",
            {"object_type": "Target"},
            is_target=True,
        )
        target = DependencyTarget(
            "object-type",
            {"object_type": "Target"},
            "Target",
            node.id,
        )
        metadata = SimpleNamespace(
            object_type=SimpleNamespace(rid="ri.object-type.target"),
            link_types=[],
        )
        service._collect_object_type_consumers(target, context, metadata)
    else:
        provider.invoke(
            context,
            spec.acp_id,
            spec.verb,
            spec.path,
            None,
            target=f"{spec.target_kind}:target",
        )

    matching_provenance = [
        operation
        for operation in context.operation_provenance.values()
        if operation.acp_id == acp_id
    ]
    assert len(matching_provenance) == 1
    provenance = matching_provenance[0]
    assert context.operation_provenance[provenance.id] is provenance
    assert provenance.acp_id == acp_id
    assert provenance.transport == spec.transport
    assert provenance.http_verb == spec.verb
    assert provenance.path == spec.path
    assert provenance.contract_pins == dict(spec.contract_pins)
    assert provenance.request_timeout_seconds == 17
    assert datetime.fromisoformat(provenance.invoked_at.replace("Z", "+00:00"))
    assert datetime.fromisoformat(provenance.observed_at.replace("Z", "+00:00"))

    if spec.transport == "graphql-sse":
        assert provenance.operation_name == spec.operation_name
        assert provenance.document_sha256 == spec.document_sha256
        assert internal_client.graphql.call_args.kwargs["request_timeout"] == 17
    else:
        assert provenance.operation_name is None
        assert provenance.document_sha256 is None
        assert internal_client.conjure.call_args.kwargs["request_timeout"] == 17
