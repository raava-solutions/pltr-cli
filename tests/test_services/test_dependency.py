"""Contract tests for bounded Foundry dependency discovery."""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import get_args
from unittest.mock import Mock

import pytest
from foundry_sdk import _errors as sdk_errors
from foundry_sdk.v2.core import models as core_models
from foundry_sdk.v2.filesystem import models as filesystem_models
from foundry_sdk.v2.ontologies import models as ontology_models
from foundry_sdk.v2.orchestration import models as orchestration_models

from pltr.services.dependency import (
    AGENT_SCHEMA_VERSION,
    CAPABILITY_IDS,
    ACTION_LOGIC_RULE_TYPES,
    BLAST_RADIUS_WEIGHT_TABLE_VERSION,
    CHANGE_TYPES,
    IMPACT_CATEGORIES,
    IMPACT_CATEGORY_BASE,
    IMPACT_CATEGORY_CHANGE_OVERRIDES,
    QUERY_DATA_TYPE_TYPES,
    RELATION_KINDS,
    STATIC_SURFACES,
    MATRIX_GAPS,
    RELEASE_RISK_WEIGHT_TABLE_VERSION,
    SDK_OPERATION_SPECS,
    AnalysisContext,
    ArgumentObservation,
    BudgetExhausted,
    DependencyGraphService,
    DependencyFatalError,
    DependencyTarget,
    DiscoveryBudget,
    METADATA_WALK_MAX_DEPTH,
    OBJECT_TYPE_CONSUMER_SURFACE,
    TRANSFORM_DATASET_LINEAGE_SURFACE,
    OperationProvenance,
    classify_exception,
)
from pltr.services.orchestration import OrchestrationService
from pltr.utils.dependency_artifacts import serialize_dependency_result


def context(**budget_values):
    return AnalysisContext.create(
        profile="test",
        host="https://example.palantirfoundry.com",
        ontology_rid="ri.ontology.main.ontology.test",
        requested_branch="feature",
        budget=DiscoveryBudget(**budget_values),
        request_timeout_seconds=30,
    )


def test_operation_registry_is_closed_and_capability_backed():
    expected = {
        "object-type.get-full-metadata",
        "object-type.get-outgoing-link-type",
        "action-type.get-full-metadata",
        "action-type.list-full-metadata",
        "query-type.list",
        "dataset.get-schedules",
        "schedule.get",
        "schedule.get-affected-resources",
        "schedule.runs",
        "build.get",
        "build.jobs",
        "filesystem.resource.get",
        "third-party-application.get",
    }
    assert set(SDK_OPERATION_SPECS) == expected
    assert all(spec.capability_ids for spec in SDK_OPERATION_SPECS.values())
    assert all(
        set(spec.capability_ids) <= CAPABILITY_IDS
        for spec in SDK_OPERATION_SPECS.values()
    )
    assert SDK_OPERATION_SPECS["action-type.get-full-metadata"].branch is True
    assert SDK_OPERATION_SPECS["action-type.get-full-metadata"].preview is True
    assert SDK_OPERATION_SPECS["query-type.list"].branch is True
    assert SDK_OPERATION_SPECS["query-type.list"].preview is False
    assert SDK_OPERATION_SPECS["dataset.get-schedules"].branch is True
    assert SDK_OPERATION_SPECS["dataset.get-schedules"].preview is False
    assert SDK_OPERATION_SPECS["build.get"].branch is False
    assert SDK_OPERATION_SPECS["build.get"].preview is False


def test_phase_a_property_column_graph_model_is_registered():
    assert RELATION_KINDS["column-backs-property"] == (
        "dependency-flow",
        "source_to_target",
    )


@pytest.mark.parametrize(
    ("relation_kind", "source_kind", "target_kind"),
    [
        ("transform-builds-dataset", "transform-jobspec", "dataset"),
        ("dataset-feeds-transform", "dataset", "transform-jobspec"),
        ("code-repo-builds-dataset", "code-repo", "dataset"),
    ],
)
def test_u5_relation_kinds_round_trip_as_provider_to_consumer_edges(
    relation_kind, source_kind, target_kind
):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    source = service._add_node(
        analysis, source_kind, "source", {"resource_rid": "ri.source"}
    )
    target = service._add_node(
        analysis, target_kind, "target", {"resource_rid": "ri.target"}
    )

    edge = service._add_edge(
        analysis, source.id, target.id, relation_kind, ["evidence-u5"]
    )

    assert edge.source == source.id
    assert edge.target == target.id
    assert edge.traversal_class == "dependency-flow"
    assert edge.intrinsic_orientation == "source_to_target"


def test_u5_edges_keep_relation_registration_and_traversal_guards(monkeypatch):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    source = service._add_node(
        analysis, "code-repo", "source", {"resource_rid": "ri.source"}
    )
    target = service._add_node(
        analysis, "dataset", "target", {"resource_rid": "ri.target"}
    )

    with pytest.raises(ValueError, match="unregistered relation kind"):
        service._add_edge(
            analysis, source.id, target.id, "not-registered", ["evidence-u5"]
        )

    service._add_edge(
        analysis,
        source.id,
        target.id,
        "code-repo-builds-dataset",
        ["evidence-u5"],
    )
    monkeypatch.setitem(
        RELATION_KINDS,
        "code-repo-builds-dataset",
        ("adjacent-structural", "source_to_target"),
    )
    with pytest.raises(ValueError, match="conflicting intrinsic relation definition"):
        service._add_edge(
            analysis,
            source.id,
            target.id,
            "code-repo-builds-dataset",
            ["evidence-u5-new"],
        )


def test_transform_dataset_surface_is_dataset_only_and_live_provider_aware():
    assert TRANSFORM_DATASET_LINEAGE_SURFACE == "transform-dataset-lineage"
    assert (
        MATRIX_GAPS["dataset"][TRANSFORM_DATASET_LINEAGE_SURFACE]
        == "unsupported-transform-dataset-lineage"
    )
    assert all(
        TRANSFORM_DATASET_LINEAGE_SURFACE not in surfaces
        for kind, surfaces in MATRIX_GAPS.items()
        if kind != "dataset"
    )


def _internal_empty_coverage_record(*, operation="ACP-01"):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "dataset", "dataset", {"resource_rid": "ri.dataset"}
    )
    record = service._coverage_record(
        analysis,
        "dataset",
        TRANSFORM_DATASET_LINEAGE_SURFACE,
        node.id,
        operation=operation,
        transport="conjure-rest",
        empty_is_inconclusive=True,
    )
    return service, record


@pytest.mark.parametrize(
    ("broken_term", "broken_value"),
    [
        ("operation", "ACP-03"),
        ("reason_code", "different-reason"),
        ("positive_control_status", "not-run"),
        ("existence_confirmed", False),
    ],
)
def test_finish_coverage_rejects_internal_empty_when_one_sanction_term_is_broken(
    broken_term, broken_value
):
    values = {
        "operation": "ACP-01",
        "reason_code": "authoritative-empty-no-producer",
        "positive_control_status": "passed",
        "existence_confirmed": True,
    }
    values[broken_term] = broken_value
    service, record = _internal_empty_coverage_record(operation=values["operation"])

    with pytest.raises(ValueError, match="internal coverage cannot be covered-empty"):
        service._finish_coverage(
            record,
            "covered-empty",
            reason_code=values["reason_code"],
            positive_control_status=values["positive_control_status"],
            existence_confirmed=values["existence_confirmed"],
        )


def test_finish_coverage_accepts_internal_empty_with_all_sanction_terms():
    service, record = _internal_empty_coverage_record()

    service._finish_coverage(
        record,
        "covered-empty",
        reason="authoritative-empty-no-producer",
        reason_code="authoritative-empty-no-producer",
        positive_control_status="passed",
        existence_confirmed=True,
    )
    assert record.status == "covered-empty"
    assert record.reason_code == "authoritative-empty-no-producer"


@pytest.mark.parametrize(
    "relation_kind",
    ["object-consumed-by-app", "object-consumed-by-workshop"],
)
def test_object_consumer_relation_kinds_are_provider_to_consumer_dependency_flow(
    relation_kind,
):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    provider = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}
    )
    consumer_kind = (
        "application"
        if relation_kind == "object-consumed-by-app"
        else "workshop-module"
    )
    consumer = service._add_node(
        analysis,
        consumer_kind,
        "consumer",
        {"resource_rid": f"ri.test.{consumer_kind}.consumer"},
    )

    edge = service._add_edge(
        analysis, provider.id, consumer.id, relation_kind, ["evidence-acp-05"]
    )

    assert edge.source == provider.id
    assert edge.target == consumer.id
    assert edge.traversal_class == "dependency-flow"
    assert edge.intrinsic_orientation == "source_to_target"


def test_declared_link_observations_union_sdk_and_internal_evidence():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    source = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}
    )
    target = service._add_node(
        analysis, "object-type", "Department", {"object_type": "Department"}
    )

    first = service._add_edge(
        analysis, source.id, target.id, "declared-link", ["evidence-sdk"]
    )
    second = service._add_edge(
        analysis, source.id, target.id, "declared-link", ["evidence-acp-05"]
    )

    assert second.id == first.id
    assert len(analysis.edges) == 1
    assert second.evidence_ids == ("evidence-acp-05", "evidence-sdk")
    assert "object-consumed-by-link" not in RELATION_KINDS


def test_object_type_consumer_surface_is_closed_and_terminal_without_provider():
    assert OBJECT_TYPE_CONSUMER_SURFACE == "object-type-consumers"
    assert (
        MATRIX_GAPS["object-type"][OBJECT_TYPE_CONSUMER_SURFACE]
        == "unsupported-object-type-consumers"
    )
    assert all(
        OBJECT_TYPE_CONSUMER_SURFACE not in surfaces
        for kind, surfaces in MATRIX_GAPS.items()
        if kind != "object-type"
    )

    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis,
        "object-type",
        "Employee",
        {"object_type": "Employee"},
        True,
    )
    target = DependencyTarget(
        "object-type", node.identifiers, node.display_name, node.id
    )

    service._initialize_matrix(analysis, target)
    service._complete_coverage(analysis)

    record = service._coverage_record(
        analysis, "object-type", "object-type-consumers", node.id
    )
    assert record.status == "unsupported"
    assert record.reason == "unsupported-object-type-consumers"


def test_object_type_consumer_surface_accepts_inconclusive_as_terminal_with_gap():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}
    )
    record = service._coverage_record(
        analysis,
        "object-type",
        "object-type-consumers",
        node.id,
        operation="ACP-05",
        transport="graphql-sse",
        empty_is_inconclusive=True,
    )
    service._finish_coverage(record, "inconclusive", reason="silent-truncation")
    service._add_gap(
        analysis,
        node.id,
        "object-type-consumers",
        "inconclusive",
        "silent-truncation",
        "Dependents may be truncated.",
        operation="ACP-05",
    )

    service._complete_coverage(analysis)

    assert record.complete is True
    assert record.status == "inconclusive"
    assert [gap.reason_code for gap in analysis.gaps.values()] == ["silent-truncation"]


def test_graphql_operation_provenance_round_trips_acp_pins_and_variables():
    operation = OperationProvenance(
        "operation-acp-05",
        "read-context",
        "internal",
        "object-type.get-dependents",
        ("CAP-10",),
        "1.101.0",
        "2026-07-22T00:00:00Z",
        "2026-07-22T00:00:01Z",
        ArgumentObservation("not-applicable"),
        ArgumentObservation("not-applicable"),
        29,
        transport="graphql-sse",
        acp_id="ACP-05",
        http_verb="POST",
        path="/graphql-gateway/api/bulk",
        contract_pins={"mcp": "0.397.0", "verified_on": "2026-07-21"},
        operation_name="GetObjectTypeDependents",
        document_sha256="abc123",
        request_variables={"rid": "ri.ontology.main.object-type.employee"},
    )

    serialized = serialize_dependency_result(
        {
            "operation_provenance": [operation],
            "coverage": [{"status": "inconclusive"}],
            "gaps": [{"coverage": "inconclusive"}],
        }
    )

    assert serialized["operation_provenance"] == [
        {
            "id": "operation-acp-05",
            "read_context_id": "read-context",
            "sdk_namespace": "internal",
            "sdk_method": "object-type.get-dependents",
            "capability_ids": ["CAP-10"],
            "invocation_sdk_version": "1.101.0",
            "invoked_at": "2026-07-22T00:00:00Z",
            "observed_at": "2026-07-22T00:00:01Z",
            "branch_argument": {"mode": "not-applicable", "value": None},
            "preview_argument": {"mode": "not-applicable", "value": None},
            "request_timeout_seconds": 29,
            "known_limitations": [],
            "transport": "graphql-sse",
            "acp_id": "ACP-05",
            "http_verb": "POST",
            "path": "/graphql-gateway/api/bulk",
            "contract_pins": {
                "mcp": "0.397.0",
                "verified_on": "2026-07-21",
            },
            "operation_name": "GetObjectTypeDependents",
            "document_sha256": "abc123",
            "request_variables": {"rid": "ri.ontology.main.object-type.employee"},
        }
    ]


def test_property_column_surface_stays_terminal_until_u4_collector_lands():
    assert "property-column-mapping" in STATIC_SURFACES
    assert (
        MATRIX_GAPS["property"]["property-column-mapping"]
        == "unsupported-property-column-mapping"
    )
    assert all(
        "property-column-mapping" in surfaces for kind, surfaces in MATRIX_GAPS.items()
    )

    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "property", "employeeId", {"property": "employeeId"}, True
    )
    target = DependencyTarget("property", node.identifiers, node.display_name, node.id)

    service._initialize_matrix(analysis, target)
    service._complete_coverage(analysis)

    record = service._coverage_record(
        analysis, "property", "property-column-mapping", node.id
    )
    assert record.status == "unsupported"
    assert record.reason == "unsupported-property-column-mapping"
    assert not any(
        gap.surface == "property-column-mapping"
        and gap.reason_code == "collector-did-not-report"
        for gap in analysis.gaps.values()
    )
    # Model the other applicable collectors succeeding. The newly registered
    # U3a surface must not be the reason an otherwise complete property run
    # loses its clean/CI-eligible status before U4 wires ACP-04.
    for candidate in analysis.coverage_records.values():
        if candidate.status == "unresolved":
            service._finish_coverage(candidate, "covered")
            service._remove_gaps(
                analysis,
                candidate.subject_node_id,
                candidate.surface,
                "collector-did-not-report",
            )
    classification = service._classify_agent_results(analysis, [])
    agent = service._build_agent_block(
        analysis, target, None, None, "absent", [], classification, None
    )
    assert classification["verification"]["must_verify_before_merge"] == []
    assert agent["status"] == "clean"


def test_inconclusive_is_terminal_and_matrix_completion_stays_deduplicated():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "property", "employeeId", {"property": "employeeId"}
    )
    record = service._coverage_record(
        analysis,
        "property",
        "property-column-mapping",
        node.id,
        operation="ACP-04",
        transport="conjure-rest",
        empty_is_inconclusive=True,
    )
    service._finish_coverage(record, "inconclusive", reason="empty-internal-response")
    service._add_gap(
        analysis,
        node.id,
        "property-column-mapping",
        "inconclusive",
        "empty-internal-response",
        "The internal response could not prove absence.",
        operation="ACP-04",
    )

    service._complete_coverage(analysis)

    assert record.complete is True
    assert record.status == "inconclusive"
    gaps = [
        gap
        for gap in analysis.gaps.values()
        if gap.target == node.id and gap.surface == "property-column-mapping"
    ]
    assert len(gaps) == 1


def test_dataset_column_node_and_column_backing_edge_round_trip():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    column = service._add_node(
        analysis,
        "dataset-column",
        "employee_id",
        {
            "dataset_rid": "ri.foundry.main.dataset.test",
            "column": "employee_id",
        },
    )
    prop = service._add_node(
        analysis, "property", "employeeId", {"property": "employeeId"}
    )

    edge = service._add_edge(
        analysis,
        column.id,
        prop.id,
        "column-backs-property",
        ["evidence-acp-04"],
    )

    assert edge.source == column.id
    assert column.id == "ri.foundry.main.dataset.test#employee_id"
    assert edge.target == prop.id
    assert edge.traversal_class == "dependency-flow"
    assert edge.intrinsic_orientation == "source_to_target"


def test_pinned_action_and_query_discriminant_registries_are_exhaustive():
    action_union = get_args(ontology_models.ActionLogicRule)[0]
    query_union = get_args(ontology_models.QueryDataType)[0]
    action_types = {
        model.model_fields["type"].default for model in get_args(action_union)
    }
    query_types = {
        model.model_fields["type"].default for model in get_args(query_union)
    }

    assert action_types == ACTION_LOGIC_RULE_TYPES
    assert query_types == QUERY_DATA_TYPE_TYPES


