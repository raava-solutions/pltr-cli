"""Pinned-SDK contract gates for dependency operation provenance."""

from importlib.metadata import version
import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from foundry_sdk import _errors as sdk_errors
from foundry_sdk.v2.filesystem import models as filesystem_models
from foundry_sdk.v2.ontologies import models as ontology_models
from foundry_sdk.v2.datasets.dataset import DatasetClient
from foundry_sdk.v2.filesystem.resource import ResourceClient
from foundry_sdk.v2.ontologies.action_type_full_metadata import (
    ActionTypeFullMetadataClient,
)
from foundry_sdk.v2.ontologies.object_type import ObjectTypeClient
from foundry_sdk.v2.ontologies.query_type import QueryTypeClient
from foundry_sdk.v2.orchestration.build import BuildClient
from foundry_sdk.v2.orchestration.schedule import ScheduleClient
from foundry_sdk.v2.third_party_applications.third_party_application import (
    ThirdPartyApplicationClient,
)

from pltr.services.dependency import (
    SDK_OPERATION_SPECS,
    AnalysisContext,
    ArgumentObservation,
    DependencyGraphService,
    DependencyFatalError,
    DiscoveryBudget,
)


PINNED_OPERATIONS = {
    "object-type.get-full-metadata": (
        ObjectTypeClient.get_full_metadata,
        "client.ontologies.Ontology.ObjectType",
        "get_full_metadata",
        ("CAP-01", "CAP-16"),
    ),
    "object-type.get-outgoing-link-type": (
        ObjectTypeClient.get_outgoing_link_type,
        "client.ontologies.Ontology.ObjectType",
        "get_outgoing_link_type",
        ("CAP-01", "CAP-16"),
    ),
    "action-type.get-full-metadata": (
        ActionTypeFullMetadataClient.get,
        "client.ontologies.ActionTypeFullMetadata",
        "get",
        ("CAP-02", "CAP-16"),
    ),
    "action-type.list-full-metadata": (
        ActionTypeFullMetadataClient.list,
        "client.ontologies.ActionTypeFullMetadata",
        "list",
        ("CAP-02", "CAP-03", "CAP-13", "CAP-16"),
    ),
    "query-type.list": (
        QueryTypeClient.list,
        "client.ontologies.Ontology.QueryType",
        "list",
        ("CAP-04", "CAP-05", "CAP-13", "CAP-16"),
    ),
    "dataset.get-schedules": (
        DatasetClient.get_schedules,
        "client.datasets.Dataset",
        "get_schedules",
        ("CAP-06", "CAP-13", "CAP-16"),
    ),
    "schedule.get": (
        ScheduleClient.get,
        "client.orchestration.Schedule",
        "get",
        ("CAP-07", "CAP-16"),
    ),
    "schedule.get-affected-resources": (
        ScheduleClient.get_affected_resources,
        "client.orchestration.Schedule",
        "get_affected_resources",
        ("CAP-07", "CAP-16"),
    ),
    "schedule.runs": (
        ScheduleClient.runs,
        "client.orchestration.Schedule",
        "runs",
        ("CAP-07", "CAP-13", "CAP-16"),
    ),
    "build.get": (
        BuildClient.get,
        "client.orchestration.Build",
        "get",
        ("CAP-08", "CAP-09", "CAP-16"),
    ),
    "build.jobs": (
        BuildClient.jobs,
        "client.orchestration.Build",
        "jobs",
        ("CAP-08", "CAP-09", "CAP-13", "CAP-16"),
    ),
    "filesystem.resource.get": (
        ResourceClient.get,
        "client.filesystem.Resource",
        "get",
        ("CAP-10", "CAP-16"),
    ),
    "third-party-application.get": (
        ThirdPartyApplicationClient.get,
        "client.third_party_applications.ThirdPartyApplication",
        "get",
        ("CAP-10", "CAP-16"),
    ),
}


@pytest.mark.parametrize("operation", sorted(PINNED_OPERATIONS))
def test_operation_registry_matches_every_pinned_sdk_signature(operation):
    method, namespace, method_name, capability_ids = PINNED_OPERATIONS[operation]
    spec = SDK_OPERATION_SPECS[operation]
    parameters = inspect.signature(method).parameters

    assert spec.namespace == namespace
    assert spec.method == method_name
    assert spec.capability_ids == capability_ids
    assert spec.branch is ("branch" in parameters or "branch_name" in parameters)
    assert spec.preview is ("preview" in parameters)
    assert "request_timeout" in parameters