@pytest.mark.parametrize(
    "rule_model", get_args(get_args(ontology_models.ActionLogicRule)[0])
)
def test_each_pinned_action_rule_discriminant_reaches_extractor_with_root_locator(
    rule_model,
):
    values = {
        "object_type_api_name": "Employee",
        "object_api_name": "Employee",
        "a_side_object_type_api_name": "Employee",
        "b_side_object_type_api_name": "Manager",
        "interface_type_api_name": "Worker",
        "link_type_api_name": "manager",
        "function_rid": "ri.function-registry.main.function.test",
        "property_type_api_name": "name",
        "shared_property_type_rid": "ri.ontology.main.shared-property.name",
        "object_type_api_names": ["Employee"],
        "link_types": ["manager"],
        "object_type": "employee",
        "parameter_id": "employee",
        "scenario_parameter": "employee",
        "object_to_modify": "employee",
        "object_to_delete": "employee",
        "interface_object_to_modify": "employee",
        "source_object": "employee",
        "target_object": "employee",
        "property_arguments": {"name": None},
        "shared_property_arguments": {"name": None},
        "struct_property_arguments": {},
        "function_rule": ontology_models.FunctionLogicRule.model_construct(
            function_rid="ri.function-registry.main.function.test",
            function_input_values={},
        ),
    }
    rule = rule_model.model_construct(
        **{name: values.get(name) for name in rule_model.model_fields if name in values}
    )
    parameter = ontology_models.ActionParameterV2.model_construct(
        data_type=ontology_models.OntologyObjectType.model_construct(
            object_api_name="Employee", object_type_api_name="Employee"
        )
    )
    metadata = ontology_models.ActionTypeFullMetadata.model_construct(
        action_type=ontology_models.ActionTypeV2.model_construct(
            api_name="PinnedRuleGate", parameters={"employee": parameter}
        ),
        full_logic_rules=[rule],
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()

    references = service._extract_action_references(
        metadata, "ontology", analysis, "operation"
    )

    assert getattr(rule, "type") in ACTION_LOGIC_RULE_TYPES
    rule_references = [
        reference
        for reference in references
        if reference[2].startswith("fullLogicRules[0]")
    ]
    rooted_gaps = [
        gap
        for gap in analysis.gaps.values()
        if gap.locator is not None and gap.locator.startswith("fullLogicRules[0]")
    ]
    assert rule_references or rooted_gaps
    assert not any(
        gap.reason_code.startswith("unknown-action-logic-rule")
        for gap in analysis.gaps.values()
    )
    assert all(
        locator.startswith("fullLogicRules[0]") for _, _, locator, _ in rule_references
    )
    assert all(
        gap.locator is None or gap.locator.startswith("fullLogicRules[0]")
        for gap in analysis.gaps.values()
    )


@pytest.mark.parametrize(
    "data_type_model", get_args(get_args(ontology_models.QueryDataType)[0])
)
def test_each_pinned_query_data_type_discriminant_reaches_rooted_closure(
    data_type_model,
):
    discriminator = data_type_model.model_fields["type"].default
    object_leaf = ontology_models.OntologyObjectType.model_construct(
        object_api_name="Employee", object_type_api_name="Employee"
    )
    values = {
        "sub_type": object_leaf,
        "union_types": [object_leaf],
        "fields": [
            ontology_models.QueryStructField.model_construct(
                name="employee", field_type=object_leaf
            )
        ],
        "key_type": object_leaf,
        "value_type": object_leaf,
        "type_id": "employeeRef",
        "object_api_name": "Employee",
        "object_type_api_name": "Employee",
        "interface_type_api_name": "Worker",
    }
    model_values = {
        name: values[name] for name in data_type_model.model_fields if name in values
    }
    if discriminator == "twoDimensionalAggregation":
        model_values = {
            "key_type": core_models.StringType(),
            "value_type": core_models.DoubleType(),
        }
    elif discriminator == "threeDimensionalAggregation":
        model_values = {
            "key_type": core_models.StringType(),
            "value_type": ontology_models.TwoDimensionalAggregation(
                key_type=core_models.StringType(),
                value_type=core_models.DoubleType(),
            ),
        }
    data_type = data_type_model.model_construct(**model_values)
    query = ontology_models.QueryTypeV2.model_construct(
        api_name="PinnedTypeGate", type_references={"employeeRef": object_leaf}
    )
    service = DependencyGraphService(client=SimpleNamespace())

    closure = service._build_query_reference_closure(
        query, {"output": data_type}, context(max_depth=10)
    )["output"]

    assert getattr(data_type, "type") in QUERY_DATA_TYPE_TYPES
    if discriminator in {
        "array",
        "set",
        "struct",
        "entrySet",
        "union",
        "typeReference",
        "object",
        "objectSet",
        "interfaceObject",
        "interfaceObjectSet",
        "unsupported",
    }:
        assert closure["leaves"] or closure["gaps"]
    if discriminator in {
        "twoDimensionalAggregation",
        "threeDimensionalAggregation",
    }:
        assert closure == {"leaves": [], "gaps": [], "sccs": []}
    assert all(item["locator"].startswith("output") for item in closure["leaves"])
    assert all(item["locator"].startswith("output") for item in closure["gaps"])
    assert not any(
        "Unknown reachable query data type variant" in item["message"]
        for item in closure["gaps"]
    )


def test_future_action_and_query_discriminants_create_exact_rooted_gaps():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    metadata = ontology_models.ActionTypeFullMetadata.model_construct(
        action_type=ontology_models.ActionTypeV2.model_construct(
            api_name="FutureAction", parameters={}
        ),
        full_logic_rules=[SimpleNamespace(type="futureRule")],
    )

    assert (
        service._extract_action_references(metadata, "ontology", analysis, "operation")
        == []
    )
    action_gap = next(iter(analysis.gaps.values()))
    assert action_gap.reason_code == "unknown-action-logic-rule:futureRule"
    assert action_gap.locator == "fullLogicRules[0]"

    query = ontology_models.QueryTypeV2.model_construct(
        api_name="FutureQuery", type_references={}
    )
    query_gaps = service._build_query_reference_closure(
        query, {"output": SimpleNamespace(type="futureType")}, analysis
    )["output"]["gaps"]
    assert query_gaps == [
        {
            "reason_code": "invalid-response",
            "locator": "output",
            "message": "Unknown reachable query data type variant: futureType",
        }
    ]


@pytest.mark.parametrize(
    ("supported", "kwargs", "name", "expected"),
    [
        (
            True,
            {"branch": "feature"},
            "branch",
            ArgumentObservation("explicit", "feature"),
        ),
        (
            True,
            {"branch_name": "feature"},
            "branch",
            ArgumentObservation("explicit", "feature"),
        ),
        (True, {}, "branch", ArgumentObservation("server-default")),
        (True, {"preview": True}, "preview", ArgumentObservation("explicit", True)),
        (True, {}, "preview", ArgumentObservation("server-default")),
        (False, {}, "branch", ArgumentObservation("not-applicable")),
        (False, {}, "preview", ArgumentObservation("not-applicable")),
    ],
)
def test_argument_observation_exact_states(supported, kwargs, name, expected):
    assert (
        DependencyGraphService._argument_observation(supported, kwargs, name)
        == expected
    )


def test_operation_provenance_records_exact_sdk_call_and_integral_timeout():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    call = Mock(return_value={"ok": True})

    result, operation_id = service._invoke_sdk(
        analysis,
        "action-type.get-full-metadata",
        call,
        {
            "ontology": "ri.ontology.main.ontology.test",
            "action_type": "HireEmployee",
            "branch": "feature",
            "preview": True,
        },
        target="HireEmployee",
    )

    assert result == {"ok": True}
    call.assert_called_once()
    passed = call.call_args.kwargs
    assert passed["branch"] == "feature"
    assert passed["preview"] is True
    assert isinstance(passed["request_timeout"], int)
    assert 1 <= passed["request_timeout"] <= 30
    operation = analysis.operation_provenance[operation_id]
    assert operation.sdk_namespace == "client.ontologies.ActionTypeFullMetadata"
    assert operation.sdk_method == "get"
    assert operation.invocation_sdk_version == "1.95.0"
    assert operation.branch_argument == ArgumentObservation("explicit", "feature")
    assert operation.preview_argument == ArgumentObservation("explicit", True)
    assert operation.request_timeout_seconds == passed["request_timeout"]
    assert operation.invoked_at
    assert operation.observed_at


@pytest.mark.parametrize(
    ("dimension", "kwargs"),
    [
        ("requests", {"max_requests": 1}),
        ("pages", {"max_pages": 1}),
        ("items", {"max_items": 1}),
        ("nodes", {"max_nodes": 1}),
    ],
)
def test_budget_stops_before_counter_overrun(dimension, kwargs):
    budget = DiscoveryBudget(**kwargs)
    budget.charge(dimension)
    with pytest.raises(BudgetExhausted) as raised:
        budget.charge(dimension)
    assert raised.value.dimension == dimension
    assert raised.value.snapshot["used"][dimension] == 1


@pytest.mark.parametrize(
    ("field", "ceiling"),
    DiscoveryBudget.HARD_CEILINGS.items(),
)
def test_hard_budget_ceilings_reject_before_discovery(field, ceiling):
    with pytest.raises(ValueError, match=field):
        DiscoveryBudget(**{field: ceiling + 1})


@pytest.mark.parametrize(
    ("error", "error_class", "coverage", "retryable"),
    [
        (sdk_errors.UnauthorizedError({}), "authentication", "inaccessible", False),
        (
            sdk_errors.PermissionDeniedError({}),
            "permission-denied",
            "inaccessible",
            False,
        ),
        (sdk_errors.NotFoundError({}), "not-found", "unresolved", False),
        (sdk_errors.ApiNotFoundError("missing"), "unsupported", "unsupported", False),
        (sdk_errors.RateLimitError("limited", "rate"), "rate-limited", "partial", True),
        (sdk_errors.TimeoutError("timeout"), "timeout", "partial", True),
        (sdk_errors.ConnectionError("connection"), "connection", "partial", True),
        (sdk_errors.ProxyError("proxy"), "connection", "partial", True),
        (sdk_errors.BadRequestError({}), "invalid-request", "unresolved", False),
        (
            sdk_errors.UnprocessableEntityError({}),
            "invalid-request",
            "unresolved",
            False,
        ),
        (sdk_errors.InternalServerError({}), "internal", "partial", True),
        (RuntimeError("unknown"), "unknown", "unresolved", False),
    ],
)
def test_cap_11_exception_classifier(error, error_class, coverage, retryable):
    result = classify_exception(error)
    assert (result.error_class, result.coverage, result.retryable) == (
        error_class,
        coverage,
        retryable,
    )


def test_branch_not_found_classifier_uses_typed_name_not_message():
    error = sdk_errors.NotFoundError({"errorName": "BranchNotFound"})
    result = classify_exception(error)
    assert result.error_class == "branch-not-found"


def test_target_failure_is_fatal_while_subread_failure_is_a_gap():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    failing = Mock(side_effect=sdk_errors.PermissionDeniedError({}))
    with pytest.raises(DependencyFatalError) as raised:
        service._invoke_sdk(
            analysis,
            "filesystem.resource.get",
            failing,
            {"resource_rid": "ri.test"},
            target="ri.test",
            fatal=True,
        )
    assert raised.value.error_class == "permission-denied"

    node = service._add_node(analysis, "resource", "child", {"rid": "child"})
    record = service._coverage_record(analysis, "resource", "compass-metadata", node.id)
    try:
        service._invoke_sdk(
            analysis,
            "filesystem.resource.get",
            failing,
            {"resource_rid": "child"},
            target="child",
        )
    except Exception as error:
        service._record_failure(analysis, record, error, "filesystem.resource.get")
    assert record.status == "inaccessible"
    assert any(gap.reason_code == "permission-denied" for gap in analysis.gaps.values())


def test_depth_and_time_budget_bound_work_deterministically():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=1)
    one = service._add_node(analysis, "resource", "one", {"rid": "one"})
    two = service._add_node(analysis, "resource", "two", {"rid": "two"})
    three = service._add_node(analysis, "resource", "three", {"rid": "three"})
    service._add_edge(analysis, one.id, two.id, "container-member", [])
    service._add_edge(analysis, two.id, three.id, "container-member", [])
    paths = service._derive_paths(analysis, one.id, "both")
    assert {path["related_node_id"] for path in paths} == {two.id}

    analysis.budget._started_at -= analysis.budget.time_budget_seconds + 1
    with pytest.raises(BudgetExhausted) as raised:
        analysis.budget.charge("requests")
    assert raised.value.dimension == "time"


@pytest.mark.parametrize(
    ("relation_kind", "source_kind", "target_kind"),
    [
        ("action-affects-object", "action-type", "object-type"),
        ("query-returns-object", "query-type", "object-type"),
        ("schedule-consumes-resource", "schedule", "dataset"),
    ],
)
def test_dependency_flow_reverses_only_root_relative_direction(
    relation_kind, source_kind, target_kind
):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    source = service._add_node(analysis, source_kind, "source", {"name": "source"})
    target = service._add_node(analysis, target_kind, "target", {"name": "target"})
    edge = service._add_edge(analysis, source.id, target.id, relation_kind, [])

    assert edge.traversal_class == "dependency-flow"
    assert service._traversal_direction(edge, source.id) == "downstream"
    assert service._traversal_direction(edge, target.id) == "upstream"
    assert (
        service._add_edge(analysis, source.id, target.id, relation_kind, []).id
        == edge.id
    )


@pytest.mark.parametrize(
    "relation_kind",
    [
        relation_kind
        for relation_kind, (traversal_class, _) in RELATION_KINDS.items()
        if traversal_class == "adjacent-structural"
    ],
)
def test_structural_relations_remain_adjacent_from_reciprocal_roots(relation_kind):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    left = service._add_node(analysis, "resource", "left", {"rid": "left"})
    right = service._add_node(analysis, "resource", "right", {"rid": "right"})
    edge = service._add_edge(analysis, left.id, right.id, relation_kind, [])

    assert edge.traversal_class == "adjacent-structural"
    assert service._traversal_direction(edge, left.id) == "adjacent"
    assert service._traversal_direction(edge, right.id) == "adjacent"


def test_edge_identity_excludes_and_merges_independent_evidence():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    source = service._add_node(analysis, "dataset", "source", {"rid": "source"})
    target = service._add_node(analysis, "schedule", "target", {"rid": "target"})

    first = service._add_edge(
        analysis, source.id, target.id, "schedule-consumes-resource", ["ev-b"]
    )
    second = service._add_edge(
        analysis, source.id, target.id, "schedule-consumes-resource", ["ev-a"]
    )

    assert first.id == second.id
    assert second.evidence_ids == ("ev-a", "ev-b")


def test_actual_full_action_metadata_uses_full_rules_when_operations_are_empty():
    parameter = ontology_models.ActionParameterV2(
        display_name="Employee",
        description=None,
        data_type=ontology_models.OntologyObjectType(
            object_api_name="Employee", object_type_api_name="Employee"
        ),
        required=True,
        type_classes=None,
    )
    metadata = ontology_models.ActionTypeFullMetadata(
        action_type=ontology_models.ActionTypeV2(
            api_name="HireEmployee",
            description=None,
            display_name="Hire employee",
            status="ACTIVE",
            parameters={"employee": parameter},
            rid="ri.ontology.main.action-type.hire",
            operations=[],
            tool_description=None,
        ),
        full_logic_rules=[
            ontology_models.CreateObjectLogicRule(
                object_type_api_name="Employee",
                property_arguments={},
                struct_property_arguments={},
            )
        ],
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    operation_id = "operation_full_action"

    references = service._extract_action_references(
        metadata,
        "ri.ontology.main.ontology.test",
        analysis,
        operation_id,
    )

    assert any(
        kind == "object-type"
        and name == "Employee"
        and locator.startswith("fullLogicRules")
        for kind, name, locator, _ in references
    )
    assert not any("operations" in locator for _, _, locator, _ in references)


def test_nested_batched_function_rid_is_collected_from_full_rule():
    metadata = ontology_models.ActionTypeFullMetadata(
        action_type=ontology_models.ActionTypeV2(
            api_name="RunFunction",
            description=None,
            display_name=None,
            status="ACTIVE",
            parameters={},
            rid="ri.ontology.main.action-type.run-function",
            operations=[],
            tool_description=None,
        ),
        full_logic_rules=[
            ontology_models.BatchedFunctionLogicRule(
                object_set_rid_input_name="objects",
                function_rule=ontology_models.FunctionLogicRule(
                    function_rid="ri.function-registry.main.function.fn",
                    function_version="1.0.0",
                    function_input_values={},
                ),
            )
        ],
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    references = service._extract_action_references(
        metadata, "ontology", analysis, "operation"
    )
    assert any(
        kind == "function"
        and name == "ri.function-registry.main.function.fn"
        and "functionRule.functionRid" in locator
        for kind, name, locator, _ in references
    )


def test_full_action_parameter_id_and_property_reference_fields_are_explicit():
    employee = ontology_models.ActionParameterV2(
        display_name="Employee",
        description=None,
        data_type=ontology_models.OntologyObjectType(
            object_api_name="Employee", object_type_api_name="Employee"
        ),
        required=True,
        type_classes=None,
    )
    scenario = ontology_models.ActionParameterV2(
        display_name="Scenario",
        description=None,
        data_type=core_models.ScenarioReferenceType(),
        required=True,
        type_classes=None,
    )
    metadata = ontology_models.ActionTypeFullMetadata(
        action_type=ontology_models.ActionTypeV2(
            api_name="Complete",
            description=None,
            display_name=None,
            status="ACTIVE",
            parameters={"employee": employee, "scenario": scenario},
            rid="ri.ontology.main.action-type.complete",
            operations=[],
            tool_description=None,
        ),
        full_logic_rules=[
            ontology_models.CreateInterfaceLogicRule(
                interface_type_api_name="Worker",
                object_type="employee",
                shared_property_arguments={
                    "name": ontology_models.ObjectParameterPropertyArgument(
                        parameter_id="employee", property_type_api_name="name"
                    )
                },
                struct_property_arguments={},
            ),
            ontology_models.FunctionLogicRule(
                function_rid="ri.function-registry.main.function.fn",
                function_version="1.0.0",
                function_input_values={
                    "employee": ontology_models.ParameterIdArgument(
                        parameter_id="employee"
                    ),
                    "shared": ontology_models.InterfaceParameterPropertyArgument(
                        parameter_id="employee",
                        shared_property_type_rid="ri.ontology.main.shared-property.name",
                    ),
                },
            ),
            ontology_models.ApplyScenarioLogicRule(
                scenario_parameter="scenario",
                object_type_api_names=["Employee"],
                link_types=[
                    ontology_models.ObjectTypeLinkTypeApiNameMapping(
                        object_type_api_name="Employee", link_types=["manager"]
                    )
                ],
            ),
        ],
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    references = service._extract_action_references(
        metadata, "ontology", analysis, "operation"
    )
    assert any(
        kind == "object-type" and name == "Employee" for kind, name, _, _ in references
    )
    assert any(kind == "property" and name == "name" for kind, name, _, _ in references)
    assert any(
        kind == "shared-property-type" and name.endswith(".name")
        for kind, name, _, _ in references
    )
    assert any(
        kind == "link-type" and name == "manager" for kind, name, _, _ in references
    )


def test_action_and_query_reverse_indices_cache_once_per_branch():
    action = ontology_models.ActionTypeFullMetadata(
        action_type=ontology_models.ActionTypeV2(
            api_name="Action",
            description=None,
            display_name=None,
            status="ACTIVE",
            parameters={},
            rid="ri.ontology.main.action-type.action",
            operations=[],
            tool_description=None,
        ),
        full_logic_rules=[],
    )
    query = _recursive_query()
    action_list = Mock(
        return_value=SimpleNamespace(data=[action], next_page_token=None)
    )
    query_list = Mock(return_value=SimpleNamespace(data=[query], next_page_token=None))
    client = SimpleNamespace(
        ontologies=SimpleNamespace(
            ActionTypeFullMetadata=SimpleNamespace(list=action_list),
            Ontology=SimpleNamespace(QueryType=SimpleNamespace(list=query_list)),
        )
    )
    service = DependencyGraphService(client=client)
    first = context()

    service._get_action_index(first, "ontology")
    service._get_action_index(first, "ontology")
    service._get_query_index(first, "ontology")
    service._get_query_index(first, "ontology")

    assert action_list.call_count == 1
    assert query_list.call_count == 1
    second = AnalysisContext.create(
        profile="test",
        ontology_rid="ontology",
        requested_branch="other",
    )
    service._get_action_index(second, "ontology")
    service._get_query_index(second, "ontology")
    assert action_list.call_count == 2
    assert query_list.call_count == 2


def _recursive_query(include_unsupported=False):
    definitions = {
        "A": ontology_models.QueryUnionType(
            union_types=[
                ontology_models.OntologyObjectType(
                    object_api_name="X", object_type_api_name="X"
                ),
                ontology_models.QueryTypeReferenceType(type_id="B"),
            ]
        ),
        "B": ontology_models.QueryUnionType(
            union_types=[
                ontology_models.OntologyObjectType(
                    object_api_name="Y", object_type_api_name="Y"
                ),
                ontology_models.QueryTypeReferenceType(type_id="A"),
            ]
        ),
    }
    if include_unsupported:
        definitions["B"] = ontology_models.QueryUnionType(
            union_types=[
                definitions["B"],
                core_models.UnsupportedType(unsupported_type="future", params={}),
            ]
        )
    return ontology_models.QueryTypeV2(
        api_name="RecursiveQuery",
        description=None,
        display_name="Recursive query",
        parameters={
            "input": ontology_models.QueryParameterV2(
                description=None,
                data_type=ontology_models.QueryTypeReferenceType(type_id="A"),
                required=True,
            )
        },
        output=ontology_models.QueryTypeReferenceType(type_id="B"),
        rid="ri.function-registry.main.function.recursive",
        version="1.0.0",
        type_references=definitions,
    )


def test_query_scc_fixed_point_is_complete_from_both_entry_roots():
    query = _recursive_query()
    service = DependencyGraphService(client=SimpleNamespace())
    closure = service._build_query_reference_closure(
        query,
        {
            "parameters.input.dataType": query.parameters["input"].data_type,
            "output": query.output,
        },
        context(max_depth=10),
    )

    assert {
        leaf["name"] for leaf in closure["parameters.input.dataType"]["leaves"]
    } == {"X", "Y"}
    assert {leaf["name"] for leaf in closure["output"]["leaves"]} == {"X", "Y"}
    assert closure["parameters.input.dataType"]["sccs"] == [["A", "B"]]
    assert closure["output"]["sccs"] == [["A", "B"]]


def test_query_parameter_inputs_and_outputs_have_opposite_intrinsic_orientation():
    query = _recursive_query()
    client = SimpleNamespace(
        ontologies=SimpleNamespace(
            ActionTypeFullMetadata=SimpleNamespace(
                list=Mock(return_value=SimpleNamespace(data=[], next_page_token=None))
            )
        )
    )
    service = DependencyGraphService(client=client)
    analysis = context()
    query_node = service._add_node(
        analysis,
        "query-type",
        query.api_name,
        {"ontology_rid": "ontology", "query_type": query.api_name},
        True,
    )
    target = DependencyTarget(
        "query-type", query_node.identifiers, query.api_name, query_node.id
    )
    analysis.caches[("query-metadata", "ontology", "feature", query.api_name)] = (
        query,
        "operation",
    )
    service._collect_query_target(target, analysis)
    accepts = [
        edge
        for edge in analysis.edges.values()
        if edge.relation_kind == "query-accepts-object"
    ]
    returns = [
        edge
        for edge in analysis.edges.values()
        if edge.relation_kind == "query-returns-object"
    ]
    assert accepts and all(edge.target == query_node.id for edge in accepts)
    assert returns and all(edge.source == query_node.id for edge in returns)


def test_reachable_unsupported_query_type_gaps_but_unreachable_does_not():
    query = _recursive_query(include_unsupported=True)
    query.type_references["UNREACHABLE"] = core_models.UnsupportedType(
        unsupported_type="unreachable", params={}
    )
    service = DependencyGraphService(client=SimpleNamespace())
    closure = service._build_query_reference_closure(
        query, {"output": query.output}, context(max_depth=10)
    )

    gaps = closure["output"]["gaps"]
    assert [gap["reason_code"] for gap in gaps].count(
        "unsupported-query-data-type"
    ) == 1
    assert all("UNREACHABLE" not in gap["locator"] for gap in gaps)


def test_missing_reachable_reference_is_invalid_but_unreachable_missing_is_ignored():
    query = _recursive_query()
    query.type_references["A"] = ontology_models.QueryTypeReferenceType(
        type_id="MISSING"
    )
    query.type_references["UNREACHABLE"] = ontology_models.QueryTypeReferenceType(
        type_id="OTHER_MISSING"
    )
    service = DependencyGraphService(client=SimpleNamespace())
    closure = service._build_query_reference_closure(
        query,
        {"parameter": ontology_models.QueryTypeReferenceType(type_id="A")},
        context(max_depth=10),
    )

    assert any("MISSING" in gap["message"] for gap in closure["parameter"]["gaps"])
    assert all(
        "OTHER_MISSING" not in gap["message"] for gap in closure["parameter"]["gaps"]
    )


def test_schedule_reverse_index_empty_success_is_always_partial(monkeypatch):
    monkeypatch.setattr(
        "pltr.services.dependency.DatasetService.get_schedule_rids_page",
        lambda self, **kwargs: {"schedule_rids": [], "next_page_token": None},
    )
    fake_client = SimpleNamespace()
    service = DependencyGraphService(client=fake_client)
    analysis = context()
    node = service._add_node(
        analysis,
        "dataset",
        "dataset",
        {"resource_rid": "ri.foundry.main.dataset.test"},
        True,
    )
    target = DependencyTarget("dataset", node.identifiers, node.display_name, node.id)

    result = service.analyze(target, analysis)

    reverse = next(
        record
        for record in result["coverage"]
        if record["surface"] == "schedule-reverse-index"
    )
    assert reverse["status"] == "partial"
    assert reverse["status"] != "covered-empty"
    stale = [
        gap
        for gap in result["gaps"]
        if gap["reason_code"] == "schedule-index-may-be-stale"
    ]
    assert len(stale) == 1
    assert "up to one hour" in stale[0]["message"]
    operation = next(
        operation
        for operation in result["operation_provenance"]
        if operation["sdk_method"] == "get_schedules"
    )
    assert operation["known_limitations"][0]["max_lag_seconds"] == 3600


def test_dataset_chain_uses_schedule_action_then_run_build_jobs_outputs(monkeypatch):
    observed = []

    def schedules(self, **kwargs):
        observed.append(("schedules", kwargs))
        return {"schedule_rids": ["schedule-a"], "next_page_token": None}

    def schedule(self, **kwargs):
        observed.append(("schedule", kwargs))
        return {
            "action": {
                "target": {
                    "type": "connecting",
                    "input_rids": ["ri.foundry.main.dataset.input"],
                    "target_rids": [
                        "ri.foundry.main.dataset.root",
                        "ri.foundry.main.dataset.target",
                    ],
                    "ignored_rids": ["ri.foundry.main.dataset.ignored"],
                }
            },
            "trigger": {"type": "manual"},
            "scope_mode": {"type": "user"},
        }

    def affected(self, **kwargs):
        observed.append(("affected", kwargs))
        return {"affected_resources": ["ri.foundry.main.dataset.affected"]}

    def runs(self, **kwargs):
        observed.append(("runs", kwargs))
        return {
            "runs": [
                {
                    "rid": "run-a",
                    "result": {"type": "submitted", "build_rid": "build-a"},
                },
                {"rid": "run-ignored", "result": {"type": "ignored"}},
            ],
            "next_page_token": None,
        }

    def build(self, **kwargs):
        observed.append(("build", kwargs))
        return {"rid": "build-a", "job_rids": ["job-a"], "status": "SUCCEEDED"}

    def jobs(self, **kwargs):
        observed.append(("jobs", kwargs))
        return {
            "jobs": [
                {
                    "rid": "job-a",
                    "outputs": [
                        {
                            "type": "datasetJobOutput",
                            "dataset_rid": "ri.foundry.main.dataset.output",
                        },
                        {
                            "type": "transactionalMediaSetJobOutput",
                            "media_set_rid": "ri.mio.main.media-set.output",
                        },
                    ],
                }
            ],
            "next_page_token": None,
        }

    monkeypatch.setattr(
        "pltr.services.dependency.DatasetService.get_schedule_rids_page", schedules
    )
    monkeypatch.setattr(
        "pltr.services.dependency.OrchestrationService.get_schedule", schedule
    )
    monkeypatch.setattr(
        "pltr.services.dependency.OrchestrationService.get_schedule_affected_resources",
        affected,
    )
    monkeypatch.setattr(
        "pltr.services.dependency.OrchestrationService.get_schedule_runs", runs
    )
    monkeypatch.setattr(
        "pltr.services.dependency.OrchestrationService.get_build", build
    )
    monkeypatch.setattr(
        "pltr.services.dependency.OrchestrationService.get_build_jobs", jobs
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(
        analysis,
        "dataset",
        "root",
        {"resource_rid": "ri.foundry.main.dataset.root"},
        True,
    )

    result = service.analyze(
        DependencyTarget("dataset", root.identifiers, root.display_name, root.id),
        analysis,
    )

    assert [name for name, _ in observed] == [
        "schedules",
        "schedule",
        "affected",
        "runs",
        "build",
        "jobs",
    ]
    assert all(isinstance(kwargs["request_timeout"], int) for _, kwargs in observed)
    assert observed[0][1]["branch_name"] == "feature"
    edges = result["graph"]["edges"]
    assert any(edge["relation_kind"] == "schedule-consumes-resource" for edge in edges)
    assert any(edge["relation_kind"] == "schedule-produces-resource" for edge in edges)
    assert any(edge["relation_kind"] == "run-submitted-build" for edge in edges)
    assert any(edge["relation_kind"] == "build-produced-output" for edge in edges)
    canonical = next(
        edge
        for edge in edges
        if edge["relation_kind"] == "schedule-produces-resource"
        and edge["source"]
        == next(
            node["id"]
            for node in result["graph"]["nodes"]
            if node["kind"] == "schedule" and node["display_name"] == "schedule-a"
        )
        and edge["target"] == root.id
    )
    assert len(canonical["evidence_ids"]) == 2
    assert any(edge["relation_kind"] == "build-co-output" for edge in edges)
    assert not any(
        "ignored" in node["display_name"] and node["kind"] == "build"
        for node in result["graph"]["nodes"]
    )
    typed = [
        record for record in result["coverage"] if record["surface"] == "typed-outputs"
    ]
    assert typed and typed[0]["status"] == "partial"
    assert any(
        gap["reason_code"] == "unsupported-output-kinds" for gap in result["gaps"]
    )


@pytest.mark.parametrize(
    "surface",
    [
        "schedule-detail-action",
        "schedule-trigger",
        "schedule-affected-resources",
        "schedule-runs",
        "submitted-build",
        "build-jobs",
        "typed-outputs",
    ],
)
def test_conditional_record_cannot_be_masked_by_stale_parent(surface):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    dataset = service._add_node(
        analysis, "dataset", "dataset", {"rid": "dataset"}, True
    )
    subject = service._add_node(analysis, "transit", surface, {"rid": surface})
    parent = service._coverage_record(
        analysis, "dataset", "schedule-reverse-index", dataset.id
    )
    service._finish_coverage(parent, "partial", reason="schedule-index-may-be-stale")
    child = service._coverage_record(
        analysis,
        "transit",
        surface,
        subject.id,
        parent_record_id=parent.id,
        applicability_evidence_id="evidence-applicable",
    )

    service._complete_coverage(analysis)

    assert child.status == "unresolved"
    assert child.reason == "collector-did-not-report"
    assert any(
        gap.surface == surface and gap.reason_code == "collector-did-not-report"
        for gap in analysis.gaps.values()
    )


def test_nested_trigger_collects_all_resource_leaves_and_manual_time_are_empty():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    schedule = service._add_node(
        analysis, "schedule", "schedule", {"schedule_rid": "schedule"}
    )
    operation_id = "operation-schedule"
    trigger = {
        "type": "and",
        "triggers": [
            {"type": "datasetUpdated", "dataset_rid": "dataset-a"},
            {
                "type": "or",
                "triggers": [
                    {"type": "jobSucceeded", "dataset_rid": "dataset-b"},
                    {"type": "newLogic", "dataset_rid": "dataset-c"},
                    {"type": "tableUpdated", "table_rid": "table-a"},
                    {"type": "scheduleSucceeded", "schedule_rid": "schedule-b"},
                    {"type": "mediaSetUpdated", "media_set_rid": "media-a"},
                    {"type": "manual"},
                    {"type": "time"},
                ],
            },
        ],
    }

    evidence, gap = service._collect_trigger(
        analysis, schedule, operation_id, trigger, "trigger"
    )

    assert gap is None
    assert len(evidence) == 6
    locators = {analysis.evidence[evidence_id].locator for evidence_id in evidence}
    assert "trigger.triggers[0].dataset_rid" in locators
    assert "trigger.triggers[1].triggers[3].schedule_rid" in locators
    assert not any("manual" in locator or "time" in locator for locator in locators)


def test_unknown_trigger_variant_and_hidden_trigger_are_specific_gaps():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    schedule = service._add_node(
        analysis, "schedule", "schedule", {"schedule_rid": "schedule"}
    )

    _, unknown = service._collect_trigger(
        analysis,
        schedule,
        "operation",
        {"type": "futureTrigger", "rid": "future"},
        "trigger.triggers[2]",
    )
    _, hidden = service._collect_trigger(
        analysis, schedule, "operation", None, "trigger"
    )

    assert unknown.reason_code == "unknown-schedule-trigger-variant:futureTrigger"
    assert hidden.reason_code == "schedule-trigger-unobservable"


def test_third_party_application_read_uses_exact_pinned_kwarg_and_preview():
    get = Mock(
        return_value=SimpleNamespace(
            rid="ri.third-party-applications.main.third-party-application.app"
        )
    )
    client = SimpleNamespace(
        third_party_applications=SimpleNamespace(
            ThirdPartyApplication=SimpleNamespace(get=get)
        )
    )
    service = DependencyGraphService(client=client)
    analysis = context()
    node = service._add_node(
        analysis,
        "third-party-application",
        "app",
        {
            "resource_rid": "ri.third-party-applications.main.third-party-application.app"
        },
        True,
    )
    record = service._coverage_record(
        analysis, "third-party-application", "compass-metadata", node.id
    )

    service._collect_resource(
        DependencyTarget("third-party-application", node.identifiers, "app", node.id),
        analysis,
    )

    passed = get.call_args.kwargs
    assert passed["third_party_application_rid"] == node.identifiers["resource_rid"]
    assert passed["preview"] is True
    assert isinstance(passed["request_timeout"], int)
    assert record.status == "covered"


def test_matrix_gap_and_completion_deduplicate_by_subject_surface_context():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "generic-resource", "unknown", {"rid": "unknown"}, True
    )
    target = DependencyTarget("generic-resource", node.identifiers, "unknown", node.id)
    service._initialize_matrix(analysis, target)
    before = len(analysis.gaps)
    service._initialize_matrix(analysis, target)
    service._complete_coverage(analysis)

    assert len(analysis.gaps) == before
    keys = [
        (gap.target, gap.surface, gap.reason_code, gap.read_context_id)
        for gap in analysis.gaps.values()
    ]
    assert len(keys) == len(set(keys))


def test_sorted_bfs_dispatches_collectors_transitively_with_cache_local_state():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=2)
    root = service._add_node(
        analysis, "generic-resource", "root", {"resource_rid": "root"}, True
    )
    visits = []

    def collect(target, active_context):
        visits.append(target.display_name)
        if target.display_name == "root":
            child = service._add_node(
                active_context, "generic-resource", "child", {"resource_rid": "child"}
            )
            service._add_edge(
                active_context, target.node_id, child.id, "container-member", []
            )
        elif target.display_name == "child":
            leaf = service._add_node(
                active_context, "generic-resource", "leaf", {"resource_rid": "leaf"}
            )
            service._add_edge(
                active_context, target.node_id, leaf.id, "container-member", []
            )

    service._collect_target = collect
    service._discover_bfs(
        DependencyTarget("generic-resource", root.identifiers, "root", root.id),
        analysis,
        "both",
    )
    assert visits == ["root", "child", "leaf"]


def test_production_bfs_dispatches_action_derived_property_and_link_collectors():
    employee = ontology_models.ActionParameterV2(
        display_name="Employee",
        description=None,
        data_type=ontology_models.OntologyObjectType(
            object_api_name="Employee", object_type_api_name="Employee"
        ),
        required=True,
        type_classes=None,
    )
    metadata = ontology_models.ActionTypeFullMetadata(
        action_type=ontology_models.ActionTypeV2(
            api_name="UpdateEmployee",
            description=None,
            display_name=None,
            status="ACTIVE",
            parameters={"employee": employee},
            rid="ri.ontology.main.action-type.update",
            operations=[],
            tool_description=None,
        ),
        full_logic_rules=[
            ontology_models.CreateObjectLogicRule(
                object_type_api_name="Employee",
                property_arguments={
                    "name": ontology_models.ParameterIdArgument(parameter_id="employee")
                },
                struct_property_arguments={},
            ),
            ontology_models.CreateLinkLogicRule(
                link_type_api_name="manager",
                source_object="employee",
                target_object="employee",
            ),
        ],
    )
    object_metadata = SimpleNamespace(
        object_type=SimpleNamespace(properties={"name": SimpleNamespace()}),
        implements_interfaces=[],
        link_types=[],
    )
    get_full = Mock(return_value=object_metadata)
    get_link = Mock(return_value=SimpleNamespace(object_type_api_name="Employee"))
    client = SimpleNamespace(
        ontologies=SimpleNamespace(
            ActionTypeFullMetadata=SimpleNamespace(
                list=Mock(
                    return_value=SimpleNamespace(data=[metadata], next_page_token=None)
                )
            ),
            Ontology=SimpleNamespace(
                ObjectType=SimpleNamespace(
                    get_full_metadata=get_full, get_outgoing_link_type=get_link
                ),
                QueryType=SimpleNamespace(
                    list=Mock(
                        return_value=SimpleNamespace(data=[], next_page_token=None)
                    )
                ),
            ),
        )
    )
    service = DependencyGraphService(client=client)
    analysis = context(max_depth=1)
    action = service._add_node(
        analysis,
        "action-type",
        "UpdateEmployee",
        {"ontology_rid": "ontology", "action_type": "UpdateEmployee"},
        True,
    )
    analysis.caches[("action-metadata", "ontology", "feature", "UpdateEmployee")] = (
        metadata,
        "operation",
    )
    service._discover_bfs(
        DependencyTarget(
            "action-type", action.identifiers, action.display_name, action.id
        ),
        analysis,
        "both",
    )
    property_node = next(
        node for node in analysis.nodes.values() if node.kind == "property"
    )
    link_node = next(
        node for node in analysis.nodes.values() if node.kind == "link-type"
    )
    assert property_node.identifiers["object_type"] == "Employee"
    assert link_node.identifiers["object_type"] == "Employee"
    assert get_full.called
    assert get_link.called


def test_real_depth_cutoff_terminalizes_undispatched_frontier_surfaces():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=1)
    root = service._add_node(
        analysis, "generic-resource", "root", {"resource_rid": "root"}, True
    )
    child = service._add_node(
        analysis, "generic-resource", "child", {"resource_rid": "child"}
    )
    leaf = service._add_node(
        analysis, "generic-resource", "leaf", {"resource_rid": "leaf"}
    )
    service._add_edge(analysis, root.id, child.id, "container-member", [])
    service._add_edge(analysis, child.id, leaf.id, "container-member", [])
    service._collect_target = lambda target, active_context: None
    service._discover_bfs(
        DependencyTarget("generic-resource", root.identifiers, "root", root.id),
        analysis,
        "both",
    )
    leaf_records = [
        record
        for record in analysis.coverage_records.values()
        if record.subject_node_id == leaf.id
    ]
    assert leaf_records
    assert all(
        record.status in {"unsupported", "budget-exhausted"} for record in leaf_records
    )
    assert any(
        gap.target == leaf.id and gap.coverage == "budget-exhausted"
        for gap in analysis.gaps.values()
    )


def test_budget_exhaustion_terminalizes_each_unfinished_surface():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "dataset", "dataset", {"resource_rid": "dataset"}
    )
    first = service._coverage_record(analysis, "dataset", "schedule-runs", node.id)
    second_node = service._add_node(analysis, "build", "build", {"build_rid": "build"})
    second = service._coverage_record(analysis, "build", "build-jobs", second_node.id)
    error = BudgetExhausted("requests", analysis.budget.snapshot())
    analysis.caches[("budget-exhausted",)] = error
    service._complete_coverage(analysis)
    assert first.status == second.status == "budget-exhausted"
    assert all(gap.reason_code == "budget-exhausted" for gap in analysis.gaps.values())


def test_real_reverse_index_request_exhaustion_is_surface_specific():
    list_actions = Mock(return_value=SimpleNamespace(data=[], next_page_token="next"))
    client = SimpleNamespace(
        ontologies=SimpleNamespace(
            ActionTypeFullMetadata=SimpleNamespace(list=list_actions)
        )
    )
    service = DependencyGraphService(client=client)
    analysis = context(max_requests=1)
    node = service._add_node(
        analysis,
        "object-type",
        "Employee",
        {"ontology_rid": "ontology", "object_type": "Employee"},
    )
    record = service._coverage_record(
        analysis, "object-type", "full-action-metadata", node.id
    )
    target = DependencyTarget(
        "object-type", node.identifiers, node.display_name, node.id
    )
    service._collect_reverse_actions(target, analysis, "ontology")
    service._complete_coverage(analysis)
    assert record.status == "budget-exhausted"
    assert record.reason == "budget-exhausted"
    gap = next(
        gap
        for gap in analysis.gaps.values()
        if gap.target == node.id and gap.surface == "full-action-metadata"
    )
    assert gap.coverage == "budget-exhausted"
    assert gap.reason_code == "budget-exhausted"
    assert gap.retryable is True
    assert gap.budget_snapshot["limits"]["requests"] == 1
    list_actions.assert_called_once()