@pytest.mark.parametrize("operation", sorted(PINNED_OPERATIONS))
@pytest.mark.parametrize("supply_optional_arguments", [False, True])
def test_every_operation_emits_pinned_provenance_from_actual_invocation_path(
    operation, supply_optional_arguments
):
    spec = SDK_OPERATION_SPECS[operation]
    budget = DiscoveryBudget(time_budget_seconds=60)
    context = AnalysisContext.create(
        profile="prod",
        host="https://prod.example.test",
        requested_branch="requested-but-not-automatically-forwarded",
        budget=budget,
        request_timeout_seconds=29,
    )
    service = DependencyGraphService(client=SimpleNamespace())
    call = Mock(return_value={"operation": operation})
    kwargs = {}
    if supply_optional_arguments and spec.branch:
        kwargs["branch"] = "explicit-branch"
    if supply_optional_arguments and spec.preview:
        kwargs["preview"] = True

    response, operation_id = service._invoke_sdk(
        context, operation, call, kwargs, target="target"
    )

    assert response == {"operation": operation}
    assert call.call_args.kwargs["request_timeout"] == 29
    provenance = context.operation_provenance[operation_id]
    assert provenance.read_context_id == context.read_context.id
    assert provenance.sdk_namespace == spec.namespace
    assert provenance.sdk_method == spec.method
    assert provenance.capability_ids == spec.capability_ids
    assert (
        provenance.invocation_sdk_version == version("foundry-platform-sdk") == "1.95.0"
    )
    assert provenance.request_timeout_seconds == 29
    assert provenance.invoked_at.endswith("Z")
    assert provenance.observed_at.endswith("Z")
    if spec.branch:
        expected = (
            ArgumentObservation("explicit", "explicit-branch")
            if supply_optional_arguments
            else ArgumentObservation("server-default")
        )
        assert provenance.branch_argument == expected
    else:
        assert provenance.branch_argument == ArgumentObservation("not-applicable")
        assert "branch" not in call.call_args.kwargs
    if spec.preview:
        expected = (
            ArgumentObservation("explicit", True)
            if supply_optional_arguments
            else ArgumentObservation("server-default")
        )
        assert provenance.preview_argument == expected
    else:
        assert provenance.preview_argument == ArgumentObservation("not-applicable")
        assert "preview" not in call.call_args.kwargs


def _resolver_fixture():
    object_type = ontology_models.ObjectTypeV2.model_construct(
        api_name="Employee",
        display_name="Employee",
        properties={"name": SimpleNamespace()},
    )
    object_metadata = ontology_models.ObjectTypeFullMetadata.model_construct(
        object_type=object_type,
        link_types=[],
        implements_interfaces=[],
        implements_interfaces2={},
        shared_property_type_mapping={},
    )
    link = ontology_models.LinkTypeSideV2.model_construct(
        api_name="manager", object_type_api_name="Employee"
    )
    action = ontology_models.ActionTypeFullMetadata.model_construct(
        action_type=ontology_models.ActionTypeV2.model_construct(
            api_name="HireEmployee"
        ),
        full_logic_rules=[],
    )
    query = ontology_models.QueryTypeV2.model_construct(api_name="FindEmployee")
    resource = filesystem_models.Resource.model_construct(
        rid="ri.foundry.main.dataset.employee",
        display_name="Employee dataset",
        type="dataset",
    )
    get_full_metadata = Mock(return_value=object_metadata)
    get_link = Mock(return_value=link)
    get_action = Mock(return_value=action)
    list_queries = Mock(
        return_value=SimpleNamespace(data=[query], next_page_token=None)
    )
    get_resource = Mock(return_value=resource)
    client = SimpleNamespace(
        ontologies=SimpleNamespace(
            ActionTypeFullMetadata=SimpleNamespace(get=get_action),
            Ontology=SimpleNamespace(
                ObjectType=SimpleNamespace(
                    get_full_metadata=get_full_metadata,
                    get_outgoing_link_type=get_link,
                ),
                QueryType=SimpleNamespace(list=list_queries),
            ),
        ),
        filesystem=SimpleNamespace(Resource=SimpleNamespace(get=get_resource)),
    )
    return client, {
        "object": get_full_metadata,
        "link": get_link,
        "action": get_action,
        "query": list_queries,
        "resource": get_resource,
    }