def test_dataset_discovery_request_exhaustion_terminalizes_schedule_children(
    monkeypatch,
):
    monkeypatch.setattr(
        "pltr.services.dependency.DatasetService.get_schedule_rids_page",
        lambda self, **kwargs: {
            "schedule_rids": ["schedule-a"],
            "next_page_token": None,
        },
    )
    detail = Mock(
        side_effect=AssertionError("detail wrapper must not run after request refusal")
    )
    monkeypatch.setattr(
        "pltr.services.dependency.OrchestrationService.get_schedule", detail
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_requests=1)
    root = service._add_node(
        analysis,
        "dataset",
        "root",
        {"resource_rid": "ri.foundry.main.dataset.root"},
        True,
    )
    target = DependencyTarget("dataset", root.identifiers, root.display_name, root.id)
    result = service.analyze(target, analysis)
    child_records = [
        record
        for record in result["coverage"]
        if record["surface"]
        in {
            "schedule-detail-action",
            "schedule-trigger",
            "schedule-affected-resources",
            "schedule-runs",
        }
    ]
    assert len(child_records) == 4
    assert all(record["status"] == "budget-exhausted" for record in child_records)
    assert all(record["reason"] == "budget-exhausted" for record in child_records)
    assert not any(
        gap["reason_code"] == "collector-did-not-report"
        and gap["surface"] in {record["surface"] for record in child_records}
        for gap in result["gaps"]
    )
    assert detail.call_count == 0


def test_bfs_frontier_request_exhaustion_terminalizes_frontier_surfaces():
    action_list = Mock(side_effect=AssertionError("refused request must not reach SDK"))
    client = SimpleNamespace(
        ontologies=SimpleNamespace(
            ActionTypeFullMetadata=SimpleNamespace(list=action_list)
        )
    )
    service = DependencyGraphService(client=client)
    analysis = context(max_requests=1)
    root = service._add_node(
        analysis, "generic-resource", "root", {"resource_rid": "root"}, True
    )
    action = service._add_node(
        analysis,
        "action-type",
        "UpdateEmployee",
        {
            "ontology_rid": "ri.ontology.main.ontology.test",
            "action_type": "UpdateEmployee",
        },
    )
    service._add_edge(analysis, root.id, action.id, "action-affects-object", [])

    original_collect = service._collect_target

    def collect(target, active_context):
        if target.node_id == root.id:
            service._invoke_sdk(
                active_context,
                "filesystem.resource.get",
                Mock(return_value={}),
                {"resource_rid": "root"},
                target="root",
            )
            return
        original_collect(target, active_context)

    service._collect_target = collect
    service._discover_bfs(
        DependencyTarget(
            "generic-resource", root.identifiers, root.display_name, root.id
        ),
        analysis,
        "both",
    )

    frontier_records = [
        record
        for record in analysis.coverage_records.values()
        if record.subject_node_id == action.id
    ]
    assert frontier_records
    assert all(
        record.status in {"unsupported", "budget-exhausted"}
        for record in frontier_records
    )
    assert any(
        gap.target == action.id and gap.coverage == "budget-exhausted"
        for gap in analysis.gaps.values()
    )
    action_list.assert_not_called()


def test_project_scope_is_adjacent_not_dependency_flow():
    assert RELATION_KINDS["project-scope"][0] == "adjacent-structural"


@pytest.mark.parametrize(
    ("resource_type", "kind"),
    [
        ("FOUNDRY_DATASET", "dataset"),
        ("THIRD_PARTY_APPLICATIONS_APPLICATION", "third-party-application"),
        ("WORKSHOP_MODULE", "workshop-resource"),
        ("WORKSHOP_STATE", "workshop-resource"),
        ("UNKNOWN_FUTURE_TYPE", "generic-resource"),
    ],
)
def test_pinned_resource_type_matrix_classification(resource_type, kind):
    assert DependencyGraphService._resource_kind(resource_type.lower()) == kind


def test_adjacent_direction_keeps_mixed_dependency_prefixes():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=2)
    root = service._add_node(analysis, "resource", "root", {"rid": "root"})
    middle = service._add_node(analysis, "resource", "middle", {"rid": "middle"})
    leaf = service._add_node(analysis, "resource", "leaf", {"rid": "leaf"})
    service._add_edge(analysis, root.id, middle.id, "schedule-produces-resource", [])
    service._add_edge(analysis, leaf.id, middle.id, "schedule-produces-resource", [])
    paths = service._derive_paths(analysis, root.id, "adjacent")
    assert [path["related_node_id"] for path in paths] == [leaf.id]
    assert paths[0]["direction"] == "adjacent"


def test_exact_build_model_and_wrapper_schema_have_no_target():
    assert "target" not in orchestration_models.Build.model_fields
    build = orchestration_models.Build(
        rid="ri.orchestration.main.build.test",
        branch_name="master",
        created_time=datetime.now(timezone.utc),
        created_by="00000000-0000-0000-0000-000000000001",
        fallback_branches=[],
        job_rids=[],
        retry_count=0,
        retry_backoff_duration=core_models.Duration(value=1, unit="SECONDS"),
        abort_on_failure=False,
        status="SUCCEEDED",
        finished_time=None,
        schedule_rid="ri.orchestration.main.schedule.test",
    )
    wrapper = OrchestrationService._format_build_info(
        OrchestrationService.__new__(OrchestrationService), build
    )
    assert "target" not in wrapper


def test_ranked_relationship_contains_readable_path_and_operation_evidence():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(analysis, "dataset", "Input", {"rid": "input"})
    related = service._add_node(analysis, "schedule", "Consumer", {"rid": "consumer"})
    operation = service._invoke_sdk(
        analysis,
        "dataset.get-schedules",
        Mock(return_value={}),
        {"dataset_rid": "input", "branch_name": "feature"},
        target="input",
    )[1]
    evidence = service._add_evidence(
        analysis, operation, "scheduleRids[0]", "schedule_rids[0]", "consumer"
    )
    service._add_edge(
        analysis,
        root.id,
        related.id,
        "schedule-consumes-resource",
        [evidence.id],
    )

    ranked = service._rank_paths(
        analysis, service._derive_paths(analysis, root.id, "both"), "change schema"
    )

    assert ranked[0]["readable_path"] == "Input -> Consumer"
    assert ranked[0]["direction"] == "downstream"
    assert ranked[0]["first_evidence_locator"] == "scheduleRids[0]"
    assert ranked[0]["sdk_namespace"] == "client.datasets.Dataset"
    assert ranked[0]["sdk_method"] == "get_schedules"


def test_change_assessment_keeps_uncertainty_alongside_verified_impacts():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(analysis, "dataset", "Input", {"rid": "input"})
    service._add_gap(
        analysis,
        root.id,
        "schedule-reverse-index",
        "partial",
        "schedule-index-may-be-stale",
        "May lag by up to one hour",
    )
    assessment = service._assess_change(
        "rename output",
        [
            {
                "id": "path",
                "related_node_id": root.id,
                "direction": "downstream",
                "relation_kind": "schedule-produces-resource",
                "readable_path": "Input",
            }
        ],
        analysis,
    )

    assert assessment["ranked_impacts"]
    assert assessment["uncertainty"][0]["reason_code"] == "schedule-index-may-be-stale"
    assert (
        "Resolve or accept intersecting coverage gaps"
        in assessment["verification_needed"]
    )


def _resolver_client():
    object_model = ontology_models.ObjectTypeV2.model_construct(
        api_name="Employee",
        display_name="Employee",
        properties={"name": SimpleNamespace()},
    )
    object_metadata = ontology_models.ObjectTypeFullMetadata.model_construct(
        object_type=object_model,
        link_types=[],
        implements_interfaces=[],
        implements_interfaces2={},
        shared_property_type_mapping={},
    )
    link = ontology_models.LinkTypeSideV2.model_construct(
        api_name="manager", object_type_api_name="Manager"
    )
    action = ontology_models.ActionTypeFullMetadata.model_construct(
        action_type=ontology_models.ActionTypeV2.model_construct(
            api_name="HireEmployee", parameters={}
        ),
        full_logic_rules=[],
    )
    query = _recursive_query()
    resource = filesystem_models.Resource.model_construct(
        rid="ri.foundry.main.dataset.employee",
        display_name="Employees",
        type="dataset",
    )
    return SimpleNamespace(
        ontologies=SimpleNamespace(
            Ontology=SimpleNamespace(
                ObjectType=SimpleNamespace(
                    get_full_metadata=Mock(return_value=object_metadata),
                    get_outgoing_link_type=Mock(return_value=link),
                ),
                QueryType=SimpleNamespace(
                    list=Mock(
                        return_value=SimpleNamespace(data=[query], next_page_token=None)
                    )
                ),
            ),
            ActionTypeFullMetadata=SimpleNamespace(
                get=Mock(return_value=action),
                list=Mock(
                    return_value=SimpleNamespace(data=[action], next_page_token=None)
                ),
            ),
        ),
        filesystem=SimpleNamespace(
            Resource=SimpleNamespace(get=Mock(return_value=resource))
        ),
    )


def test_all_six_real_resolvers_use_pinned_shaped_results_and_provenance():
    client = _resolver_client()
    service = DependencyGraphService(client=client)
    analysis = context()
    ontology = "ri.ontology.main.ontology.test"

    targets = [
        service.resolve_object_type(analysis, ontology, "Employee"),
        service.resolve_property(analysis, ontology, "Employee", "name"),
        service.resolve_link_type(analysis, ontology, "Employee", "manager"),
        service.resolve_action_type(analysis, ontology, "HireEmployee"),
        service.resolve_query_type(analysis, ontology, "RecursiveQuery"),
        service.resolve_resource(analysis, "ri.foundry.main.dataset.employee"),
    ]

    assert [target.kind for target in targets] == [
        "object-type",
        "property",
        "link-type",
        "action-type",
        "query-type",
        "dataset",
    ]
    assert targets[1].identifiers["property"] == "name"
    assert targets[2].identifiers["link_type"] == "manager"
    assert targets[5].display_name == "Employees"
    assert all(target.node_id in analysis.nodes for target in targets)
    assert {
        operation.read_context_id
        for operation in analysis.operation_provenance.values()
    } == {analysis.read_context.id}
    assert all(
        operation.request_timeout_seconds <= 30
        for operation in analysis.operation_provenance.values()
    )
    object_calls = (
        client.ontologies.Ontology.ObjectType.get_full_metadata.call_args_list
    )
    assert all(call.kwargs["branch"] == "feature" for call in object_calls)
    assert all(call.kwargs["preview"] is True for call in object_calls)
    assert client.filesystem.Resource.get.call_args.kwargs.get("branch") is None
    resource_evidence = [
        value for value in analysis.evidence.values() if value.locator == "resource"
    ]
    assert len(resource_evidence) == 1
    assert resource_evidence[0].operation_provenance_id in analysis.operation_provenance


def test_action_and_query_indexes_forward_second_page_tokens_and_charge_globally():
    client = _resolver_client()
    action = client.ontologies.ActionTypeFullMetadata.get.return_value
    query = client.ontologies.Ontology.QueryType.list.return_value.data[0]
    client.ontologies.ActionTypeFullMetadata.list.side_effect = [
        SimpleNamespace(data=[action], next_page_token="action-next"),
        SimpleNamespace(data=[], next_page_token=None),
    ]
    client.ontologies.Ontology.QueryType.list.side_effect = [
        SimpleNamespace(data=[query], next_page_token="query-next"),
        SimpleNamespace(data=[], next_page_token=None),
    ]
    service = DependencyGraphService(client=client)
    analysis = context()

    service._get_action_index(analysis, "ontology")
    service._get_query_index(analysis, "ontology")

    action_calls = client.ontologies.ActionTypeFullMetadata.list.call_args_list
    query_calls = client.ontologies.Ontology.QueryType.list.call_args_list
    assert "page_token" not in action_calls[0].kwargs
    assert action_calls[1].kwargs["page_token"] == "action-next"
    assert "page_token" not in query_calls[0].kwargs
    assert query_calls[1].kwargs["page_token"] == "query-next"
    assert analysis.budget.used_requests == 4
    assert analysis.budget.used_pages == 4
    assert analysis.budget.used_items == 2
    assert all(
        1 <= call.kwargs["request_timeout"] <= 30
        for call in [*action_calls, *query_calls]
    )