@pytest.mark.parametrize(
    ("kind", "resolve", "expected_identifiers", "operation"),
    [
        (
            "object-type",
            lambda service, context: service.resolve_object_type(
                context, "ontology", "Employee"
            ),
            {"ontology_rid": "ontology", "object_type": "Employee"},
            "object-type.get-full-metadata",
        ),
        (
            "property",
            lambda service, context: service.resolve_property(
                context, "ontology", "Employee", "name"
            ),
            {
                "ontology_rid": "ontology",
                "object_type": "Employee",
                "property": "name",
            },
            "object-type.get-full-metadata",
        ),
        (
            "link-type",
            lambda service, context: service.resolve_link_type(
                context, "ontology", "Employee", "manager"
            ),
            {
                "ontology_rid": "ontology",
                "object_type": "Employee",
                "link_type": "manager",
            },
            "object-type.get-outgoing-link-type",
        ),
        (
            "action-type",
            lambda service, context: service.resolve_action_type(
                context, "ontology", "HireEmployee"
            ),
            {"ontology_rid": "ontology", "action_type": "HireEmployee"},
            "action-type.get-full-metadata",
        ),
        (
            "query-type",
            lambda service, context: service.resolve_query_type(
                context, "ontology", "FindEmployee"
            ),
            {"ontology_rid": "ontology", "query_type": "FindEmployee"},
            "query-type.list",
        ),
        (
            "dataset",
            lambda service, context: service.resolve_resource(
                context, "ri.foundry.main.dataset.employee"
            ),
            {
                "resource_rid": "ri.foundry.main.dataset.employee",
                "resource_type": "dataset",
            },
            "filesystem.resource.get",
        ),
    ],
)
def test_all_six_real_target_resolvers_preserve_identity_and_provenance(
    kind, resolve, expected_identifiers, operation
):
    client, _ = _resolver_fixture()
    service = DependencyGraphService(client=client)
    context = AnalysisContext.create(
        profile="prod",
        host="https://prod.example.test",
        ontology_rid="ontology",
        requested_branch="feature",
    )

    target = resolve(service, context)

    assert target.kind == kind
    assert target.identifiers == expected_identifiers
    node = context.nodes[target.node_id]
    assert node.is_target is True
    assert node.read_context_id == context.read_context.id
    matching = [
        item
        for item in context.operation_provenance.values()
        if (item.sdk_namespace, item.sdk_method)
        == (
            SDK_OPERATION_SPECS[operation].namespace,
            SDK_OPERATION_SPECS[operation].method,
        )
    ]
    assert matching
    assert all(item.invocation_sdk_version == "1.95.0" for item in matching)
    assert all(item.request_timeout_seconds > 0 for item in matching)
    if SDK_OPERATION_SPECS[operation].branch:
        assert matching[-1].branch_argument == ArgumentObservation(
            "explicit", "feature"
        )
    timeout = matching[-1].request_timeout_seconds
    exercised_calls = {
        "object-type": client.ontologies.Ontology.ObjectType.get_full_metadata,
        "property": client.ontologies.Ontology.ObjectType.get_full_metadata,
        "link-type": client.ontologies.Ontology.ObjectType.get_outgoing_link_type,
        "action-type": client.ontologies.ActionTypeFullMetadata.get,
        "query-type": client.ontologies.Ontology.QueryType.list,
        "dataset": client.filesystem.Resource.get,
    }
    expected_kwargs = {
        "object-type": {
            "ontology": "ontology",
            "object_type": "Employee",
            "preview": True,
            "branch": "feature",
            "request_timeout": timeout,
        },
        "property": {
            "ontology": "ontology",
            "object_type": "Employee",
            "preview": True,
            "branch": "feature",
            "request_timeout": timeout,
        },
        "link-type": {
            "ontology": "ontology",
            "object_type": "Employee",
            "link_type": "manager",
            "branch": "feature",
            "request_timeout": timeout,
        },
        "action-type": {
            "ontology": "ontology",
            "action_type": "HireEmployee",
            "preview": True,
            "branch": "feature",
            "request_timeout": timeout,
        },
        "query-type": {
            "ontology": "ontology",
            "page_size": 100,
            "branch": "feature",
            "request_timeout": timeout,
        },
        "dataset": {
            "resource_rid": "ri.foundry.main.dataset.employee",
            "request_timeout": timeout,
        },
    }
    exercised_calls[kind].assert_called_once_with(**expected_kwargs[kind])


def test_target_resolvers_fail_closed_for_missing_members_and_permissions():
    client, calls = _resolver_fixture()
    service = DependencyGraphService(client=client)
    missing_property_context = AnalysisContext.create(profile="prod")
    with pytest.raises(DependencyFatalError) as missing_property:
        service.resolve_property(
            missing_property_context, "ontology", "Employee", "missing"
        )
    assert missing_property.value.error_class == "not-found"

    missing_query_context = AnalysisContext.create(profile="prod")
    with pytest.raises(DependencyFatalError) as missing_query:
        service.resolve_query_type(missing_query_context, "ontology", "MissingQuery")
    assert missing_query.value.error_class == "not-found"

    calls["link"].side_effect = sdk_errors.NotFoundError({})
    missing_link_context = AnalysisContext.create(profile="prod")
    with pytest.raises(DependencyFatalError) as missing_link:
        service.resolve_link_type(
            missing_link_context, "ontology", "Employee", "missingLink"
        )
    assert missing_link.value.error_class == "not-found"
    assert missing_link.value.operation == "object-type.get-outgoing-link-type"

    calls["action"].side_effect = sdk_errors.PermissionDeniedError({})
    permission_context = AnalysisContext.create(profile="prod")
    with pytest.raises(DependencyFatalError) as permission:
        service.resolve_action_type(permission_context, "ontology", "HireEmployee")
    assert permission.value.error_class == "permission-denied"
    assert permission.value.operation == "action-type.get-full-metadata"