def test_schedule_reverse_index_pages_create_per_subject_conditional_records(
    monkeypatch,
):
    calls = []

    def schedules(self, **kwargs):
        calls.append(kwargs)
        if kwargs.get("page_token") is None:
            return {"schedule_rids": ["schedule-a"], "next_page_token": "next"}
        return {"schedule_rids": ["schedule-b"], "next_page_token": None}

    monkeypatch.setattr(
        "pltr.services.dependency.DatasetService.get_schedule_rids_page", schedules
    )
    monkeypatch.setattr(
        DependencyGraphService,
        "_collect_schedule",
        lambda self, context, root, schedule_node, orchestration, records: None,
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(
        analysis,
        "dataset",
        "root",
        {"resource_rid": "ri.foundry.main.dataset.root"},
        True,
    )

    result = service.analyze(
        DependencyTarget("dataset", root.identifiers, root.display_name, root.id),
        analysis,
    )

    assert "page_token" not in calls[0]
    assert calls[1]["page_token"] == "next"
    assert analysis.budget.used_requests == 2
    assert analysis.budget.used_pages == 2
    assert analysis.budget.used_items == 2
    schedule_ids = {
        node["id"] for node in result["graph"]["nodes"] if node["kind"] == "schedule"
    }
    conditional = [
        record
        for record in result["coverage"]
        if record["subject_node_id"] in schedule_ids
    ]
    assert len(conditional) == 8
    assert all(record["status"] == "unresolved" for record in conditional)
    assert (
        len(
            [
                gap
                for gap in result["gaps"]
                if gap["reason_code"] == "collector-did-not-report"
                and gap["target"] in schedule_ids
            ]
        )
        == 8
    )
    stale = [
        gap
        for gap in result["gaps"]
        if gap["reason_code"] == "schedule-index-may-be-stale"
    ]
    assert len(stale) == 1
    assert (
        next(
            record
            for record in result["coverage"]
            if record["surface"] == "schedule-reverse-index"
        )["status"]
        == "partial"
    )


def test_schedule_runs_and_build_jobs_forward_page_tokens_and_share_budget():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    schedule = service._add_node(
        analysis, "schedule", "schedule", {"schedule_rid": "schedule"}
    )
    runs_record = service._coverage_record(
        analysis, "schedule", "schedule-runs", schedule.id
    )
    run_calls = Mock(
        side_effect=[
            {
                "runs": [{"rid": "run-a", "result": {"type": "ignored"}}],
                "next_page_token": "run-next",
            },
            {
                "runs": [{"rid": "run-b", "result": None}],
                "next_page_token": None,
            },
        ]
    )
    orchestration = SimpleNamespace(get_schedule_runs=run_calls)
    service._collect_runs(analysis, schedule, orchestration, runs_record)

    build = service._add_node(analysis, "build", "build", {"build_rid": "build"})
    jobs_record = service._coverage_record(analysis, "build", "build-jobs", build.id)
    job_calls = Mock(
        side_effect=[
            {
                "jobs": [{"rid": "job-a", "outputs": []}],
                "next_page_token": "job-next",
            },
            {
                "jobs": [{"rid": "job-b", "outputs": []}],
                "next_page_token": None,
            },
        ]
    )
    orchestration.get_build_jobs = job_calls
    service._collect_jobs(analysis, build, orchestration, jobs_record)

    assert "page_token" not in run_calls.call_args_list[0].kwargs
    assert run_calls.call_args_list[1].kwargs["page_token"] == "run-next"
    assert "page_token" not in job_calls.call_args_list[0].kwargs
    assert job_calls.call_args_list[1].kwargs["page_token"] == "job-next"
    assert analysis.budget.used_requests == 4
    assert analysis.budget.used_pages == 4
    assert analysis.budget.used_items == 4
    assert all(
        1 <= call.kwargs["request_timeout"] <= 30
        for call in [*run_calls.call_args_list, *job_calls.call_args_list]
    )


@pytest.mark.parametrize(
    ("dimension", "budget_values"),
    [
        ("pages", {"max_pages": 1}),
        ("items", {"max_items": 2}),
    ],
)
@pytest.mark.parametrize(
    ("collector", "page_cap"),
    [
        ("action-index", 500),
        ("query-index", 100),
        ("dataset-schedules", 100),
        ("schedule-runs", 100),
        ("build-jobs", 100),
    ],
)
def test_every_paginator_refuses_sdk_calls_after_global_capacity_is_spent(
    monkeypatch, collector, page_cap, dimension, budget_values
):
    analysis = context(**budget_values)
    if dimension == "items":
        analysis.budget.charge("items")
    first_page = Mock()
    record = None

    if collector == "action-index":
        item = SimpleNamespace(action_type=SimpleNamespace(api_name="Action"))
        first_page.return_value = SimpleNamespace(data=[item], next_page_token="next")
        service = DependencyGraphService(
            client=SimpleNamespace(
                ontologies=SimpleNamespace(
                    ActionTypeFullMetadata=SimpleNamespace(list=first_page)
                )
            )
        )
        result = service._get_action_index(analysis, "ontology")
        exhausted = result["incomplete_error"]
        assert len(result["entries"]) == 1
    elif collector == "query-index":
        item = SimpleNamespace(api_name="Query")
        first_page.return_value = SimpleNamespace(data=[item], next_page_token="next")
        service = DependencyGraphService(
            client=SimpleNamespace(
                ontologies=SimpleNamespace(
                    Ontology=SimpleNamespace(QueryType=SimpleNamespace(list=first_page))
                )
            )
        )
        result = service._get_query_index(analysis, "ontology")
        exhausted = result["incomplete_error"]
        assert len(result["entries"]) == 1
    elif collector == "dataset-schedules":
        first_page.return_value = {
            "schedule_rids": ["schedule-a"],
            "next_page_token": "next",
        }
        monkeypatch.setattr(
            "pltr.services.dependency.DatasetService.get_schedule_rids_page",
            lambda self, **kwargs: first_page(**kwargs),
        )
        service = DependencyGraphService(client=SimpleNamespace())
        target = _dataset_target(service, analysis)
        service._collect_dataset(target, analysis)
        exhausted = analysis.caches[("budget-exhausted",)]
        record = service._coverage_record(
            analysis, "dataset", "schedule-reverse-index", target.node_id
        )
    elif collector == "schedule-runs":
        first_page.return_value = {
            "runs": [{"rid": "run-a", "result": {"type": "ignored"}}],
            "next_page_token": "next",
        }
        service = DependencyGraphService(client=SimpleNamespace())
        schedule = service._add_node(
            analysis, "schedule", "schedule", {"schedule_rid": "schedule"}
        )
        record = service._coverage_record(
            analysis, "schedule", "schedule-runs", schedule.id
        )
        service._collect_runs(
            analysis,
            schedule,
            SimpleNamespace(get_schedule_runs=first_page),
            record,
        )
        exhausted = analysis.caches[("budget-exhausted",)]
    else:
        first_page.return_value = {
            "jobs": [{"rid": "job-a", "outputs": []}],
            "next_page_token": "next",
        }
        service = DependencyGraphService(client=SimpleNamespace())
        build = service._add_node(analysis, "build", "build", {"build_rid": "build"})
        record = service._coverage_record(analysis, "build", "build-jobs", build.id)
        service._collect_jobs(
            analysis,
            build,
            SimpleNamespace(get_build_jobs=first_page),
            record,
        )
        exhausted = analysis.caches[("budget-exhausted",)]

    assert isinstance(exhausted, BudgetExhausted)
    assert exhausted.dimension == dimension
    first_page.assert_called_once()
    assert "page_token" not in first_page.call_args.kwargs
    assert first_page.call_args.kwargs["page_size"] == (
        1 if dimension == "items" else page_cap
    )
    assert analysis.budget.used_pages == 1
    assert analysis.budget.used_items == (2 if dimension == "items" else 1)
    assert analysis.budget.used_requests == 1
    if record is not None:
        assert record.status == "budget-exhausted"
        assert record.evidence_ids


def test_two_submitted_builds_create_subject_local_build_job_and_output_coverage():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    schedule = service._add_node(
        analysis, "schedule", "schedule", {"schedule_rid": "schedule"}
    )
    runs_record = service._coverage_record(
        analysis, "schedule", "schedule-runs", schedule.id
    )

    def get_build(*, build_rid, request_timeout):
        return {"rid": build_rid, "job_rids": [f"{build_rid}-job"]}

    def get_jobs(*, build_rid, page_size, request_timeout):
        return {
            "jobs": [
                {
                    "rid": f"{build_rid}-job",
                    "outputs": [
                        {
                            "type": "datasetJobOutput",
                            "dataset_rid": f"ri.foundry.main.dataset.{build_rid[-1]}",
                        }
                    ],
                }
            ],
            "next_page_token": None,
        }

    orchestration = SimpleNamespace(
        get_schedule_runs=Mock(
            return_value={
                "runs": [
                    {
                        "rid": "run-a",
                        "result": {"type": "submitted", "build_rid": "build-a"},
                    },
                    {
                        "rid": "run-b",
                        "result": {"type": "submitted", "build_rid": "build-b"},
                    },
                ],
                "next_page_token": None,
            }
        ),
        get_build=Mock(side_effect=get_build),
        get_build_jobs=Mock(side_effect=get_jobs),
    )

    service._collect_runs(analysis, schedule, orchestration, runs_record)

    build_nodes = [node for node in analysis.nodes.values() if node.kind == "build"]
    job_nodes = [node for node in analysis.nodes.values() if node.kind == "job"]
    assert len(build_nodes) == len(job_nodes) == 2
    build_records = [
        service._coverage_record(analysis, "build", "submitted-build", node.id)
        for node in build_nodes
    ]
    job_records = [
        service._coverage_record(analysis, "build", "build-jobs", node.id)
        for node in build_nodes
    ]
    output_records = [
        service._coverage_record(analysis, "job", "typed-outputs", node.id)
        for node in job_nodes
    ]
    assert all(
        record.status == "covered" and record.evidence_ids for record in build_records
    )
    assert all(
        record.status == "covered" and record.evidence_ids for record in job_records
    )
    assert all(
        record.status == "partial" and record.evidence_ids for record in output_records
    )
    assert {record.parent_record_id for record in job_records} == {
        record.id for record in build_records
    }
    assert {record.parent_record_id for record in output_records} == {
        record.id for record in job_records
    }


@pytest.mark.parametrize(
    ("collector", "surface", "subject_kind"),
    [
        ("_collect_build", "submitted-build", "build"),
        ("_collect_jobs", "build-jobs", "build"),
        ("_collect_outputs", "typed-outputs", "job"),
    ],
)
def test_deep_conditional_coverage_is_subject_local_when_one_collector_is_suppressed(
    monkeypatch, collector, surface, subject_kind
):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    schedule = service._add_node(
        analysis, "schedule", "schedule", {"schedule_rid": "schedule"}
    )
    runs_record = service._coverage_record(
        analysis, "schedule", "schedule-runs", schedule.id
    )
    orchestration = SimpleNamespace(
        get_schedule_runs=Mock(
            return_value={
                "runs": [
                    {
                        "rid": "run-a",
                        "result": {"type": "submitted", "build_rid": "build-a"},
                    },
                    {
                        "rid": "run-b",
                        "result": {"type": "submitted", "build_rid": "build-b"},
                    },
                ],
                "next_page_token": None,
            }
        ),
        get_build=Mock(
            side_effect=lambda *, build_rid, request_timeout: {
                "rid": build_rid,
                "job_rids": [f"{build_rid}-job"],
            }
        ),
        get_build_jobs=Mock(
            side_effect=lambda *, build_rid, page_size, request_timeout: {
                "jobs": [
                    {
                        "rid": f"{build_rid}-job",
                        "outputs": [
                            {
                                "type": "datasetJobOutput",
                                "dataset_rid": f"ri.foundry.main.dataset.{build_rid[-1]}",
                            }
                        ],
                    }
                ],
                "next_page_token": None,
            }
        ),
    )

    original = getattr(service, collector)
    if collector == "_collect_build":

        def selective(context_value, build_node, orchestration_value, record):
            if build_node.identifiers["build_rid"] == "build-b":
                return
            original(context_value, build_node, orchestration_value, record)
    elif collector == "_collect_jobs":

        def selective(context_value, build_node, orchestration_value, record):
            if build_node.identifiers["build_rid"] == "build-b":
                return
            original(context_value, build_node, orchestration_value, record)
    else:

        def selective(
            context_value,
            build_node,
            job_node,
            job,
            operation_id,
            job_index,
            record,
        ):
            if build_node.identifiers["build_rid"] == "build-b":
                return
            original(
                context_value,
                build_node,
                job_node,
                job,
                operation_id,
                job_index,
                record,
            )

    monkeypatch.setattr(service, collector, selective)

    service._collect_runs(analysis, schedule, orchestration, runs_record)
    service._complete_coverage(analysis)

    suppressed_subject = next(
        node
        for node in analysis.nodes.values()
        if node.kind == subject_kind and "build-b" in node.display_name
    )
    sibling_subject = next(
        node
        for node in analysis.nodes.values()
        if node.kind == subject_kind and "build-a" in node.display_name
    )
    suppressed = service._coverage_record(
        analysis, subject_kind, surface, suppressed_subject.id
    )
    sibling = service._coverage_record(
        analysis, subject_kind, surface, sibling_subject.id
    )
    assert suppressed.status == "unresolved"
    assert suppressed.reason == "collector-did-not-report"
    assert sibling.status in {"covered", "partial"}
    assert any(
        gap.target == suppressed_subject.id
        and gap.surface == surface
        and gap.reason_code == "collector-did-not-report"
        for gap in analysis.gaps.values()
    )
    assert not any(
        gap.target == sibling_subject.id
        and gap.surface == surface
        and gap.reason_code == "collector-did-not-report"
        for gap in analysis.gaps.values()
    )


def test_real_resolvers_fail_closed_for_missing_members_and_expected_api_errors():
    client = _resolver_client()
    service = DependencyGraphService(client=client)
    ontology = "ri.ontology.main.ontology.test"

    with pytest.raises(DependencyFatalError) as missing_property:
        service.resolve_property(context(), ontology, "Employee", "missing")
    assert missing_property.value.error_class == "not-found"

    with pytest.raises(DependencyFatalError) as missing_query:
        service.resolve_query_type(context(), ontology, "MissingQuery")
    assert missing_query.value.error_class == "not-found"

    client.ontologies.Ontology.ObjectType.get_full_metadata.side_effect = (
        sdk_errors.PermissionDeniedError({})
    )
    with pytest.raises(DependencyFatalError) as denied:
        service.resolve_object_type(context(), ontology, "Employee")
    assert denied.value.error_class == "permission-denied"


def test_programming_and_invariant_errors_are_not_downgraded_to_gaps():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(analysis, "build", "build", {"build_rid": "build"})
    record = service._coverage_record(analysis, "build", "submitted-build", node.id)

    with pytest.raises(ValueError, match="wrapper invariant"):
        service._record_failure(
            analysis, record, ValueError("wrapper invariant"), "build.get"
        )

    assert record.complete is False
    assert not analysis.gaps


def _dataset_target(service, analysis):
    node = service._add_node(
        analysis,
        "dataset",
        "dataset",
        {"resource_rid": "ri.foundry.main.dataset.test"},
        True,
    )
    return DependencyTarget("dataset", node.identifiers, node.display_name, node.id)


def test_actual_dataset_wrapper_preserves_retryable_sdk_cause_as_local_gap():
    get_schedules = Mock(side_effect=sdk_errors.RateLimitError("limited", "rate"))
    client = SimpleNamespace(
        datasets=SimpleNamespace(Dataset=SimpleNamespace(get_schedules=get_schedules))
    )
    service = DependencyGraphService(client=client)
    analysis = context()
    target = _dataset_target(service, analysis)

    result = service.analyze(target, analysis)

    reverse = next(
        record
        for record in result["coverage"]
        if record["subject_node_id"] == target.node_id
        and record["surface"] == "schedule-reverse-index"
    )
    gap = next(
        gap
        for gap in result["gaps"]
        if gap["target"] == target.node_id
        and gap["surface"] == "schedule-reverse-index"
    )
    assert reverse["status"] == "partial"
    assert reverse["reason"] == "rate-limited"
    assert gap["reason_code"] == "rate-limited"
    assert gap["retryable"] is True
    assert gap["operation"] == "dataset.get-schedules"


def test_actual_orchestration_wrapper_preserves_inaccessible_cause_on_schedule():
    client = SimpleNamespace(
        datasets=SimpleNamespace(
            Dataset=SimpleNamespace(
                get_schedules=Mock(
                    return_value=SimpleNamespace(
                        data=["ri.orchestration.main.schedule.test"],
                        next_page_token=None,
                    )
                )
            )
        ),
        orchestration=SimpleNamespace(
            Schedule=SimpleNamespace(
                get=Mock(side_effect=sdk_errors.PermissionDeniedError({})),
                get_affected_resources=Mock(return_value={"datasets": []}),
                runs=Mock(return_value=SimpleNamespace(data=[], next_page_token=None)),
            )
        ),
    )
    service = DependencyGraphService(client=client)
    analysis = context()
    target = _dataset_target(service, analysis)

    result = service.analyze(target, analysis)

    schedule = next(
        node for node in result["graph"]["nodes"] if node["kind"] == "schedule"
    )
    denied = [
        gap
        for gap in result["gaps"]
        if gap["target"] == schedule["id"] and gap["reason_code"] == "permission-denied"
    ]
    assert {gap["surface"] for gap in denied} == {
        "schedule-detail-action",
        "schedule-trigger",
    }
    assert all(
        gap["coverage"] == "inaccessible" and not gap["retryable"] for gap in denied
    )
    reverse = next(
        record
        for record in result["coverage"]
        if record["surface"] == "schedule-reverse-index"
    )
    assert reverse["status"] == "partial"
    assert any(
        gap["reason_code"] == "schedule-index-may-be-stale" for gap in result["gaps"]
    )


def test_actual_dataset_wrapper_plain_invariant_error_propagates_without_unknown_gap():
    client = SimpleNamespace(
        datasets=SimpleNamespace(
            Dataset=SimpleNamespace(
                get_schedules=Mock(
                    return_value=SimpleNamespace(data=[object()], next_page_token=None)
                )
            )
        )
    )
    service = DependencyGraphService(client=client)
    analysis = context()
    target = _dataset_target(service, analysis)

    with pytest.raises(RuntimeError) as raised:
        service.analyze(target, analysis)

    assert isinstance(raised.value.__cause__, ValueError)
    assert not any(gap.reason_code == "unknown" for gap in analysis.gaps.values())


def test_output_budget_failure_is_job_local_and_parent_job_evidence_is_preserved():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_items=2)
    build = service._add_node(analysis, "build", "build", {"build_rid": "build"})
    record = service._coverage_record(analysis, "build", "build-jobs", build.id)
    orchestration = SimpleNamespace(
        get_build_jobs=Mock(
            return_value={
                "jobs": [
                    {
                        "rid": "job",
                        "outputs": [
                            {"type": "datasetJobOutput", "dataset_rid": "dataset-a"},
                            {"type": "datasetJobOutput", "dataset_rid": "dataset-b"},
                        ],
                    }
                ],
                "next_page_token": None,
            }
        )
    )

    service._collect_jobs(analysis, build, orchestration, record)

    job = next(node for node in analysis.nodes.values() if node.kind == "job")
    output_record = service._coverage_record(analysis, "job", "typed-outputs", job.id)
    assert record.status == "covered" and record.evidence_ids
    assert output_record.status == "budget-exhausted" and output_record.evidence_ids
    assert any(
        gap.target == job.id
        and gap.surface == "typed-outputs"
        and gap.reason_code == "budget-exhausted"
        for gap in analysis.gaps.values()
    )
    assert not any(
        gap.target == build.id and gap.reason_code == "budget-exhausted"
        for gap in analysis.gaps.values()
    )


def test_nested_build_budget_does_not_reclassify_successful_schedule_runs():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_requests=1)
    schedule = service._add_node(
        analysis, "schedule", "schedule", {"schedule_rid": "schedule"}
    )
    record = service._coverage_record(
        analysis, "schedule", "schedule-runs", schedule.id
    )
    orchestration = SimpleNamespace(
        get_schedule_runs=Mock(
            return_value={
                "runs": [
                    {
                        "rid": "run",
                        "result": {"type": "submitted", "build_rid": "build"},
                    }
                ],
                "next_page_token": None,
            }
        ),
        get_build=Mock(
            side_effect=AssertionError("request budget must refuse child SDK call")
        ),
    )

    service._collect_runs(analysis, schedule, orchestration, record)

    build = next(node for node in analysis.nodes.values() if node.kind == "build")
    build_record = service._coverage_record(
        analysis, "build", "submitted-build", build.id
    )
    assert record.status == "covered" and record.evidence_ids
    assert build_record.status == "budget-exhausted"
    assert not any(
        gap.target == schedule.id and gap.reason_code == "budget-exhausted"
        for gap in analysis.gaps.values()
    )


def test_nested_job_budget_preserves_successful_build_evidence():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_requests=1)
    build = service._add_node(analysis, "build", "build", {"build_rid": "build"})
    record = service._coverage_record(analysis, "build", "submitted-build", build.id)
    orchestration = SimpleNamespace(
        get_build=Mock(return_value={"rid": "build", "job_rids": ["job"]}),
        get_build_jobs=Mock(
            side_effect=AssertionError("request budget must refuse jobs SDK call")
        ),
    )

    service._collect_build(analysis, build, orchestration, record)

    jobs_record = service._coverage_record(analysis, "build", "build-jobs", build.id)
    assert record.status == "covered" and record.evidence_ids
    assert jobs_record.status == "budget-exhausted"
    assert any(
        gap.target == build.id
        and gap.surface == "build-jobs"
        and gap.reason_code == "budget-exhausted"
        for gap in analysis.gaps.values()
    )


def test_nested_schedule_budget_preserves_reverse_index_evidence_and_stale_gap(
    monkeypatch,
):
    monkeypatch.setattr(
        "pltr.services.dependency.DatasetService.get_schedule_rids_page",
        lambda self, **kwargs: {
            "schedule_rids": ["schedule"],
            "next_page_token": None,
        },
    )
    monkeypatch.setattr(
        "pltr.services.dependency.OrchestrationService.get_schedule",
        lambda self, **kwargs: {
            "action": {
                "target": {
                    "type": "connecting",
                    "input_rids": ["ri.foundry.main.dataset.input"],
                    "target_rids": [],
                }
            },
            "trigger": {"type": "manual"},
            "scope_mode": {"type": "user"},
        },
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_items=1)
    target = _dataset_target(service, analysis)

    result = service.analyze(target, analysis)

    reverse = next(
        record
        for record in result["coverage"]
        if record["surface"] == "schedule-reverse-index"
    )
    schedule = next(
        node for node in result["graph"]["nodes"] if node["kind"] == "schedule"
    )
    assert reverse["status"] == "partial" and reverse["evidence_ids"]
    assert (
        sum(
            gap["reason_code"] == "schedule-index-may-be-stale"
            for gap in result["gaps"]
        )
        == 1
    )
    assert any(
        gap["target"] == schedule["id"]
        and gap["surface"] == "schedule-detail-action"
        and gap["reason_code"] == "budget-exhausted"
        for gap in result["gaps"]
    )
    assert not any(
        gap["target"] == target.node_id and gap["reason_code"] == "budget-exhausted"
        for gap in result["gaps"]
    )


def test_schedule_budget_partial_evidence_never_crosses_schedule_subjects():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_items=1)
    schedule_a = service._add_node(
        analysis, "schedule", "schedule-a", {"schedule_rid": "schedule-a"}
    )
    schedule_b = service._add_node(
        analysis, "schedule", "schedule-b", {"schedule_rid": "schedule-b"}
    )
    resource = service._add_node(
        analysis, "dataset", "input", {"resource_rid": "input"}
    )
    evidence_a = service._add_evidence(
        analysis,
        "operation-a",
        "action.target.input_rids[0]",
        "action.target.input_rids[0]",
        "input",
    )
    service._add_edge(
        analysis,
        resource.id,
        schedule_a.id,
        "schedule-consumes-resource",
        [evidence_a.id],
    )
    records = {
        surface: service._coverage_record(analysis, "schedule", surface, schedule_b.id)
        for surface in (
            "schedule-detail-action",
            "schedule-trigger",
            "schedule-affected-resources",
            "schedule-runs",
        )
    }
    analysis.budget.charge("items")
    orchestration = SimpleNamespace(
        get_schedule=Mock(
            return_value={
                "action": {
                    "target": {
                        "type": "connecting",
                        "input_rids": ["other-input"],
                        "target_rids": [],
                    }
                },
                "trigger": {"type": "manual"},
                "scope_mode": {"type": "user"},
            }
        )
    )

    service._collect_schedule(
        analysis,
        DependencyTarget("dataset", {"resource_rid": "root"}),
        schedule_b,
        orchestration,
        records,
    )

    assert records["schedule-detail-action"].status == "budget-exhausted"
    assert evidence_a.id not in records["schedule-detail-action"].evidence_ids


def test_unreachable_query_definition_is_not_walked_or_charged():
    class ExplodingDefinition:
        @property
        def type(self):
            raise AssertionError("unreachable definition was inspected")

    query = SimpleNamespace(type_references={"UNREACHABLE": ExplodingDefinition()})
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_items=1)

    closure = service._build_query_reference_closure(
        query,
        {
            "output": ontology_models.OntologyObjectType(
                object_api_name="Employee", object_type_api_name="Employee"
            )
        },
        analysis,
    )

    assert {leaf["name"] for leaf in closure["output"]["leaves"]} == {"Employee"}
    assert analysis.budget.used_items == 1


def test_iterative_scc_handles_a_chain_beyond_python_recursion_limit():
    graph = {str(index): {str(index + 1)} for index in range(1500)}
    graph["1500"] = set()

    components = DependencyGraphService._tarjan_scc(graph)

    assert len(components) == 1501
    assert components[0] == ("0",)


def test_action_metadata_walk_has_independent_pathological_depth_bound():
    nested_rule = {}
    for _ in range(METADATA_WALK_MAX_DEPTH + 1):
        nested_rule = {"nested": nested_rule}
    metadata = ontology_models.ActionTypeFullMetadata.model_construct(
        action_type=ontology_models.ActionTypeV2.model_construct(
            api_name="DeepAction", parameters={}
        ),
        full_logic_rules=[{"type": "futureRule", "nested": nested_rule}],
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=1)
    node = service._add_node(
        analysis,
        "action-type",
        "DeepAction",
        {"ontology_rid": "ontology", "action_type": "DeepAction"},
        True,
    )
    analysis.caches[("action-metadata", "ontology", "feature", "DeepAction")] = (
        metadata,
        "operation",
    )

    service._collect_action_target(
        DependencyTarget("action-type", node.identifiers, node.display_name, node.id),
        analysis,
    )

    record = service._coverage_record(
        analysis, "action-type", "full-action-metadata", node.id
    )
    assert record.status == "budget-exhausted"
    gap = next(
        gap
        for gap in analysis.gaps.values()
        if gap.target == node.id
        and gap.surface == "full-action-metadata"
        and gap.reason_code == "budget-exhausted"
    )
    assert gap.budget_snapshot["limits"]["depth"] == 1
    assert gap.budget_snapshot["limits"]["metadata_depth"] == METADATA_WALK_MAX_DEPTH


def test_action_metadata_exhaustion_preserves_only_the_current_walk_references():
    parameters = {
        "a_employee": ontology_models.ActionParameterV2.model_construct(
            data_type=ontology_models.OntologyObjectType.model_construct(
                object_api_name="Employee", object_type_api_name="Employee"
            )
        ),
        "b_manager": ontology_models.ActionParameterV2.model_construct(
            data_type=ontology_models.OntologyObjectType.model_construct(
                object_api_name="Manager", object_type_api_name="Manager"
            )
        ),
    }
    metadata = ontology_models.ActionTypeFullMetadata.model_construct(
        action_type=ontology_models.ActionTypeV2.model_construct(
            api_name="PartialAction", parameters=parameters
        ),
        full_logic_rules=[],
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_items=1)

    with pytest.raises(BudgetExhausted) as exhausted:
        service._extract_action_references(metadata, "ontology", analysis, "operation")

    assert {
        (kind, name) for kind, name, _, _ in exhausted.value.partial_action_references
    } == {("object-type", "Employee")}


def test_query_metadata_depth_is_independent_of_graph_depth():
    query = SimpleNamespace(
        api_name="DeepQuery",
        parameters={},
        output=SimpleNamespace(
            type="union",
            union_types=[
                ontology_models.OntologyObjectType(
                    object_api_name="Employee", object_type_api_name="Employee"
                ),
                SimpleNamespace(
                    type="array",
                    sub_type=SimpleNamespace(
                        type="array",
                        sub_type=SimpleNamespace(type="string"),
                    ),
                ),
            ],
        ),
        type_references={},
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=1)
    node = service._add_node(
        analysis,
        "query-type",
        "DeepQuery",
        {"ontology_rid": "ontology", "query_type": "DeepQuery"},
        True,
    )
    analysis.caches[("query-metadata", "ontology", "feature", "DeepQuery")] = (
        query,
        "operation",
    )
    analysis.caches[("action-index", "test", "ontology", "feature")] = {
        "entries": [],
        "by_name": {},
        "incomplete_error": None,
    }

    service._collect_query_target(
        DependencyTarget("query-type", node.identifiers, node.display_name, node.id),
        analysis,
    )

    record = service._coverage_record(
        analysis, "query-type", "query-related-function-metadata", node.id
    )
    assert record.status == "covered"
    assert record.evidence_ids
    assert any(
        edge.relation_kind == "query-returns-object"
        and edge.source == node.id
        and analysis.nodes[edge.target].display_name == "Employee"
        for edge in analysis.edges.values()
    )


def test_query_metadata_has_an_independent_pathological_depth_bound():
    output = SimpleNamespace(type="string")
    for _ in range(METADATA_WALK_MAX_DEPTH + 1):
        output = SimpleNamespace(type="array", sub_type=output)
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=10)

    with pytest.raises(BudgetExhausted) as exhausted:
        service._build_query_reference_closure(
            SimpleNamespace(type_references={}), {"output": output}, analysis
        )

    assert exhausted.value.dimension == "metadata_depth"
    assert (
        exhausted.value.snapshot["limits"]["metadata_depth"] == METADATA_WALK_MAX_DEPTH
    )


def test_query_metadata_time_budget_is_subject_local():
    query = SimpleNamespace(
        api_name="TimedQuery",
        parameters={},
        output=SimpleNamespace(type="string"),
        type_references={},
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(time_budget_seconds=1)
    node = service._add_node(
        analysis,
        "query-type",
        "TimedQuery",
        {"ontology_rid": "ontology", "query_type": "TimedQuery"},
        True,
    )
    analysis.caches[("query-metadata", "ontology", "feature", "TimedQuery")] = (
        query,
        "operation",
    )
    analysis.budget._started_at -= 2

    service._collect_query_target(
        DependencyTarget("query-type", node.identifiers, node.display_name, node.id),
        analysis,
    )

    record = service._coverage_record(
        analysis, "query-type", "query-related-function-metadata", node.id
    )
    gap = next(
        gap
        for gap in analysis.gaps.values()
        if gap.target == node.id and gap.surface == "query-related-function-metadata"
    )
    assert record.status == "budget-exhausted"
    assert gap.reason_code == "budget-exhausted"
    assert gap.budget_snapshot["limits"]["time_budget_seconds"] == 1


def test_locator_distinct_gaps_remain_separate_and_mark_only_their_surface_partial():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(analysis, "query-type", "Query", {"query_type": "Query"})
    for index in range(2):
        service._add_gap(
            analysis,
            node.id,
            "query-related-function-metadata",
            "unresolved",
            "invalid-response",
            f"Missing reference at output.unionTypes[{index}]",
            locator=f"output.unionTypes[{index}]",
        )

    assert len(analysis.gaps) == 2
    assert {gap.locator for gap in analysis.gaps.values()} == {
        "output.unionTypes[0]",
        "output.unionTypes[1]",
    }
    assert service._has_reported_gap(
        analysis, node.id, "query-related-function-metadata"
    )
    assert not service._has_reported_gap(analysis, node.id, "full-action-metadata")


def test_object_metadata_collects_interface_link_and_shared_property_mappings():
    implementation = ontology_models.ObjectTypeInterfaceImplementation.model_construct(
        properties={"sharedName": "name"},
        properties_v2={},
        links={"managerLink": ["manager", "mentor"]},
    )
    metadata = ontology_models.ObjectTypeFullMetadata.model_construct(
        object_type=ontology_models.ObjectTypeV2.model_construct(
            api_name="Employee", properties={"name": SimpleNamespace()}
        ),
        link_types=[],
        implements_interfaces=[],
        implements_interfaces2={"Worker": implementation},
        shared_property_type_mapping={"sharedName": "name"},
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    target_node = service._add_node(
        analysis,
        "object-type",
        "Employee",
        {"ontology_rid": "ontology", "object_type": "Employee"},
        True,
    )
    target = DependencyTarget(
        "object-type", target_node.identifiers, "Employee", target_node.id
    )
    evidence = service._collect_object_interface_mappings(
        analysis,
        target,
        target_node,
        metadata,
        "operation",
        "ontology",
        "Employee",
    )

    assert evidence
    assert {node.kind for node in analysis.nodes.values()} >= {
        "interface-type",
        "interface-link-type",
        "shared-property-type",
        "property",
        "link-type",
    }
    assert (
        len(
            [
                edge
                for edge in analysis.edges.values()
                if edge.relation_kind == "container-member"
            ]
        )
        >= 4
    )
    assert not analysis.gaps


def test_properties_v2_materializes_every_reachable_backing_property_and_gaps_unknown():
    implementation = ontology_models.ObjectTypeInterfaceImplementation.model_construct(
        properties={},
        properties_v2={
            "displayName": ontology_models.InterfacePropertyLocalPropertyImplementation.model_construct(
                property_api_name="name"
            ),
            "officeCity": ontology_models.InterfacePropertyStructFieldImplementation.model_construct(
                struct_field_of_property=ontology_models.StructFieldOfPropertyImplementation.model_construct(
                    property_api_name="office", struct_field_api_name="city"
                )
            ),
            "contact": ontology_models.InterfacePropertyStructImplementation.model_construct(
                mapping={
                    "email": ontology_models.PropertyImplementation.model_construct(
                        property_api_name="email"
                    ),
                    "phone": ontology_models.StructFieldOfPropertyImplementation.model_construct(
                        property_api_name="contact", struct_field_api_name="phone"
                    ),
                }
            ),
            "primaryRegion": ontology_models.InterfacePropertyReducedPropertyImplementation.model_construct(
                implementation=ontology_models.InterfacePropertyLocalPropertyImplementation.model_construct(
                    property_api_name="regions"
                )
            ),
            "future": SimpleNamespace(type="futureImplementation"),
        },
        links={},
    )
    metadata = ontology_models.ObjectTypeFullMetadata.model_construct(
        object_type=ontology_models.ObjectTypeV2.model_construct(
            api_name="Employee", properties={}
        ),
        link_types=[],
        implements_interfaces=[],
        implements_interfaces2={"Worker": implementation},
        shared_property_type_mapping={},
    )
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    target_node = service._add_node(
        analysis,
        "object-type",
        "Employee",
        {"ontology_rid": "ontology", "object_type": "Employee"},
        True,
    )
    target = DependencyTarget(
        "object-type", target_node.identifiers, "Employee", target_node.id
    )

    evidence_ids = service._collect_object_interface_mappings(
        analysis,
        target,
        target_node,
        metadata,
        "operation",
        "ontology",
        "Employee",
    )

    backing_properties = {
        node.identifiers["property"]
        for node in analysis.nodes.values()
        if node.kind == "property"
    }
    assert backing_properties == {"name", "office", "email", "contact", "regions"}
    assert (
        len(
            [
                edge
                for edge in analysis.edges.values()
                if analysis.nodes[edge.source].kind == "interface-property-type"
                and analysis.nodes[edge.target].kind == "property"
            ]
        )
        == 5
    )
    evidence = [analysis.evidence[evidence_id] for evidence_id in evidence_ids]
    assert any(
        "officeCity.structFieldOfProperty.city" in item.locator for item in evidence
    )
    assert any("contact.mapping.phone.phone" in item.locator for item in evidence)
    assert any(
        "primaryRegion.implementation.propertyApiName" in item.locator
        for item in evidence
    )
    unknown = next(
        gap
        for gap in analysis.gaps.values()
        if gap.reason_code
        == "unknown-interface-property-v2-implementation:futureImplementation"
    )
    assert unknown.locator == "implementsInterfaces2.Worker.propertiesV2.future"


def test_reverse_action_shape_gap_remains_partial_for_each_subject_when_deduped():
    parameter = ontology_models.ActionParameterV2.model_construct(
        data_type=ontology_models.OntologyObjectType.model_construct(
            object_api_name="Employee", object_type_api_name="Employee"
        )
    )
    metadata = ontology_models.ActionTypeFullMetadata.model_construct(
        action_type=ontology_models.ActionTypeV2.model_construct(
            api_name="FutureAction", parameters={"employee": parameter}
        ),
        full_logic_rules=[SimpleNamespace(type="futureRule")],
    )
    client = SimpleNamespace(
        ontologies=SimpleNamespace(
            ActionTypeFullMetadata=SimpleNamespace(
                list=Mock(
                    return_value=SimpleNamespace(data=[metadata], next_page_token=None)
                )
            )
        )
    )
    service = DependencyGraphService(client=client)
    analysis = context()
    targets = []
    for object_type in ("Employee", "Manager"):
        node = service._add_node(
            analysis,
            "object-type",
            object_type,
            {"ontology_rid": "ontology", "object_type": object_type},
            True,
        )
        targets.append(
            DependencyTarget("object-type", node.identifiers, object_type, node.id)
        )

    for target in targets:
        service._collect_reverse_actions(target, analysis, "ontology")

    records = [
        service._coverage_record(
            analysis, "object-type", "full-action-metadata", target.node_id
        )
        for target in targets
    ]
    assert [record.status for record in records] == ["partial", "partial"]
    assert [record.reason for record in records] == [
        "action-metadata-shape-gap",
        "action-metadata-shape-gap",
    ]
    assert records[0].evidence_ids
    assert any(
        edge.relation_kind == "action-affects-object"
        and edge.target == targets[0].node_id
        for edge in analysis.edges.values()
    )
    assert (
        len(
            [
                gap
                for gap in analysis.gaps.values()
                if gap.reason_code == "unknown-action-logic-rule:futureRule"
            ]
        )
        == 1
    )


def test_reverse_action_budget_exhaustion_retains_completed_page_evidence():
    parameter = ontology_models.ActionParameterV2.model_construct(
        data_type=ontology_models.OntologyObjectType.model_construct(
            object_api_name="Employee", object_type_api_name="Employee"
        )
    )
    metadata = ontology_models.ActionTypeFullMetadata.model_construct(
        action_type=ontology_models.ActionTypeV2.model_construct(
            api_name="HireEmployee", parameters={"employee": parameter}
        ),
        full_logic_rules=[],
    )
    list_actions = Mock(
        return_value=SimpleNamespace(data=[metadata], next_page_token="next-page")
    )
    service = DependencyGraphService(
        client=SimpleNamespace(
            ontologies=SimpleNamespace(
                ActionTypeFullMetadata=SimpleNamespace(list=list_actions)
            )
        )
    )
    analysis = context(max_requests=1)
    target_node = service._add_node(
        analysis,
        "object-type",
        "Employee",
        {"ontology_rid": "ontology", "object_type": "Employee"},
        True,
    )
    target = DependencyTarget(
        "object-type", target_node.identifiers, "Employee", target_node.id
    )

    service._collect_reverse_actions(target, analysis, "ontology")

    record = service._coverage_record(
        analysis, "object-type", "full-action-metadata", target_node.id
    )
    assert record.status == "budget-exhausted"
    assert record.evidence_ids
    assert all(evidence_id in analysis.evidence for evidence_id in record.evidence_ids)
    assert all(
        analysis.evidence[evidence_id].operation_provenance_id
        in analysis.operation_provenance
        for evidence_id in record.evidence_ids
    )
    assert any(
        edge.relation_kind == "action-affects-object" and edge.target == target_node.id
        for edge in analysis.edges.values()
    )
    gap = next(
        gap
        for gap in analysis.gaps.values()
        if gap.target == target_node.id and gap.reason_code == "budget-exhausted"
    )
    assert gap.surface == "full-action-metadata"
    assert gap.budget_snapshot["used"]["requests"] == 1
    list_actions.assert_called_once()


def test_reverse_action_walk_exhaustion_retains_only_target_evidence():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    target_node = service._add_node(
        analysis,
        "object-type",
        "Employee",
        {"ontology_rid": "ontology", "object_type": "Employee"},
        True,
    )
    target = DependencyTarget(
        "object-type", target_node.identifiers, "Employee", target_node.id
    )
    operation_id = "shared-page-operation"
    department = service._add_evidence(
        analysis, operation_id, "first.department", "first.department", "Department"
    )
    employee = service._add_evidence(
        analysis, operation_id, "second.employee", "second.employee", "Employee"
    )
    manager = service._add_evidence(
        analysis, operation_id, "second.manager", "second.manager", "Manager"
    )
    exhausted = BudgetExhausted("items", analysis.budget.snapshot())
    exhausted.partial_action_references = [
        ("object-type", "Employee", "second.employee", employee.id),
        ("object-type", "Manager", "second.manager", manager.id),
    ]
    service._extract_action_references = Mock(
        side_effect=[
            [("object-type", "Department", "first.department", department.id)],
            exhausted,
        ]
    )
    analysis.caches[("action-index", "test", "ontology", "feature")] = {
        "entries": [
            (
                SimpleNamespace(action_type=SimpleNamespace(api_name="First")),
                operation_id,
            ),
            (
                SimpleNamespace(action_type=SimpleNamespace(api_name="Second")),
                operation_id,
            ),
        ],
        "by_name": {},
        "incomplete_error": None,
    }

    service._collect_reverse_actions(target, analysis, "ontology")

    record = service._coverage_record(
        analysis, "object-type", "full-action-metadata", target_node.id
    )
    assert record.status == "budget-exhausted"
    assert record.evidence_ids == [employee.id]


def test_reverse_query_walk_exhaustion_retains_only_target_leaves():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    target_node = service._add_node(
        analysis,
        "object-type",
        "Employee",
        {"ontology_rid": "ontology", "object_type": "Employee"},
        True,
    )
    target = DependencyTarget(
        "object-type", target_node.identifiers, "Employee", target_node.id
    )
    exhausted = BudgetExhausted("items", analysis.budget.snapshot())
    exhausted.partial_query_leaves = [
        ("object-type", "Department", "output.department"),
        ("object-type", "Employee", "output.employee"),
    ]
    service._build_query_reference_closure = Mock(side_effect=exhausted)
    analysis.caches[("query-index", "test", "ontology", "feature")] = {
        "entries": [
            (
                SimpleNamespace(
                    api_name="FindEmployee", parameters={}, output=SimpleNamespace()
                ),
                "operation",
            )
        ],
        "by_name": {},
        "incomplete_error": None,
    }

    service._collect_reverse_queries(target, analysis, "ontology")

    record = service._coverage_record(
        analysis,
        "object-type",
        "query-related-function-metadata",
        target_node.id,
    )
    assert record.status == "budget-exhausted"
    assert [
        analysis.evidence[evidence_id].locator for evidence_id in record.evidence_ids
    ] == ["output.employee"]


def test_nested_output_budget_dedupes_and_materializes_only_linear_co_output_edges():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_items=5)
    build = service._add_node(analysis, "build", "build", {"build_rid": "build"})
    job = service._add_node(analysis, "job", "job", {"job_rid": "job"})
    record = service._coverage_record(analysis, "job", "typed-outputs", job.id)
    outputs = [
        {"type": "datasetJobOutput", "dataset_rid": "ri.dataset.a"},
        {"type": "datasetJobOutput", "dataset_rid": "ri.dataset.a"},
        {"type": "datasetJobOutput", "dataset_rid": "ri.dataset.b"},
        {"type": "datasetJobOutput", "dataset_rid": "ri.dataset.c"},
    ]

    service._collect_outputs(
        analysis, build, job, {"outputs": outputs}, "operation", 0, record
    )

    co_outputs = [
        edge
        for edge in analysis.edges.values()
        if edge.relation_kind == "build-co-output"
    ]
    assert analysis.budget.used_items == 4
    assert len(co_outputs) == 2
    assert (
        len([node for node in analysis.nodes.values() if node.kind == "dataset"]) == 3
    )


def test_trigger_recursion_and_nested_trigger_items_share_global_bounds():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=1, max_items=10)
    schedule = service._add_node(
        analysis, "schedule", "schedule", {"schedule_rid": "schedule"}
    )
    trigger = {
        "type": "and",
        "triggers": [
            {
                "type": "or",
                "triggers": [{"type": "and", "triggers": [{"type": "manual"}]}],
            }
        ],
    }

    evidence, gap = service._collect_trigger(
        analysis, schedule, "operation", trigger, "trigger"
    )

    assert evidence == []
    assert gap is None
    assert analysis.budget.used_items == 4


def test_trigger_metadata_has_an_independent_pathological_depth_bound():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=10, max_items=METADATA_WALK_MAX_DEPTH + 2)
    schedule = service._add_node(
        analysis, "schedule", "schedule", {"schedule_rid": "schedule"}
    )
    trigger = {"type": "manual"}
    for _ in range(METADATA_WALK_MAX_DEPTH + 1):
        trigger = {"type": "and", "triggers": [trigger]}

    with pytest.raises(BudgetExhausted) as exhausted:
        service._collect_trigger(analysis, schedule, "operation", trigger, "trigger")

    assert exhausted.value.dimension == "metadata_depth"


def test_change_ranking_varies_by_relation_and_prefers_verified_coverage():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(analysis, "dataset", "root", {"resource_rid": "root"})
    schedule = service._add_node(
        analysis, "schedule", "nightly schedule", {"schedule_rid": "schedule"}
    )
    object_type = service._add_node(
        analysis, "object-type", "Employee schema", {"object_type": "Employee"}
    )
    service._add_edge(
        analysis,
        root.id,
        schedule.id,
        "schedule-produces-resource",
        [],
        coverage="partial",
    )
    service._add_edge(
        analysis,
        root.id,
        object_type.id,
        "container-member",
        [],
        coverage="verified",
    )
    paths = service._derive_paths(analysis, root.id, "both")

    schema_ranked = service._rank_paths(analysis, paths, "change schema type")
    schedule_ranked = service._rank_paths(analysis, paths, "change schedule trigger")

    assert schema_ranked[0]["related_node_id"] == object_type.id
    assert schema_ranked[0]["coverage_confidence"] == "verified"
    assert schedule_ranked[0]["related_node_id"] == schedule.id
    assert schedule_ranked[0]["coverage_confidence"] == "partial"


@pytest.mark.parametrize(
    ("edge_coverage", "expected_confidence"),
    [
        ("unresolved", "partial"),
        ("inconclusive", "inconclusive"),
        ("unsupported", "unsupported"),
    ],
)
def test_ranked_paths_render_inconclusive_distinctly_from_partial(
    edge_coverage, expected_confidence
):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(analysis, "dataset", "root", {"rid": "root"})
    related = service._add_node(
        analysis, "schedule", "consumer", {"schedule_rid": "consumer"}
    )
    service._add_edge(
        analysis,
        root.id,
        related.id,
        "schedule-consumes-resource",
        [],
        coverage=edge_coverage,
    )

    ranked = service._rank_paths(
        analysis, service._derive_paths(analysis, root.id, "both"), None
    )

    assert ranked[0]["coverage_confidence"] == expected_confidence


def test_semantic_impact_dedupe_unions_evidence_but_separates_direction():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    related = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}
    )
    ranked = [
        {
            "id": "path-a",
            "related_node_id": related.id,
            "direction": "downstream",
            "relation_kind": "query-returns-object",
            "steps": [{"edge_id": "edge-a"}],
            "evidence_ids": ["evidence-a"],
            "coverage_confidence": "verified",
            "hop_count": 1,
            "readable_path": "Query -> Employee",
            "first_evidence_locator": "output",
        },
        {
            "id": "path-b",
            "related_node_id": related.id,
            "direction": "downstream",
            "relation_kind": "query-returns-object",
            "steps": [{"edge_id": "edge-b"}],
            "evidence_ids": ["evidence-b", "evidence-a"],
            "coverage_confidence": "partial",
            "hop_count": 2,
            "readable_path": "Query -> Function -> Employee",
            "first_evidence_locator": "returnType",
        },
        {
            "id": "path-c",
            "related_node_id": related.id,
            "direction": "upstream",
            "relation_kind": "query-returns-object",
            "steps": [{"edge_id": "edge-c"}],
            "evidence_ids": ["evidence-c"],
            "coverage_confidence": "verified",
            "hop_count": 1,
            "readable_path": "Employee <- Query",
            "first_evidence_locator": "output",
        },
    ]

    impacts = service._dedupe_ranked_impacts(analysis, ranked, None)

    assert len(impacts) == 2
    downstream = next(
        impact for impact in impacts if impact["direction_class"] == "downstream"
    )
    assert downstream["representative_path_id"] == "path-a"
    assert downstream["member_path_ids"] == ["path-a", "path-b"]
    assert downstream["representative_evidence_ids"] == ["evidence-a"]
    assert downstream["all_member_evidence_ids"] == ["evidence-a", "evidence-b"]
    assert {impact["direction_class"] for impact in impacts} == {
        "downstream",
        "upstream",
    }


def test_impact_category_tables_are_closed_complete_and_override_specific():
    assert set(IMPACT_CATEGORY_BASE) == set(RELATION_KINDS)
    assert set(IMPACT_CATEGORY_BASE.values()) <= set(IMPACT_CATEGORIES)
    assert all(
        change_type in CHANGE_TYPES
        and relation_kind in RELATION_KINDS
        and direction in {"upstream", "downstream", "adjacent"}
        and category in IMPACT_CATEGORIES
        for (change_type, relation_kind, direction), category in (
            IMPACT_CATEGORY_CHANGE_OVERRIDES.items()
        )
    )
    assert (
        DependencyGraphService._resolve_impact_category(
            "declared-link", "adjacent", "rename"
        )
        == "contract-break"
    )
    assert (
        DependencyGraphService._resolve_impact_category(
            "declared-link", "adjacent", None
        )
        == "schema-break"
    )
    assert (
        DependencyGraphService._resolve_impact_category(
            "query-returns-object", "upstream", "rename"
        )
        == "semantic-break"
    )
    assert DependencyGraphService._resolve_change_type("rename the field", None) == (
        "rename",
        "inferred",
    )
    assert DependencyGraphService._resolve_change_type(
        "rename the field", "type-change"
    ) == ("type-change", "explicit")


def _impact(
    impact_id,
    node_id,
    *,
    category,
    direction,
    confidence,
    hop_count,
):
    return {
        "impact_id": impact_id,
        "related_node_id": node_id,
        "related_display_name": impact_id,
        "impact_category": category,
        "direction_class": direction,
        "coverage_confidence": confidence,
        "hop_count": hop_count,
        "why_it_matters": f"verify {impact_id}",
    }


def test_verification_buckets_are_exact_disjoint_and_precedence_ordered():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    nodes = [
        service._add_node(analysis, "object-type", name, {"object_type": name})
        for name in ("critical", "structural", "indirect", "unknown")
    ]
    impacts = [
        _impact(
            "critical",
            nodes[0].id,
            category="runtime-break",
            direction="downstream",
            confidence="verified",
            hop_count=1,
        ),
        _impact(
            "structural",
            nodes[1].id,
            category="schema-break",
            direction="adjacent",
            confidence="unsupported",
            hop_count=1,
        ),
        _impact(
            "indirect",
            nodes[2].id,
            category="workflow-break",
            direction="downstream",
            confidence="partial",
            hop_count=2,
        ),
        _impact(
            "unknown",
            nodes[3].id,
            category="unknown",
            direction="downstream",
            confidence="unsupported",
            hop_count=2,
        ),
    ]

    result = service._classify_agent_results(analysis, impacts)
    verification = result["verification"]

    assert set(verification) == {
        "must_verify_before_merge",
        "should_verify_before_deploy",
        "unsupported_manual_surfaces",
    }
    memberships = [
        impact_id
        for items in verification.values()
        for item in items
        for impact_id in item["related_impact_ids"]
    ]
    assert sorted(memberships) == sorted(impact["impact_id"] for impact in impacts)
    assert len(memberships) == len(set(memberships))
    assert {
        item["related_impact_ids"][0]
        for item in verification["must_verify_before_merge"]
    } == {"critical", "structural"}


def test_verification_aggregates_mixed_impacts_and_gap_by_subject_precedence():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    subject = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}
    )
    impacts = [
        _impact(
            "critical",
            subject.id,
            category="runtime-break",
            direction="downstream",
            confidence="verified",
            hop_count=1,
        ),
        _impact(
            "indirect",
            subject.id,
            category="workflow-break",
            direction="downstream",
            confidence="partial",
            hop_count=2,
        ),
        _impact(
            "unsupported",
            subject.id,
            category="unknown",
            direction="downstream",
            confidence="unsupported",
            hop_count=2,
        ),
    ]
    service._add_gap(
        analysis,
        subject.id,
        "full-action-metadata",
        "unresolved",
        "metadata-unresolved",
        "Action metadata could not be resolved",
    )

    verification = service._classify_agent_results(analysis, impacts)["verification"]
    subject_entries = [
        (bucket, item)
        for bucket, items in verification.items()
        for item in items
        if item["subject_node_id"] == subject.id
    ]

    assert len(subject_entries) == 1
    bucket, item = subject_entries[0]
    assert bucket == "must_verify_before_merge"
    assert item["reason"] == "coverage-gap"
    assert item["related_impact_ids"] == [
        "critical",
        "indirect",
        "unsupported",
    ]


def test_budget_exhaustion_forces_must_verify_without_discovered_impacts():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    analysis.caches[("budget-exhausted",)] = BudgetExhausted(
        "requests", analysis.budget.snapshot()
    )

    result = service._classify_agent_results(analysis, [])

    assert result["coverage_completeness"]["budget_exhausted"] is True
    assert result["verification"]["must_verify_before_merge"][0]["reason"] == (
        "budget-truncation"
    )


def test_coverage_gap_touching_structural_impact_forces_must_verify():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}
    )
    service._add_gap(
        analysis,
        node.id,
        "full-action-metadata",
        "unresolved",
        "metadata-unresolved",
        "Action metadata could not be resolved",
    )
    impacts = [
        _impact(
            "structural",
            node.id,
            category="schema-break",
            direction="adjacent",
            confidence="verified",
            hop_count=1,
        )
    ]

    result = service._classify_agent_results(analysis, impacts)

    assert any(
        item["reason"] == "coverage-gap"
        for item in result["verification"]["must_verify_before_merge"]
    )


def test_static_unsupported_matrix_gap_routes_unsupported_not_must_and_stays_clean():
    """A structurally unsupported/manual surface (a static MATRIX_GAPS
    limitation for this target kind) is not a merge blocker: it routes to
    unsupported_manual_surfaces, must_verify_before_merge stays empty, and
    the agent status remains clean/CI-eligible even though coverage is
    incomplete."""
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "generic-resource", "widget", {"resource_rid": "widget"}, True
    )
    target = DependencyTarget(
        "generic-resource", node.identifiers, node.display_name, node.id
    )
    service._initialize_matrix(analysis, target)
    # `compass-metadata` is the one static surface MATRIX_GAPS never covers
    # for this kind; finish it the way a real collector would so this test
    # isolates the static-unsupported-gap behavior under verification.
    compass = service._coverage_record(
        analysis, "generic-resource", "compass-metadata", node.id
    )
    service._finish_coverage(compass, "covered", evidence_ids=[])
    service._remove_gaps(
        analysis, node.id, "compass-metadata", "collector-did-not-report"
    )

    classification = service._classify_agent_results(analysis, [])
    agent = service._build_agent_block(
        analysis, target, None, None, "absent", [], classification, None
    )
    verification = classification["verification"]

    assert verification["must_verify_before_merge"] == []
    assert {
        item["subject_node_id"] for item in verification["unsupported_manual_surfaces"]
    } == {node.id}
    assert classification["coverage_completeness"]["complete"] is False
    assert agent["status"] == "clean"


def test_dynamic_unsupported_gap_with_non_matrix_reason_stays_must_and_non_clean():
    """A dynamic collector failure that happens to carry coverage="unsupported"
    (e.g. a live API-not-found response) is not a static MATRIX_GAPS surface
    limitation -- its reason_code is not in STATIC_UNSUPPORTED_GAP_REASONS,
    so it must stay in must_verify_before_merge, not unsupported_manual_surfaces,
    and the agent must not report clean."""
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}, True
    )
    target = DependencyTarget(
        "object-type", node.identifiers, node.display_name, node.id
    )
    service._add_gap(
        analysis,
        node.id,
        "full-action-metadata",
        "unsupported",
        "unsupported",
        "The Foundry API reported this surface as not found",
    )

    classification = service._classify_agent_results(analysis, [])
    agent = service._build_agent_block(
        analysis, target, None, None, "absent", [], classification, None
    )
    verification = classification["verification"]

    assert verification["unsupported_manual_surfaces"] == []
    assert {
        item["subject_node_id"] for item in verification["must_verify_before_merge"]
    } == {node.id}
    assert agent["status"] == "needs-verification"


def test_supported_complete_coverage_stays_clean_and_ci_eligible():
    """A target with genuinely complete, supported coverage (no gaps at all)
    stays clean and CI-eligible -- the routing change must not regress the
    baseline no-gap case."""
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}, True
    )
    target = DependencyTarget(
        "object-type", node.identifiers, node.display_name, node.id
    )

    classification = service._classify_agent_results(analysis, [])
    agent = service._build_agent_block(
        analysis, target, None, None, "absent", [], classification, None
    )

    assert classification["verification"] == {
        "must_verify_before_merge": [],
        "should_verify_before_deploy": [],
        "unsupported_manual_surfaces": [],
    }
    assert classification["coverage_completeness"]["complete"] is True
    assert agent["status"] == "clean"


def test_scores_are_versioned_deterministic_and_budget_sensitive():
    service = DependencyGraphService(client=SimpleNamespace())
    groups = {
        "critical_paths": ["critical"],
        "structural_dependents": ["structural"],
        "indirect_operational_effects": [],
        "unknown_manual_verification": [],
    }
    first = context()
    identical = context()
    changed_budget = context(max_depth=3)

    blast_absent, release_absent = service._compute_scores(
        first, groups, None, "absent"
    )
    blast_explicit, release_explicit = service._compute_scores(
        identical, groups, "remove-delete", "explicit"
    )
    blast_changed, _ = service._compute_scores(
        changed_budget, groups, "remove-delete", "explicit"
    )

    assert blast_absent["score"] == blast_explicit["score"] == 16
    assert blast_absent["weight_table_version"] == BLAST_RADIUS_WEIGHT_TABLE_VERSION
    assert release_absent == {
        "score": None,
        "weight_table_version": RELEASE_RISK_WEIGHT_TABLE_VERSION,
        "budget_fingerprint": blast_absent["budget_fingerprint"],
        "change_type_source": "absent",
    }
    assert release_explicit["score"] == 24
    assert release_explicit["change_type_source"] == "explicit"
    assert blast_absent["budget_fingerprint"] == blast_explicit["budget_fingerprint"]
    assert blast_changed["budget_fingerprint"] != blast_absent["budget_fingerprint"]
    assert all(
        0 <= score <= 100
        for score in (blast_absent["score"], release_explicit["score"])
    )


def test_unclassified_free_text_change_still_produces_inferred_release_risk():
    service = DependencyGraphService(client=SimpleNamespace())
    groups = {
        "critical_paths": ["critical"],
        "structural_dependents": [],
        "indirect_operational_effects": [],
        "unknown_manual_verification": [],
    }

    resolved, source = service._resolve_change_type(
        "adjust employee business semantics", None
    )
    _, release_risk = service._compute_scores(context(), groups, resolved, source)

    assert (resolved, source) == (None, "inferred")
    assert release_risk["score"] == 10
    assert release_risk["change_type_source"] == "inferred"


@pytest.mark.parametrize(
    "budget_override",
    [
        {"max_requests": 201},
        {"max_pages": 101},
        {"max_items": 10_001},
        {"max_nodes": 151},
        {"max_depth": 3},
        {"time_budget_seconds": 61},
    ],
)
def test_budget_fingerprint_changes_for_every_discovery_limit(budget_override):
    baseline = DependencyGraphService._budget_fingerprint(context())

    assert (
        DependencyGraphService._budget_fingerprint(context(**budget_override))
        != baseline
    )


def test_action_and_query_contracts_project_only_from_cached_metadata():
    client = Mock()
    service = DependencyGraphService(client=client)
    analysis = context()
    action = service._add_node(
        analysis,
        "action-type",
        "Promote",
        {"ontology_rid": "ontology", "action_type": "Promote"},
    )
    query = service._add_node(
        analysis,
        "query-type",
        "FindEmployee",
        {"ontology_rid": "ontology", "query_type": "FindEmployee"},
    )
    employee_filter = service._add_node(
        analysis,
        "object-type",
        "EmployeeFilter",
        {"object_type": "EmployeeFilter"},
    )
    employee = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}
    )
    department = service._add_node(
        analysis, "object-type", "Department", {"object_type": "Department"}
    )
    consumer = service._add_node(
        analysis,
        "query-type",
        "SummarizeEmployee",
        {"ontology_rid": "ontology", "query_type": "SummarizeEmployee"},
    )
    function = service._add_node(
        analysis, "function", "validate", {"function_rid": "function"}
    )
    service._add_edge(analysis, action.id, function.id, "action-uses-function", [])
    service._add_edge(
        analysis, employee_filter.id, query.id, "query-accepts-object", []
    )
    service._add_edge(analysis, query.id, employee.id, "query-returns-object", [])
    service._add_edge(analysis, employee.id, consumer.id, "query-accepts-object", [])
    service._add_gap(
        analysis,
        employee.id,
        "query-related-function-metadata",
        "unresolved",
        "reverse-query-mapping-unavailable",
        "Reverse query consumer metadata is unavailable for Employee",
    )
    service._add_gap(
        analysis,
        query.id,
        "query-related-function-metadata",
        "unresolved",
        "query-consumer-metadata-unavailable",
        "Query consumer metadata is unavailable for FindEmployee",
    )
    parameter_type = ontology_models.OntologyObjectType.model_construct(
        object_api_name="Employee", object_type_api_name="Employee"
    )
    department_type = ontology_models.OntologyObjectType.model_construct(
        object_api_name="Department", object_type_api_name="Department"
    )
    action_metadata = SimpleNamespace(
        action_type=SimpleNamespace(
            parameters={
                "department": SimpleNamespace(
                    data_type=department_type, required=False
                ),
                "employee": SimpleNamespace(data_type=parameter_type, required=True),
            }
        ),
        full_logic_rules=[
            {"type": "modifyObject", "propertyArguments": {"name": "value"}}
        ],
    )
    query_metadata = SimpleNamespace(
        parameters={"employee": SimpleNamespace(data_type=parameter_type)},
        output=parameter_type,
    )
    branch = analysis.read_context.requested_branch
    analysis.caches[("action-metadata", "ontology", branch, "Promote")] = (
        action_metadata,
        "operation-action",
    )
    analysis.caches[("query-metadata", "ontology", branch, "FindEmployee")] = (
        query_metadata,
        "operation-query",
    )

    contracts = service._project_action_query_contracts(
        analysis, [{"related_node_id": employee.id}]
    )

    client.assert_not_called()
    assert contracts["actions"] == [
        {
            "action_type": "Promote",
            "inputs": [
                {
                    "parameter_id": "department",
                    "data_type": "object",
                    "required": False,
                },
                {"parameter_id": "employee", "data_type": "object", "required": True},
            ],
            "writes_deletes": [
                {"operation": "write", "rule_index": 0, "type": "modifyObject"}
            ],
            "affected_fields": ["name"],
            "validation_risks": ["employee"],
            "runtime_consumers": ["validate"],
        }
    ]
    assert contracts["queries"] == [
        {
            "query_type": "FindEmployee",
            "inputs": [{"parameter_id": "employee", "data_type": "object"}],
            "outputs": [
                {
                    "data_type": "object-type",
                    "name": "Employee",
                    "locator": "output",
                }
            ],
            "input_producers": ["EmployeeFilter"],
            "likely_downstream_consumers": ["SummarizeEmployee"],
            "unresolved_consumers": [
                "Query consumer metadata is unavailable for FindEmployee",
                "Reverse query consumer metadata is unavailable for Employee",
            ],
        }
    ]
    assert "Employee" not in contracts["queries"][0]["likely_downstream_consumers"]
    assert department.display_name not in contracts["actions"][0]["validation_risks"]


def test_artifact_diff_classifies_removed_edges_by_subject_local_budget_state():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(analysis, "dataset", "root", {"rid": "root"})
    shared = service._add_node(analysis, "schedule", "shared", {"rid": "shared"})
    added = service._add_node(analysis, "schedule", "added", {"rid": "added"})
    actually_removed = service._add_node(
        analysis, "schedule", "removed", {"rid": "removed"}
    )
    shared_edge = service._add_edge(
        analysis,
        root.id,
        shared.id,
        "schedule-consumes-resource",
        [],
        coverage="verified",
    )
    added_edge = service._add_edge(
        analysis,
        root.id,
        added.id,
        "schedule-produces-resource",
        [],
    )
    service._add_gap(
        analysis,
        root.id,
        "schedule-reverse-index",
        "budget-exhausted",
        "budget-exhausted",
        "Schedule discovery stopped at the local subject budget",
    )
    omitted_node = {
        "id": "node-omitted",
        "kind": "schedule",
        "identifiers": {"rid": "omitted"},
    }
    sibling_source = {
        "id": "node-sibling-source",
        "kind": "schedule",
        "identifiers": {"rid": "sibling-source"},
    }
    sibling_target = {
        "id": "node-sibling-target",
        "kind": "schedule",
        "identifiers": {"rid": "sibling-target"},
    }
    baseline = {
        "target": {
            "kind": "dataset",
            "identifiers": root.identifiers,
            "node_id": root.id,
        },
        "read_contexts": [
            {
                "ontology_rid": analysis.read_context.ontology_rid,
                "requested_branch": analysis.read_context.requested_branch,
            }
        ],
        "graph": {
            "nodes": [
                service._serialize(root),
                service._serialize(shared),
                service._serialize(actually_removed),
                omitted_node,
                sibling_source,
                sibling_target,
            ],
            "edges": [
                {
                    "id": shared_edge.id,
                    "source": root.id,
                    "target": shared.id,
                    "coverage": "partial",
                },
                {
                    "id": "edge-actual-removal",
                    "source": root.id,
                    "target": actually_removed.id,
                    "coverage": "verified",
                },
                {
                    "id": "edge-truncated-omission",
                    "source": root.id,
                    "target": omitted_node["id"],
                    "coverage": "verified",
                },
                {
                    "id": "edge-unrelated-removal",
                    "source": sibling_source["id"],
                    "target": sibling_target["id"],
                    "coverage": "verified",
                },
            ],
        },
        "budget": {"limits": analysis.budget.snapshot()["limits"]},
        "artifact": {"analysis_id": "dep-baseline"},
    }
    impacts = [{"impact_id": "new-impact", "terminal_edge_id": added_edge.id}]

    diff = service._diff_graphs(
        analysis,
        baseline,
        impacts,
        {"budget_exhausted": True},
        DependencyTarget("dataset", root.identifiers, root.display_name, root.id),
    )

    assert diff["added_edges"] == [added_edge.id]
    assert diff["changed_edges"] == [
        {
            "edge_id": shared_edge.id,
            "from_coverage": "partial",
            "to_coverage": "verified",
        }
    ]
    # An edge directly adjacent to a locally-truncated subject is always
    # ambiguous (edge-actual-removal), even when its far endpoint happens to
    # be independently reached elsewhere in the current graph -- truncation
    # could have cut that specific edge regardless.  An edge with neither
    # endpoint reachable from the truncated frontier at all
    # (edge-unrelated-removal) is unambiguous.
    assert diff["removed_edges"] == [
        {
            "edge_id": "edge-actual-removal",
            "possibly_budget_truncated": True,
        },
        {
            "edge_id": "edge-truncated-omission",
            "possibly_budget_truncated": True,
        },
        {
            "edge_id": "edge-unrelated-removal",
            "possibly_budget_truncated": False,
        },
    ]
    assert diff["newly_introduced_impacts"] == ["new-impact"]
    assert diff["compared_against"] == "dep-baseline"
    assert diff["comparable"] is True


def test_artifact_diff_convergent_path_marks_frontier_edge_but_stops_propagation():
    """A removed edge directly incident to a locally-truncated subject stays
    possibly-truncated even when its far endpoint is independently confirmed
    reached via another, unaffected path -- but propagation must not
    continue past that independently-confirmed node."""
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(analysis, "dataset", "root", {"rid": "root"})
    anchor = service._add_node(analysis, "schedule", "anchor", {"rid": "anchor"})
    convergent = service._add_node(
        analysis, "schedule", "convergent", {"rid": "convergent"}
    )
    anchor_edge = service._add_edge(
        analysis,
        anchor.id,
        convergent.id,
        "schedule-produces-resource",
        [],
        coverage="verified",
    )
    service._add_gap(
        analysis,
        root.id,
        "schedule-reverse-index",
        "budget-exhausted",
        "budget-exhausted",
        "Schedule discovery stopped at the local subject budget",
    )
    beyond_node = {
        "id": "node-beyond",
        "kind": "schedule",
        "identifiers": {"rid": "beyond"},
    }
    baseline = {
        "target": {
            "kind": "dataset",
            "identifiers": root.identifiers,
            "node_id": root.id,
        },
        "read_contexts": [
            {
                "ontology_rid": analysis.read_context.ontology_rid,
                "requested_branch": analysis.read_context.requested_branch,
            }
        ],
        "graph": {
            "nodes": [
                service._serialize(root),
                service._serialize(anchor),
                service._serialize(convergent),
                beyond_node,
            ],
            "edges": [
                {
                    "id": anchor_edge.id,
                    "source": anchor.id,
                    "target": convergent.id,
                    "coverage": "verified",
                },
                {
                    "id": "edge-frontier-to-convergent",
                    "source": root.id,
                    "target": convergent.id,
                    "coverage": "verified",
                },
                {
                    "id": "edge-beyond-convergent",
                    "source": convergent.id,
                    "target": beyond_node["id"],
                    "coverage": "verified",
                },
            ],
        },
        "budget": {"limits": analysis.budget.snapshot()["limits"]},
        "artifact": {"analysis_id": "dep-baseline"},
    }

    diff = service._diff_graphs(
        analysis,
        baseline,
        [],
        {"budget_exhausted": True},
        DependencyTarget("dataset", root.identifiers, root.display_name, root.id),
    )

    removed = {
        item["edge_id"]: item["possibly_budget_truncated"]
        for item in diff["removed_edges"]
    }
    assert removed == {
        "edge-frontier-to-convergent": True,
        "edge-beyond-convergent": False,
    }


def test_agent_block_exposes_stable_schema_status_and_null_diff():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}, True
    )
    target = DependencyTarget(
        "object-type", node.identifiers, node.display_name, node.id
    )
    classification = service._classify_agent_results(analysis, [])

    agent = service._build_agent_block(
        analysis,
        target,
        None,
        None,
        "absent",
        [],
        classification,
        None,
    )

    assert agent["schema_version"] == AGENT_SCHEMA_VERSION == "dependency-agent-v1"
    assert agent["status"] == "clean"
    assert agent["diff"] is None
    assert set(agent["verification"]) == {
        "must_verify_before_merge",
        "should_verify_before_deploy",
        "unsupported_manual_surfaces",
    }


@pytest.mark.parametrize(
    ("direction", "causal_source_is_middle"),
    [("downstream", True), ("upstream", False)],
)
def test_one_way_paths_continue_through_adjacent_prefix(
    direction, causal_source_is_middle
):
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=2)
    root = service._add_node(analysis, "project", "root", {"rid": "root"})
    middle = service._add_node(analysis, "dataset", "middle", {"rid": "middle"})
    leaf = service._add_node(analysis, "schedule", "leaf", {"rid": "leaf"})
    service._add_edge(analysis, root.id, middle.id, "container-member", [])
    source, target = (
        (middle.id, leaf.id) if causal_source_is_middle else (leaf.id, middle.id)
    )
    service._add_edge(analysis, source, target, "schedule-consumes-resource", [])

    paths = service._derive_paths(analysis, root.id, direction)

    assert [path["related_node_id"] for path in paths] == [leaf.id]
    assert paths[0]["direction"] == direction
    assert service._overall_direction_values(["adjacent", direction]) == direction
    assert service._overall_direction_values(["upstream", "downstream"]) == "adjacent"


def test_zero_impact_non_budget_gap_is_incomplete_and_needs_verification():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    node = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}, True
    )
    record = service._coverage_record(
        analysis, "object-type", "frontier-collection", node.id
    )
    service._finish_coverage(
        record, "inaccessible", reason="permission-denied", attempted=True
    )
    gap = service._add_gap(
        analysis,
        node.id,
        "frontier-collection",
        "inaccessible",
        "permission-denied",
        "The dependency surface is inaccessible",
    )

    classification = service._classify_agent_results(analysis, [])
    agent = service._build_agent_block(
        analysis,
        DependencyTarget("object-type", node.identifiers, node.display_name, node.id),
        None,
        None,
        "absent",
        [],
        classification,
        None,
    )

    assert classification["coverage_completeness"]["complete"] is False
    assert classification["coverage_completeness"]["incomplete_gap_ids"] == [gap.id]
    must = classification["verification"]["must_verify_before_merge"]
    assert must and must[0]["reason"] == "coverage-gap"
    assert must[0]["related_gap_ids"] == [gap.id]
    assert agent["status"] == "needs-verification"


def test_blast_groups_and_score_ignore_change_aware_impact_category():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    action = service._add_node(
        analysis,
        "action-type",
        "Promote",
        {"ontology_rid": "ontology", "action_type": "Promote"},
        True,
    )
    employee = service._add_node(
        analysis, "object-type", "Employee", {"object_type": "Employee"}
    )
    service._add_edge(analysis, action.id, employee.id, "action-affects-object", [])
    ranked = service._rank_paths(
        analysis, service._derive_paths(analysis, action.id, "downstream"), None
    )
    target = DependencyTarget(
        "action-type", action.identifiers, action.display_name, action.id
    )

    no_change_impacts = service._dedupe_ranked_impacts(analysis, ranked, None)
    changed_impacts = service._dedupe_ranked_impacts(
        analysis, ranked, "required-to-optional"
    )
    no_change = service._build_agent_block(
        analysis,
        target,
        None,
        None,
        "absent",
        no_change_impacts,
        service._classify_agent_results(analysis, no_change_impacts),
        None,
    )
    changed = service._build_agent_block(
        analysis,
        target,
        None,
        "required-to-optional",
        "explicit",
        changed_impacts,
        service._classify_agent_results(analysis, changed_impacts),
        None,
    )

    assert no_change["blast_radius"] == changed["blast_radius"]
    assert (
        no_change_impacts[0]["impact_category"] != changed_impacts[0]["impact_category"]
    )
    assert no_change["release_risk"]["score"] is None
    assert changed["release_risk"]["score"] is not None


def test_query_contract_projection_resolves_recursive_scc_output_without_sdk_calls():
    client = Mock()
    service = DependencyGraphService(client=client)
    analysis = context(max_depth=10)
    query = _recursive_query()
    query_node = service._add_node(
        analysis,
        "query-type",
        query.api_name,
        {"ontology_rid": "ontology", "query_type": query.api_name},
    )
    analysis.caches[("query-metadata", "ontology", "feature", query.api_name)] = (
        query,
        "operation",
    )

    contracts = service._project_action_query_contracts(analysis, [])

    client.assert_not_called()
    outputs = contracts["queries"][0]["outputs"]
    assert [(output["data_type"], output["name"]) for output in outputs] == [
        ("object-type", "X"),
        ("object-type", "Y"),
    ]
    assert all("typeReferences" in output["locator"] for output in outputs)
    cached = analysis.caches[("query-reference-closure", query_node.id)]
    assert cached["output"]["sccs"] == [["A", "B"]]


def test_diff_comparability_requires_same_target_and_all_budget_limits():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(
        analysis, "dataset", "root", {"resource_rid": "root"}, True
    )
    target = DependencyTarget("dataset", root.identifiers, root.display_name, root.id)
    baseline = {
        "target": {
            "kind": target.kind,
            "identifiers": target.identifiers,
            "node_id": target.node_id,
        },
        "read_contexts": [
            {
                "ontology_rid": analysis.read_context.ontology_rid,
                "requested_branch": analysis.read_context.requested_branch,
            }
        ],
        "graph": {"nodes": [service._serialize(root)], "edges": []},
        "budget": {"limits": analysis.budget.snapshot()["limits"]},
    }

    assert (
        service._diff_graphs(
            analysis, baseline, [], {"budget_exhausted": False}, target
        )["comparable"]
        is True
    )
    different_target = {**baseline, "target": {**baseline["target"], "kind": "table"}}
    assert (
        service._diff_graphs(
            analysis, different_target, [], {"budget_exhausted": False}, target
        )["comparable"]
        is False
    )
    different_budget = {
        **baseline,
        "budget": {"limits": {**baseline["budget"]["limits"], "depth": 99}},
    }
    assert (
        service._diff_graphs(
            analysis, different_budget, [], {"budget_exhausted": False}, target
        )["comparable"]
        is False
    )


def test_removed_edge_budget_uncertainty_propagates_beyond_frontier():
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context()
    root = service._add_node(
        analysis, "dataset", "root", {"resource_rid": "root"}, True
    )
    frontier = service._add_node(
        analysis, "schedule", "frontier", {"schedule_rid": "frontier"}
    )
    shared = service._add_edge(
        analysis, root.id, frontier.id, "schedule-consumes-resource", []
    )
    service._add_gap(
        analysis,
        frontier.id,
        "graph-discovery",
        "budget-exhausted",
        "budget-exhausted",
        "Discovery stopped at frontier",
    )
    analysis.caches[("requested-direction",)] = "downstream"
    omitted_one = {
        "id": "node-omitted-one",
        "kind": "schedule",
        "identifiers": {"schedule_rid": "omitted-one"},
    }
    omitted_two = {
        "id": "node-omitted-two",
        "kind": "schedule",
        "identifiers": {"schedule_rid": "omitted-two"},
    }
    target = DependencyTarget("dataset", root.identifiers, root.display_name, root.id)
    baseline = {
        "target": {
            "kind": target.kind,
            "identifiers": target.identifiers,
            "node_id": target.node_id,
        },
        "read_contexts": [
            {
                "ontology_rid": analysis.read_context.ontology_rid,
                "requested_branch": analysis.read_context.requested_branch,
            }
        ],
        "graph": {
            "nodes": [
                service._serialize(root),
                service._serialize(frontier),
                omitted_one,
                omitted_two,
            ],
            "edges": [
                service._serialize(shared),
                {
                    "id": "edge-frontier-one",
                    "source": frontier.id,
                    "target": omitted_one["id"],
                    "traversal_class": "dependency-flow",
                    "coverage": "verified",
                },
                {
                    "id": "edge-one-two",
                    "source": omitted_one["id"],
                    "target": omitted_two["id"],
                    "traversal_class": "dependency-flow",
                    "coverage": "verified",
                },
            ],
        },
        "budget": {"limits": analysis.budget.snapshot()["limits"]},
    }

    truncated = service._diff_graphs(
        analysis, baseline, [], {"budget_exhausted": True}, target
    )
    complete = service._diff_graphs(
        analysis, baseline, [], {"budget_exhausted": False}, target
    )

    assert truncated["removed_edges"] == [
        {"edge_id": "edge-frontier-one", "possibly_budget_truncated": True},
        {"edge_id": "edge-one-two", "possibly_budget_truncated": True},
    ]
    assert all(
        item["possibly_budget_truncated"] is False for item in complete["removed_edges"]
    )


def test_global_budget_exhaustion_terminalizes_every_queued_branch_not_just_current():
    """A global (non-depth) BudgetExhausted must terminalize every branch
    still sitting in the BFS queue, not only the branch being processed when
    it fired -- otherwise a sibling branch that was never dequeued carries no
    coverage/gap record at all, and `_diff_graphs`'s budget-truncation
    propagation has no seed to expand from beneath it."""
    service = DependencyGraphService(client=SimpleNamespace())
    analysis = context(max_depth=3)
    root = service._add_node(
        analysis, "generic-resource", "root", {"resource_rid": "root"}, True
    )
    branch_one = service._add_node(
        analysis, "generic-resource", "branch-one", {"resource_rid": "branch-one"}
    )
    branch_two = service._add_node(
        analysis, "generic-resource", "branch-two", {"resource_rid": "branch-two"}
    )
    service._add_edge(analysis, root.id, branch_one.id, "container-member", [])
    service._add_edge(analysis, root.id, branch_two.id, "container-member", [])

    processed: list[str] = []

    def collect(target, active_context):
        if target.node_id == root.id:
            return
        processed.append(target.node_id)
        if len(processed) == 1:
            raise BudgetExhausted("requests", active_context.budget.snapshot())
        raise AssertionError(
            "the second queued branch must never be dequeued after a global "
            "budget exhaustion stops the BFS"
        )

    service._collect_target = collect
    service._discover_bfs(
        DependencyTarget("generic-resource", root.identifiers, "root", root.id),
        analysis,
        "both",
    )

    assert len(processed) == 1
    exhausted_id = processed[0]
    unvisited_id = branch_two.id if exhausted_id == branch_one.id else branch_one.id

    def is_budget_exhausted(node_id: str) -> bool:
        return any(
            gap.target == node_id and gap.coverage == "budget-exhausted"
            for gap in analysis.gaps.values()
        ) or any(
            record.subject_node_id == node_id and record.status == "budget-exhausted"
            for record in analysis.coverage_records.values()
        )

    assert is_budget_exhausted(exhausted_id)
    assert is_budget_exhausted(unvisited_id), (
        "the never-dequeued sibling branch must still be terminalized as "
        "budget-exhausted"
    )

    # The queue-wide terminalization must also seed the diff's budget-
    # truncation propagation for edges two hops beneath the unvisited branch.
    omitted_one = {
        "id": "node-omitted-one",
        "kind": "generic-resource",
        "identifiers": {"resource_rid": "omitted-one"},
    }
    omitted_two = {
        "id": "node-omitted-two",
        "kind": "generic-resource",
        "identifiers": {"resource_rid": "omitted-two"},
    }
    target = DependencyTarget("generic-resource", root.identifiers, "root", root.id)
    baseline = {
        "target": {
            "kind": target.kind,
            "identifiers": target.identifiers,
            "node_id": target.node_id,
        },
        "read_contexts": [
            {
                "ontology_rid": analysis.read_context.ontology_rid,
                "requested_branch": analysis.read_context.requested_branch,
            }
        ],
        "graph": {
            "nodes": [service._serialize(node) for node in analysis.nodes.values()]
            + [omitted_one, omitted_two],
            "edges": [service._serialize(edge) for edge in analysis.edges.values()]
            + [
                {
                    "id": "edge-unvisited-one",
                    "source": unvisited_id,
                    "target": omitted_one["id"],
                    "traversal_class": "adjacent-structural",
                    "coverage": "verified",
                },
                {
                    "id": "edge-one-two",
                    "source": omitted_one["id"],
                    "target": omitted_two["id"],
                    "traversal_class": "adjacent-structural",
                    "coverage": "verified",
                },
            ],
        },
        "budget": {"limits": analysis.budget.snapshot()["limits"]},
    }

    diff = service._diff_graphs(
        analysis, baseline, [], {"budget_exhausted": True}, target
    )

    removed = {
        item["edge_id"]: item["possibly_budget_truncated"]
        for item in diff["removed_edges"]
    }
    assert removed["edge-unvisited-one"] is True
    assert removed["edge-one-two"] is True
