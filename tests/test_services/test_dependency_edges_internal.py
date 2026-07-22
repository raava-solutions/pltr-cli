import base64
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote

import pytest
import requests

from pltr.services.dependency import (
    TRANSFORM_DATASET_LINEAGE_SURFACE,
    DependencyGraphService,
    DependencyTarget,
    DiscoveryBudget,
)
from pltr.services.dependency_internal_specs import (
    ACP_OPERATION_SPECS,
    ACP_05_DEPENDENTS_PAGE_BOUNDARY,
    CONJURE_POST_OPERATION_SPECS,
    GET_OBJECT_TYPE_DEPENDENTS_QUERY,
    GRAPHQL_OPERATION_SPECS,
    TRANSFORM_LINEAGE_GET_OPERATION_SPECS,
)
from pltr.services.dependency_providers import ConjureRestProvider, ProviderResult
from pltr.services.foundry_internal_client import (
    FoundryInternalClient,
    GraphQLOperation,
    GraphQLResult,
    TokenExpiredError,
)


def _sdk_client(
    *property_names: str,
    link_types=(),
    object_type_rid="ri.ontology.main.object-type.program",
) -> SimpleNamespace:
    metadata = SimpleNamespace(
        object_type=SimpleNamespace(
            properties={name: SimpleNamespace() for name in property_names},
            rid=object_type_rid,
        ),
        link_types=list(link_types),
        implements_interfaces=[],
        implements_interfaces2={},
        shared_property_type_mapping={},
    )
    empty_page = SimpleNamespace(data=[], next_page_token=None)
    return SimpleNamespace(
        ontologies=SimpleNamespace(
            Ontology=SimpleNamespace(
                ObjectType=SimpleNamespace(
                    get_full_metadata=Mock(return_value=metadata)
                ),
                QueryType=SimpleNamespace(list=Mock(return_value=empty_page)),
            ),
            ActionTypeFullMetadata=SimpleNamespace(list=Mock(return_value=empty_page)),
        )
    )


def _property_mapping_response():
    return (
        200,
        {
            "datasources": [
                {
                    "definition": {
                        "type": "dataset",
                        "datasetRid": "ri.foundry.main.dataset.programs",
                        "propertyMapping": {
                            "programId": {"type": "column", "column": "program_id"}
                        },
                    }
                }
            ]
        },
        "{}",
    )


def _dependent(rid, type_name, name=None):
    return {
        "rid": rid,
        "name": name or rid,
        "description": f"{type_name} consumer",
        "path": f"/Consumers/{name or rid}",
        "type": {"name": type_name},
        "parent": {
            "rid": "ri.compass.main.folder.parent",
            "name": "Consumers",
            "path": "/Consumers",
        },
        "projectRid": "ri.compass.main.folder.project",
    }


_UNSET = object()


def _analyze_object(
    values,
    *,
    next_page_token=None,
    graphql_object=True,
    graphql_response=None,
    graphql_error=None,
    object_type_rid="ri.ontology.main.object-type.program",
    returned_rid="ri.ontology.main.object-type.program",
    dependents_override=_UNSET,
    monocle_response=None,
    monocle_error=None,
    monocle_http_response=None,
    link_types=(),
    internal_budget=None,
    graph_budget=None,
    requested_branch="feature",
):
    internal_client = SimpleNamespace(graphql=Mock(), conjure=Mock())
    dependents = (
        {
            "values": values,
            "nextPageToken": next_page_token,
        }
        if dependents_override is _UNSET
        else dependents_override
    )
    internal_client.graphql.return_value = graphql_response or GraphQLResult(
        data={
            "objectTypeV2": (
                {"rid": returned_rid, "dependents": dependents}
                if graphql_object
                else None
            )
        }
    )
    if graphql_error is not None:
        internal_client.graphql.side_effect = graphql_error

    def conjure(verb, path, **kwargs):
        if "includeDatasources" in path:
            return _property_mapping_response()
        assert verb == "POST"
        assert path == "/monocle/api/links/graphV3"
        if monocle_error is not None:
            raise monocle_error
        if monocle_http_response is not None:
            return monocle_http_response
        return 200, monocle_response or {"nodes": []}, "{}"

    internal_client.conjure.side_effect = conjure
    service = DependencyGraphService(
        client=_sdk_client(
            "programId", link_types=link_types, object_type_rid=object_type_rid
        ),
        conjure_provider=ConjureRestProvider(internal_client),
    )
    context = service.create_context(
        host="https://example.test",
        ontology_rid="ri.ontology",
        requested_branch=requested_branch,
        budget=graph_budget or DiscoveryBudget(max_depth=1),
        internal_budget=internal_budget,
    )
    target = service.resolve_object_type(context, "ri.ontology", "Program")
    service._initialize_matrix(context, target)
    service._collect_target(target, context)
    service._complete_coverage(context)
    result = {
        "target": service._serialize(target),
        "operation_provenance": [
            service._serialize(item) for item in context.operation_provenance.values()
        ],
        "evidence": [service._serialize(item) for item in context.evidence.values()],
        "graph": {
            "nodes": [service._serialize(item) for item in context.nodes.values()],
            "edges": [service._serialize(item) for item in context.edges.values()],
        },
        "coverage": [
            service._serialize(item) for item in context.coverage_records.values()
        ],
        "gaps": [
            dict(service._serialize(item), id=item.id) for item in context.gaps.values()
        ],
        "budget": context.budget.snapshot(),
        "internal_budget": context.internal_budget.snapshot(),
    }
    return result, internal_client


def _analyze_property(internal_response):
    internal_client = Mock()
    if isinstance(internal_response, BaseException):
        internal_client.conjure.side_effect = internal_response
    else:
        internal_client.conjure.return_value = internal_response
    service = DependencyGraphService(
        client=_sdk_client("programId"),
        conjure_provider=ConjureRestProvider(internal_client),
    )
    context = service.create_context(
        host="https://example.test",
        ontology_rid="ri.ontology",
        budget=DiscoveryBudget(max_depth=1),
    )
    target = service.resolve_property(context, "ri.ontology", "Program", "programId")
    return service.analyze(target, context), internal_client


def test_property_mapping_emits_exact_non_convention_column_edge():
    result, internal_client = _analyze_property(
        (
            200,
            {
                "datasources": [
                    {
                        "rid": "ri.ontology.main.datasource.source",
                        "definition": {
                            "type": "dataset",
                            "datasetRid": "ri.foundry.main.dataset.programs",
                            "propertyMapping": {
                                "programId": {
                                    "type": "column",
                                    "column": "program_id",
                                }
                            },
                        },
                    }
                ]
            },
            "{}",
        )
    )

    column_id = "ri.foundry.main.dataset.programs#program_id"
    edges = [
        edge
        for edge in result["graph"]["edges"]
        if edge["relation_kind"] == "column-backs-property"
    ]
    assert len(edges) == 1
    assert edges[0]["source"] == column_id
    assert edges[0]["target"] == result["target"]["node_id"]
    assert any(
        node["id"] == column_id and node["kind"] == "dataset-column"
        for node in result["graph"]["nodes"]
    )
    evidence = {item["id"]: item for item in result["evidence"]}[
        edges[0]["evidence_ids"][0]
    ]
    assert evidence["locator"] == (
        "datasources[0].definition.propertyMapping.programId"
    )
    operation = {item["id"]: item for item in result["operation_provenance"]}[
        evidence["operation_provenance_id"]
    ]
    assert operation["transport"] == "conjure-rest"
    assert operation["acp_id"] == "ACP-04"
    internal_client.conjure.assert_called_once()
    assert internal_client.conjure.call_args.args[:2] == (
        "GET",
        "/api/v2/ontologies/ri.ontology/objectTypes/Program"
        "?includeDatasources=true&preview=true",
    )


def test_empty_datasources_is_inconclusive_not_covered_empty():
    result, _ = _analyze_property((200, {"datasources": []}, "{}"))

    mapping_coverage = [
        item
        for item in result["coverage"]
        if item["surface"] == "property-column-mapping"
        and item["subject_node_id"] == result["target"]["node_id"]
    ]
    assert [item["status"] for item in mapping_coverage] == ["inconclusive"]
    assert all(item["status"] != "covered-empty" for item in mapping_coverage)
    assert any(
        gap["surface"] == "property-column-mapping"
        and gap["coverage"] == "inconclusive"
        for gap in result["gaps"]
    )


def test_object_type_target_maps_only_sdk_known_properties():
    internal_client = Mock()
    internal_client.conjure.return_value = (
        200,
        {
            "datasources": [
                {
                    "definition": {
                        "type": "dataset",
                        "datasetRid": "ri.foundry.main.dataset.programs",
                        "propertyMapping": {
                            "programId": {
                                "type": "column",
                                "column": "program_id",
                            },
                            "internalOnly": {
                                "type": "column",
                                "column": "internal_only",
                            },
                        },
                    }
                }
            ]
        },
        "{}",
    )
    service = DependencyGraphService(
        client=_sdk_client("programId"),
        conjure_provider=ConjureRestProvider(internal_client),
    )
    context = service.create_context(
        host="https://example.test",
        ontology_rid="ri.ontology",
        budget=DiscoveryBudget(max_depth=1),
    )
    target = service.resolve_object_type(context, "ri.ontology", "Program")

    result = service.analyze(target, context)

    property_nodes = [
        node for node in result["graph"]["nodes"] if node["kind"] == "property"
    ]
    assert [node["identifiers"]["property"] for node in property_nodes] == ["programId"]
    assert any(
        edge["relation_kind"] == "column-backs-property"
        and edge["target"] == property_nodes[0]["id"]
        for edge in result["graph"]["edges"]
    )
    internal_client.conjure.assert_called_once()


def test_route_not_mounted_is_inconclusive_and_keeps_sdk_structure():
    result, _ = _analyze_property(
        (
            404,
            {"errorName": "Route:RouteNotMounted"},
            "route not mounted",
        )
    )

    assert any(
        edge["relation_kind"] == "container-member"
        and edge["target"] == result["target"]["node_id"]
        for edge in result["graph"]["edges"]
    )
    assert any(
        gap["reason_code"] == "route-not-mounted" and gap["coverage"] == "inconclusive"
        for gap in result["gaps"]
    )


def test_missing_property_mapping_is_shape_drift_and_keeps_sdk_structure():
    result, _ = _analyze_property(
        (
            200,
            {
                "datasources": [
                    {
                        "definition": {
                            "type": "dataset",
                            "datasetRid": "ri.foundry.main.dataset.programs",
                        }
                    }
                ]
            },
            "{}",
        )
    )

    assert any(
        edge["relation_kind"] == "container-member"
        and edge["target"] == result["target"]["node_id"]
        for edge in result["graph"]["edges"]
    )
    assert not any(
        edge["relation_kind"] == "column-backs-property"
        for edge in result["graph"]["edges"]
    )
    assert any(
        gap["reason_code"] == "response-shape-drift"
        and gap["coverage"] == "inconclusive"
        for gap in result["gaps"]
    )


def test_shape_drift_keeps_valid_mappings_from_the_same_response():
    result, _ = _analyze_property(
        (
            200,
            {
                "datasources": [
                    {
                        "definition": {
                            "type": "dataset",
                            "datasetRid": "ri.foundry.main.dataset.programs",
                            "propertyMapping": {
                                "programId": {
                                    "type": "column",
                                    "column": "program_id",
                                }
                            },
                        }
                    },
                    {
                        "definition": {
                            "type": "dataset",
                            "datasetRid": "ri.foundry.main.dataset.drifted",
                        }
                    },
                ]
            },
            "{}",
        )
    )

    assert any(
        edge["source"] == "ri.foundry.main.dataset.programs#program_id"
        and edge["target"] == result["target"]["node_id"]
        and edge["relation_kind"] == "column-backs-property"
        for edge in result["graph"]["edges"]
    )
    assert any(
        gap["reason_code"] == "response-shape-drift"
        and gap["coverage"] == "inconclusive"
        for gap in result["gaps"]
    )
    assert any(
        item["surface"] == "property-column-mapping"
        and item["status"] == "inconclusive"
        for item in result["coverage"]
    )


def test_token_expiry_is_a_distinct_gap_and_keeps_sdk_structure():
    result, _ = _analyze_property(TokenExpiredError("expired"))

    assert any(
        edge["relation_kind"] == "container-member"
        and edge["target"] == result["target"]["node_id"]
        for edge in result["graph"]["edges"]
    )
    assert any(
        gap["reason_code"] == "token-expired" and gap["coverage"] == "token-expired"
        for gap in result["gaps"]
    )


def test_mocked_401_is_a_distinct_gap_and_keeps_sdk_structure():
    result, _ = _analyze_property(
        (401, {"errorName": "Default:Unauthorized"}, "expired")
    )

    assert any(
        edge["relation_kind"] == "container-member"
        and edge["target"] == result["target"]["node_id"]
        for edge in result["graph"]["edges"]
    )
    assert any(
        gap["reason_code"] == "token-expired" and gap["coverage"] == "token-expired"
        for gap in result["gaps"]
    )


def test_object_dependents_emit_typed_consumers_and_merge_declared_link_evidence():
    link_types = [
        SimpleNamespace(
            object_type_api_name=f"Linked{i}",
            link_type_rid=f"ri.ontology.main.relation.link-{i}",
        )
        for i in range(6)
    ]
    modules = [
        _dependent(f"ri.workshop.main.module.module-{i}", "Module", f"Module {i}")
        for i in range(5)
    ]
    links = [_dependent(link.link_type_rid, "Link type") for link in link_types]
    app_rid = "ri.third-party-applications.main.application.consumer"
    app = _dependent(app_rid, "Application", "Consumer App")
    monocle = {
        "nodes": [
            {
                "resourceIdentifier": "ri.ontology.main.object-type.program",
                "links": [
                    {
                        "type": "objectProvenanceLink",
                        "objectProvenanceLink": {
                            "resourceIdentifier": app_rid,
                            "linkDirection": "OUTGOING",
                        },
                    },
                    {
                        "type": "ontologyLinkV2",
                        "ontologyLinkV2": {
                            "objectTypeId": "ri.ontology.main.object-type.linked-0",
                            "linkId": link_types[0].link_type_rid,
                            "linkDirection": "UNDIRECTED",
                        },
                    },
                    {"type": "futureLink", "futureLink": {"unknown": True}},
                ],
            }
        ]
    }

    result, internal_client = _analyze_object(
        [*modules, *links, app], link_types=link_types, monocle_response=monocle
    )

    workshop_edges = [
        edge
        for edge in result["graph"]["edges"]
        if edge["relation_kind"] == "object-consumed-by-workshop"
    ]
    app_edges = [
        edge
        for edge in result["graph"]["edges"]
        if edge["relation_kind"] == "object-consumed-by-app"
    ]
    declared_links = [
        edge
        for edge in result["graph"]["edges"]
        if edge["relation_kind"] == "declared-link"
    ]
    assert len(workshop_edges) == 5
    assert len(app_edges) == 1
    assert len(declared_links) == 6
    assert sorted(len(edge["evidence_ids"]) for edge in declared_links) == [
        2,
        2,
        2,
        2,
        2,
        3,
    ]
    assert len(app_edges[0]["evidence_ids"]) == 2
    consumer_nodes = {
        node["kind"]: node
        for node in result["graph"]["nodes"]
        if node["kind"] in {"application", "workshop-module"}
    }
    assert consumer_nodes["application"]["display_name"] == "Consumer App"
    assert consumer_nodes["application"]["identifiers"]["path"] == (
        "/Consumers/Consumer App"
    )
    assert any(
        item["surface"] == "object-type-consumers" and item["status"] == "covered"
        for item in result["coverage"]
    )
    assert internal_client.graphql.call_args.args == (
        "GetObjectTypeDependents",
        GET_OBJECT_TYPE_DEPENDENTS_QUERY,
        {"rid": "ri.ontology.main.object-type.program"},
    )
    assert "_id" not in internal_client.graphql.call_args.args[1]
    operations = {
        item["acp_id"]: item
        for item in result["operation_provenance"]
        if item["acp_id"]
    }
    assert operations["ACP-05"]["transport"] == "graphql-sse"
    assert operations["ACP-05"]["contract_pins"] == {
        "mcp": "0.397.0",
        "verified_on": "2026-07-21",
    }
    assert operations["ACP-06"]["path"] == "/monocle/api/links/graphV3"


def test_phase_b_post_specs_do_not_widen_the_get_only_acp_registry():
    assert set(GRAPHQL_OPERATION_SPECS) == {"ACP-05"}
    assert set(CONJURE_POST_OPERATION_SPECS) == {"ACP-02", "ACP-06"}
    assert GRAPHQL_OPERATION_SPECS["ACP-05"].transport == "graphql-sse"
    assert CONJURE_POST_OPERATION_SPECS["ACP-02"].verb == "POST"
    assert CONJURE_POST_OPERATION_SPECS["ACP-06"].verb == "POST"


def _lineage_target(service, analysis, dataset_rid="ri.foundry.main.dataset.output"):
    node = service._add_node(
        analysis,
        "dataset",
        dataset_rid,
        {"resource_rid": dataset_rid},
        True,
    )
    return DependencyTarget("dataset", node.identifiers, node.display_name, node.id)


def _lineage_result(service, analysis):
    service._complete_coverage(analysis)
    return {
        "nodes": [service._serialize(item) for item in analysis.nodes.values()],
        "edges": [service._serialize(item) for item in analysis.edges.values()],
        "evidence": [service._serialize(item) for item in analysis.evidence.values()],
        "coverage": [
            service._serialize(item) for item in analysis.coverage_records.values()
        ],
        "gaps": [service._serialize(item) for item in analysis.gaps.values()],
    }


def _invoke_acp_01_with_conjure(conjure):
    internal_client = SimpleNamespace(conjure=conjure)
    service = DependencyGraphService(
        client=SimpleNamespace(),
        conjure_provider=ConjureRestProvider(internal_client),
    )
    analysis = service.create_context(host="https://example.test")
    spec = TRANSFORM_LINEAGE_GET_OPERATION_SPECS["ACP-01"]
    path = spec.path.format(dataset_rid="ri.foundry.main.dataset.output")
    return service, analysis, spec, path


def test_transform_lineage_conjure_expected_failure_records_gap_and_provenance():
    error = requests.Timeout("slow build2")
    conjure = Mock(side_effect=error)
    service, analysis, spec, path = _invoke_acp_01_with_conjure(conjure)

    result = service._invoke_transform_lineage_get(
        analysis,
        spec,
        path,
        target="ri.foundry.main.dataset.output",
    )

    assert result.coverage_status == "partial"
    assert result.coverage_status != "covered"
    assert result.error_class == "timeout"
    assert result.retryable is True
    assert result.raw == "slow build2"
    gap = next(iter(analysis.gaps.values()))
    assert (
        gap.surface,
        gap.target,
        gap.coverage,
        gap.reason_code,
        gap.retryable,
        gap.operation,
        gap.locator,
    ) == (
        TRANSFORM_DATASET_LINEAGE_SURFACE,
        "ri.foundry.main.dataset.output",
        "partial",
        "timeout",
        True,
        "ACP-01",
        path,
    )
    provenance = analysis.operation_provenance[result.operation_provenance_id]
    assert (
        provenance.transport,
        provenance.acp_id,
        provenance.http_verb,
        provenance.path,
    ) == ("conjure-rest", "ACP-01", "GET", path)


def test_transform_lineage_conjure_unexpected_failure_propagates():
    conjure = Mock(side_effect=ValueError("broken transform lineage collector"))
    service, analysis, spec, path = _invoke_acp_01_with_conjure(conjure)

    with pytest.raises(ValueError, match="broken transform lineage collector"):
        service._invoke_transform_lineage_get(
            analysis,
            spec,
            path,
            target="ri.foundry.main.dataset.output",
        )

    assert analysis.gaps == {}
    provenance = next(iter(analysis.operation_provenance.values()))
    assert (provenance.acp_id, provenance.http_verb, provenance.path) == (
        "ACP-01",
        "GET",
        path,
    )


@pytest.mark.parametrize(
    ("status", "payload", "expected_coverage", "expected_error", "retryable"),
    [
        (
            400,
            {"errorName": "Default:InvalidArgument"},
            "inconclusive",
            "missing-required-field",
            True,
        ),
        (403, {}, "inaccessible", "inaccessible", False),
        (500, {}, "inconclusive", "internal-http-error", False),
    ],
)
def test_transform_lineage_conjure_non_2xx_uses_classifier_and_records_gap(
    status, payload, expected_coverage, expected_error, retryable
):
    conjure = Mock(return_value=(status, payload, f"raw-{status}"))
    service, analysis, spec, path = _invoke_acp_01_with_conjure(conjure)

    result = service._invoke_transform_lineage_get(
        analysis,
        spec,
        path,
        target="ri.foundry.main.dataset.output",
    )

    assert result.coverage_status == expected_coverage
    assert result.coverage_status != "covered"
    assert result.error_class == expected_error
    assert result.retryable is retryable
    gap = next(iter(analysis.gaps.values()))
    assert (
        gap.surface,
        gap.target,
        gap.coverage,
        gap.reason_code,
        gap.retryable,
        gap.operation,
        gap.locator,
    ) == (
        TRANSFORM_DATASET_LINEAGE_SURFACE,
        "ri.foundry.main.dataset.output",
        expected_coverage,
        expected_error,
        retryable,
        "ACP-01",
        path,
    )
    assert result.operation_provenance_id in analysis.operation_provenance


@pytest.mark.parametrize(
    ("semantics", "expected_error"),
    [
        ("empty", None),
        ("truncated", None),
        ("shape-drift", "response-shape-drift"),
        ("permission-ambiguous", None),
    ],
)
def test_transform_lineage_conjure_2xx_unsafe_semantics_are_inconclusive(
    semantics, expected_error
):
    conjure = Mock(return_value=(200, {"branch": []}, "raw-200"))
    service, analysis, spec, path = _invoke_acp_01_with_conjure(conjure)

    with patch(
        "pltr.services.dependency_providers.ResultSemantics",
        return_value=semantics,
    ):
        result = service._invoke_transform_lineage_get(
            analysis,
            spec,
            path,
            target="ri.foundry.main.dataset.output",
        )

    assert result.result_semantics == semantics
    assert result.coverage_status == "inconclusive"
    assert result.coverage_status != "covered"
    assert result.error_class == expected_error
    expected_reason = expected_error or f"{semantics}-internal-response"
    gap = next(iter(analysis.gaps.values()))
    assert (
        gap.surface,
        gap.target,
        gap.coverage,
        gap.reason_code,
        gap.retryable,
        gap.operation,
        gap.locator,
    ) == (
        TRANSFORM_DATASET_LINEAGE_SURFACE,
        "ri.foundry.main.dataset.output",
        "inconclusive",
        expected_reason,
        False,
        "ACP-01",
        path,
    )
    assert result.operation_provenance_id in analysis.operation_provenance


def test_acp_01_emits_only_artifact_repo_and_foundry_dataset_lineage():
    dataset_rid = "ri.foundry.main.dataset.output"
    input_rid = "ri.foundry.main.dataset.input"
    repo_rid = "ri.stemma.main.repository.transforms"
    source = """from transforms.api import Input, Output, transform

@transform(
    output=Output("/Datasets/output"),
    source=Input("/Datasets/input"),
)
def compute(output, source):
    pass
"""
    internal_client = SimpleNamespace(conjure=Mock())

    def conjure(verb, path, **kwargs):
        assert verb == "GET"
        if path == f"/build2/api/jobspecs/datasets/{dataset_rid}":
            return (
                200,
                {
                    "feature": {
                        "jobSpecs": [
                            {
                                "jobSpecRid": "ri.foundry.main.jobspec.transform",
                                "sourcePath": "transforms/main.py",
                                "inputSpecs": [
                                    {
                                        "inputType": "artifacts",
                                        "datasetLocator": {"datasetRid": repo_rid},
                                    },
                                    {
                                        "type": "foundry",
                                        "datasetLocator": {"datasetRid": input_rid},
                                    },
                                    {
                                        "type": "build-plumbing",
                                        "datasetLocator": {
                                            "datasetRid": "ri.false.input"
                                        },
                                    },
                                    {
                                        "inputType": "foundry",
                                        "datasetLocator": {
                                            "datasetRid": "ri.false.input-type-only"
                                        },
                                    },
                                ],
                                "outputSpecs": [
                                    {
                                        "type": "foundry",
                                        "datasetLocator": {"datasetRid": dataset_rid},
                                    },
                                    {
                                        "type": "build-plumbing",
                                        "datasetLocator": {
                                            "datasetRid": "ri.false.output"
                                        },
                                    },
                                    {
                                        "outputType": "foundry",
                                        "datasetLocator": {
                                            "datasetRid": "ri.false.output-type-only"
                                        },
                                    },
                                ],
                            }
                        ]
                    }
                },
                "{}",
            )
        if path.endswith("/paths/contents/transforms%2Fmain.py"):
            return (
                200,
                {"fileContents": base64.b64encode(source.encode()).decode()},
                "{}",
            )
        if path.endswith("/paths/blame/transforms%2Fmain.py"):
            return 200, {"blameRows": [{"lineNumber": 4}]}, "{}"
        if path == "/compass/api/resources?path=%2FDatasets%2Foutput":
            return 200, {"rid": dataset_rid}, "{}"
        raise AssertionError(path)

    internal_client.conjure.side_effect = conjure
    service = DependencyGraphService(
        client=SimpleNamespace(),
        conjure_provider=ConjureRestProvider(internal_client),
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis, dataset_rid)
    service._initialize_matrix(analysis, target)

    service._collect_transform_dataset_lineage(target, analysis)
    result = _lineage_result(service, analysis)

    relations = {edge["relation_kind"] for edge in result["edges"]}
    assert {
        "code-repo-builds-dataset",
        "dataset-feeds-transform",
        "transform-builds-dataset",
    } <= relations
    assert not any("ri.false" in str(node["identifiers"]) for node in result["nodes"])
    repo_edge = next(
        edge
        for edge in result["edges"]
        if edge["relation_kind"] == "code-repo-builds-dataset"
    )
    locators = {
        evidence["locator"]
        for evidence in result["evidence"]
        if evidence["id"] in repo_edge["evidence_ids"]
    }
    assert "transforms/main.py:3-6" in locators
    assert "blameRows[0]@4" in locators
    assert any(
        item["surface"] == TRANSFORM_DATASET_LINEAGE_SURFACE
        and item["status"] == "covered"
        for item in result["coverage"]
    )


def _empty_lineage_result(positive_control_status, existence_payload):
    provider = SimpleNamespace(invoke=Mock())
    provider.invoke.side_effect = [
        ProviderResult(
            {},
            "operation-acp-01",
            "empty",
            positive_control_status,
            "inconclusive",
            "inconclusive",
        ),
        *(
            [
                ProviderResult(
                    existence_payload,
                    "operation-acp-08",
                    "ok",
                    "not-run",
                )
            ]
            if positive_control_status == "passed"
            else []
        ),
    ]
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)
    service._initialize_matrix(analysis, target)
    service._collect_transform_dataset_lineage(target, analysis)
    return _lineage_result(service, analysis), provider


def test_acp_01_empty_is_covered_empty_only_with_both_same_run_guards():
    dataset_rid = "ri.foundry.main.dataset.output"
    result, provider = _empty_lineage_result("passed", {"rid": dataset_rid})

    record = next(
        item
        for item in result["coverage"]
        if item["surface"] == TRANSFORM_DATASET_LINEAGE_SURFACE
    )
    assert record["status"] == "covered-empty"
    assert record["reason_code"] == "authoritative-empty-no-producer"
    assert record["positive_control_status"] == "passed"
    assert record["existence_confirmed"] is True
    assert provider.invoke.call_count == 2


@pytest.mark.parametrize(
    ("positive_control_status", "existence_payload"),
    [("not-run", None), ("passed", {"rid": "ri.foundry.main.dataset.other"})],
)
def test_acp_01_empty_missing_either_guard_is_inconclusive(
    positive_control_status, existence_payload
):
    result, _ = _empty_lineage_result(positive_control_status, existence_payload)

    record = next(
        item
        for item in result["coverage"]
        if item["surface"] == TRANSFORM_DATASET_LINEAGE_SURFACE
    )
    assert record["status"] == "inconclusive"
    assert record["status"] != "covered-empty"


def test_acp_01_permission_ambiguity_is_inconclusive():
    provider = SimpleNamespace(
        invoke=Mock(
            return_value=ProviderResult(
                None,
                "operation-acp-01",
                "permission-ambiguous",
                "not-run",
                "inaccessible",
                "inaccessible",
            )
        )
    )
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)

    service._collect_transform_dataset_lineage(target, analysis)

    record = next(iter(analysis.coverage_records.values()))
    assert record.status == "inconclusive"
    assert record.status != "covered-empty"


def test_acp_01_token_expiry_is_a_gap_and_dataset_rid_is_path_encoded():
    dataset_rid = "ri.foundry.main.dataset.output/../?redirect#fragment"
    provider = SimpleNamespace(invoke=Mock(side_effect=TokenExpiredError("expired")))
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis, dataset_rid)

    service._collect_transform_dataset_lineage(target, analysis)

    request_path = provider.invoke.call_args.args[3]
    assert request_path == TRANSFORM_LINEAGE_GET_OPERATION_SPECS["ACP-01"].path.format(
        dataset_rid=quote(dataset_rid, safe="")
    )
    record = next(iter(analysis.coverage_records.values()))
    assert (record.status, record.reason) == ("token-expired", "token-expired")
    assert any(
        gap.operation == "ACP-01"
        and gap.coverage == "token-expired"
        and gap.reason_code == "token-expired"
        for gap in analysis.gaps.values()
    )


def test_acp_01_unexpected_exception_propagates():
    provider = SimpleNamespace(
        invoke=Mock(side_effect=ValueError("broken ACP-01 collector"))
    )
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)

    with pytest.raises(ValueError, match="broken ACP-01 collector"):
        service._collect_transform_dataset_lineage(target, analysis)


def test_acp_01_malformed_artifacts_locator_is_inconclusive():
    dataset_rid = "ri.foundry.main.dataset.output"
    provider = SimpleNamespace(
        invoke=Mock(
            return_value=ProviderResult(
                {
                    "master": [
                        {
                            "rid": "ri.foundry.main.jobspec.transform",
                            "inputSpecs": [
                                {
                                    "inputType": "artifacts",
                                    "datasetLocator": {"datasetRid": None},
                                }
                            ],
                            "outputSpecs": [
                                {
                                    "type": "foundry",
                                    "datasetLocator": {"datasetRid": dataset_rid},
                                }
                            ],
                        }
                    ]
                },
                "operation-acp-01",
                "ok",
                "passed",
            )
        )
    )
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis, dataset_rid)

    service._collect_transform_dataset_lineage(target, analysis)

    record = next(iter(analysis.coverage_records.values()))
    assert record.status == "inconclusive"
    assert any(
        gap.operation == "ACP-01"
        and gap.coverage == "inconclusive"
        and gap.reason_code == "response-shape-drift"
        and gap.locator == "master.jobSpecs[0].inputSpecs[0].datasetLocator.datasetRid"
        for gap in analysis.gaps.values()
    )


@pytest.mark.parametrize("malformed_side", ["inputSpecs", "outputSpecs"])
def test_acp_01_malformed_foundry_locator_is_inconclusive(malformed_side):
    dataset_rid = "ri.foundry.main.dataset.output"
    job_spec = {
        "rid": "ri.foundry.main.jobspec.transform",
        "inputSpecs": [
            {
                "type": "foundry",
                "datasetLocator": {"datasetRid": "ri.foundry.main.dataset.input"},
            }
        ],
        "outputSpecs": [
            {"type": "foundry", "datasetLocator": {"datasetRid": dataset_rid}}
        ],
    }
    job_spec[malformed_side][0]["datasetLocator"] = {"datasetRid": None}
    provider = SimpleNamespace(
        invoke=Mock(
            return_value=ProviderResult(
                {"master": [job_spec]},
                "operation-acp-01",
                "ok",
                "passed",
            )
        )
    )
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis, dataset_rid)

    service._collect_transform_dataset_lineage(target, analysis)

    record = next(iter(analysis.coverage_records.values()))
    assert record.status == "inconclusive"
    assert any(
        gap.reason_code == "response-shape-drift"
        and gap.locator
        == f"master.jobSpecs[0].{malformed_side}[0].datasetLocator.datasetRid"
        for gap in analysis.gaps.values()
    )


def test_acp_01_mixed_valid_and_malformed_branches_is_inconclusive():
    dataset_rid = "ri.foundry.main.dataset.output"
    provider = SimpleNamespace(
        invoke=Mock(
            return_value=ProviderResult(
                {
                    "broken": "not-a-jobspec-list",
                    "master": [
                        {
                            "rid": "ri.foundry.main.jobspec.transform",
                            "outputSpecs": [
                                {
                                    "type": "foundry",
                                    "datasetLocator": {"datasetRid": dataset_rid},
                                }
                            ],
                        }
                    ],
                },
                "operation-acp-01",
                "ok",
                "passed",
            )
        )
    )
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis, dataset_rid)

    service._collect_transform_dataset_lineage(target, analysis)

    record = next(iter(analysis.coverage_records.values()))
    assert record.status == "inconclusive"
    assert any(
        gap.reason_code == "response-shape-drift" and gap.locator == "broken.jobSpecs"
        for gap in analysis.gaps.values()
    )


def test_transform_ast_scope_accepts_only_canonical_literal_decorator():
    canonical = """from transforms.api import Input, Output, transform
@transform(output=Output("/out"), source=Input("/in"))
def compute(output, source): pass
"""
    matches, issues = DependencyGraphService._parse_transform_decorators(canonical)
    assert issues == []
    assert matches[0]["inputs"] == [("/in", 2)]
    assert matches[0]["outputs"] == [("/out", 2)]

    multiline_output = """from transforms.api import Input, Output, transform
@transform(output=Output(
    "/out",
))
def compute(output): pass
"""
    matches, issues = DependencyGraphService._parse_transform_decorators(
        multiline_output
    )
    assert issues == []
    assert matches[0]["outputs"] == [("/out", 3)]

    for unsupported in (
        "from transforms.api import Input, Output, transform as t\n"
        "@t(output=Output('/out'))\ndef compute(output): pass\n",
        "from transforms.api import Input, Output, transform\n"
        "PATH='/out'\n@transform(output=Output(PATH))\ndef compute(output): pass\n",
        "from transforms.api import Input, Output, transform\n"
        "@transform(first=Output('/one'), second=Output('/two'))\n"
        "def compute(first, second): pass\n",
        "from transforms.api import Input, Output, transform\n"
        "@incremental()\n@transform(output=Output('/out'))\n"
        "def compute(output): pass\n",
        "from transforms.api import Input, Output, transform\n"
        "@transform_df(Output('/out'))\ndef compute(output): pass\n",
        "from transforms.api import Input, Output, transform\n@transform(\n",
    ):
        matches, issues = DependencyGraphService._parse_transform_decorators(
            unsupported
        )
        assert matches == []
        assert issues and isinstance(issues[0]["line"], int)


@pytest.mark.parametrize(
    "source",
    [
        "from transforms.api import Input, Output, transform as t\n"
        "@t(output=Output('/out'))\ndef compute(output): pass\n",
        "from transforms.api import Input, Output, transform\n"
        "PATH='/out'\n@transform(output=Output(PATH))\ndef compute(output): pass\n",
        "from transforms.api import Input, Output, transform\n"
        "@transform(first=Output('/one'), second=Output('/two'))\n"
        "def compute(first, second): pass\n",
        "from transforms.api import Input, Output, transform\n"
        "@incremental()\n@transform(output=Output('/out'))\n"
        "def compute(output): pass\n",
        "from transforms.api import Input, Output, transform\n@transform(\n",
    ],
)
def test_unsupported_transform_source_reports_unresolved_gap_with_locator(source):
    provider = SimpleNamespace(invoke=Mock())
    provider.invoke.side_effect = [
        ProviderResult(
            {"fileContents": base64.b64encode(source.encode()).decode()},
            "operation-contents",
            "ok",
            "not-run",
        ),
        ProviderResult(
            {"blameRows": [{"startLine": 1, "endLine": 20}]},
            "operation-blame",
            "ok",
            "not-run",
        ),
    ]
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)
    repo = service._add_node(
        analysis,
        "code-repo",
        "transforms",
        {"resource_rid": "ri.stemma.main.repository.transforms"},
    )

    evidence_ids, source_status = service._collect_transform_source(
        analysis, target, repo, "transforms/main.py", "operation-jobspec"
    )

    assert evidence_ids == []
    assert source_status == "unresolved"
    assert any(
        gap.coverage == "unresolved"
        and gap.reason_code == "transform-source-unresolved"
        and gap.operation == "ACP-03"
        and gap.locator is not None
        and gap.locator.startswith("transforms/main.py:")
        for gap in analysis.gaps.values()
    )
    assert analysis.edges == {}


def test_compass_path_resolution_failure_reports_unresolved_gap_without_guessing():
    source = (
        "from transforms.api import Input, Output, transform\n"
        "@transform(output=Output('/out'), source=Input('/in'))\n"
        "def compute(output, source): pass\n"
    )
    provider = SimpleNamespace(invoke=Mock())
    provider.invoke.side_effect = [
        ProviderResult(
            {"fileContents": base64.b64encode(source.encode()).decode()},
            "operation-contents",
            "ok",
            "not-run",
        ),
        ProviderResult(
            {"blameRows": [{"lineNumber": 2}]},
            "operation-blame",
            "ok",
            "not-run",
        ),
        ProviderResult(
            {},
            "operation-compass",
            "empty",
            "not-run",
            "inconclusive",
            "inconclusive",
        ),
    ]
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)
    repo = service._add_node(
        analysis,
        "code-repo",
        "transforms",
        {"resource_rid": "ri.stemma.main.repository.transforms"},
    )

    evidence_ids, source_status = service._collect_transform_source(
        analysis, target, repo, "transforms/main.py", "operation-jobspec"
    )

    assert evidence_ids == []
    assert source_status == "inconclusive"
    assert any(
        gap.coverage == "inconclusive"
        and gap.reason_code == "compass-path-unresolved"
        and gap.operation == "ACP-08"
        and gap.locator == "/out"
        for gap in analysis.gaps.values()
    )
    assert analysis.edges == {}


def test_non_python_source_degrades_to_unresolved_with_locator():
    dataset_rid = "ri.foundry.main.dataset.output"
    internal_client = SimpleNamespace(conjure=Mock())
    internal_client.conjure.return_value = (
        200,
        {
            "master": [
                {
                    "rid": "ri.foundry.main.jobspec.sql",
                    "sourcePath": "queries/build.sql",
                    "inputSpecs": [
                        {
                            "inputType": "artifacts",
                            "datasetLocator": {
                                "datasetRid": "ri.stemma.main.repository.sql"
                            },
                        }
                    ],
                    "outputSpecs": [
                        {
                            "type": "foundry",
                            "datasetLocator": {"datasetRid": dataset_rid},
                        }
                    ],
                }
            ]
        },
        "{}",
    )
    service = DependencyGraphService(
        client=SimpleNamespace(),
        conjure_provider=ConjureRestProvider(internal_client),
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis, dataset_rid)
    service._collect_transform_dataset_lineage(target, analysis)
    result = _lineage_result(service, analysis)

    assert any(
        gap["coverage"] == "unresolved"
        and gap["reason_code"] == "transform-source-unresolved"
        and gap["operation"] == "ACP-01"
        and gap["locator"] == "master.jobSpecs[0]"
        for gap in result["gaps"]
    )


def test_acp_08_existence_token_expiry_is_a_gap_and_rid_is_path_encoded():
    dataset_rid = "ri.foundry.main.dataset.output/../?redirect#fragment"
    provider = SimpleNamespace(invoke=Mock(side_effect=TokenExpiredError("expired")))
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis, dataset_rid)

    assert (
        service._confirm_dataset_exists(analysis, target.node_id, dataset_rid) is False
    )

    request_path = provider.invoke.call_args.args[3]
    assert request_path == ACP_OPERATION_SPECS["ACP-08"].path.format(
        rid=quote(dataset_rid, safe="")
    )
    record = next(iter(analysis.coverage_records.values()))
    assert record.status == "token-expired"
    assert any(
        gap.operation == "ACP-08"
        and gap.coverage == "token-expired"
        and gap.reason_code == "token-expired"
        for gap in analysis.gaps.values()
    )


def test_acp_08_existence_unexpected_exception_propagates():
    provider = SimpleNamespace(
        invoke=Mock(side_effect=ValueError("broken existence collector"))
    )
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)

    with pytest.raises(ValueError, match="broken existence collector"):
        service._confirm_dataset_exists(
            analysis, target.node_id, target.identifiers["resource_rid"]
        )


def test_acp_03_source_token_expiry_is_a_gap_and_repo_rid_is_path_encoded():
    repo_rid = "ri.stemma.main.repository.transforms/../?redirect#fragment"
    provider = SimpleNamespace(invoke=Mock(side_effect=TokenExpiredError("expired")))
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)
    repo = service._add_node(
        analysis, "code-repo", "transforms", {"resource_rid": repo_rid}
    )

    evidence_ids, source_status = service._collect_transform_source(
        analysis, target, repo, "transforms/main.py", "operation-jobspec"
    )

    assert evidence_ids == []
    assert source_status == "token-expired"
    request_path = provider.invoke.call_args.args[3]
    assert request_path == TRANSFORM_LINEAGE_GET_OPERATION_SPECS["ACP-03"].path.format(
        repo_rid=quote(repo_rid, safe=""), path="transforms%2Fmain.py"
    )
    assert any(
        gap.operation == "ACP-03"
        and gap.coverage == "token-expired"
        and gap.reason_code == "token-expired"
        for gap in analysis.gaps.values()
    )


def test_acp_03_source_unexpected_exception_propagates():
    provider = SimpleNamespace(
        invoke=Mock(side_effect=ValueError("broken source collector"))
    )
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)
    repo = service._add_node(
        analysis,
        "code-repo",
        "transforms",
        {"resource_rid": "ri.stemma.main.repository.transforms"},
    )

    with pytest.raises(ValueError, match="broken source collector"):
        service._collect_transform_source(
            analysis, target, repo, "transforms/main.py", "operation-jobspec"
        )


def test_acp_08_path_resolution_token_expiry_is_a_gap():
    provider = SimpleNamespace(invoke=Mock(side_effect=TokenExpiredError("expired")))
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)

    assert service._resolve_compass_path(analysis, target.node_id, "/out") == (
        None,
        "token-expired",
    )
    record = next(iter(analysis.coverage_records.values()))
    assert record.status == "token-expired"
    assert any(
        gap.operation == "ACP-08"
        and gap.coverage == "token-expired"
        and gap.reason_code == "token-expired"
        for gap in analysis.gaps.values()
    )


def test_acp_08_path_resolution_unexpected_exception_propagates():
    provider = SimpleNamespace(
        invoke=Mock(side_effect=ValueError("broken path resolver"))
    )
    service = DependencyGraphService(
        client=SimpleNamespace(), conjure_provider=provider
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)

    with pytest.raises(ValueError, match="broken path resolver"):
        service._resolve_compass_path(analysis, target.node_id, "/out")


def test_acp_02_missing_fallbacks_and_empty_walk_are_inconclusive():
    internal_client = SimpleNamespace(conjure=Mock(return_value=(200, {}, "{}")))
    service = DependencyGraphService(
        client=SimpleNamespace(),
        conjure_provider=ConjureRestProvider(internal_client),
    )

    missing_context = service.create_context(host="https://example.test")
    missing_target = _lineage_target(service, missing_context)
    assert (
        service._invoke_build2_walk(
            missing_context, missing_target.node_id, "master", "downstream", {}
        )
        is None
    )
    missing_record = next(iter(missing_context.coverage_records.values()))
    assert (missing_record.status, missing_record.reason) == (
        "inconclusive",
        "missing-required-field",
    )
    internal_client.conjure.assert_not_called()

    empty_context = service.create_context(host="https://example.test")
    empty_target = _lineage_target(service, empty_context)
    assert (
        service._invoke_build2_walk(
            empty_context,
            empty_target.node_id,
            "master",
            "downstream",
            {"branchFallbacks": {"branches": []}},
        )
        is None
    )
    empty_record = next(iter(empty_context.coverage_records.values()))
    assert empty_record.status == "inconclusive"
    assert empty_record.status != "covered-empty"


@pytest.mark.parametrize(
    ("side_effect", "return_value"),
    [
        (TokenExpiredError("expired"), None),
        (None, (401, {"errorName": "Default:Unauthorized"}, "expired")),
    ],
)
def test_acp_02_token_expiry_remains_distinct(side_effect, return_value):
    internal_client = SimpleNamespace(
        conjure=Mock(side_effect=side_effect, return_value=return_value)
    )
    service = DependencyGraphService(
        client=SimpleNamespace(),
        conjure_provider=ConjureRestProvider(internal_client),
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)

    assert (
        service._invoke_build2_walk(
            analysis,
            target.node_id,
            "master",
            "downstream",
            {"branchFallbacks": {"branches": []}},
        )
        is None
    )

    record = next(iter(analysis.coverage_records.values()))
    assert (record.status, record.reason) == ("token-expired", "token-expired")
    assert any(
        gap.operation == "ACP-02"
        and gap.coverage == "token-expired"
        and gap.reason_code == "token-expired"
        for gap in analysis.gaps.values()
    )


def test_acp_02_can_degrade_an_existing_acp_01_surface_without_metadata_conflict():
    internal_client = SimpleNamespace(conjure=Mock(return_value=(200, {}, "{}")))
    service = DependencyGraphService(
        client=SimpleNamespace(),
        conjure_provider=ConjureRestProvider(internal_client),
    )
    analysis = service.create_context(host="https://example.test")
    target = _lineage_target(service, analysis)
    record = service._coverage_record(
        analysis,
        "dataset",
        TRANSFORM_DATASET_LINEAGE_SURFACE,
        target.node_id,
        operation="ACP-01",
        transport="conjure-rest",
        empty_is_inconclusive=True,
    )
    service._finish_coverage(record, "covered")

    assert (
        service._invoke_build2_walk(
            analysis,
            target.node_id,
            "master",
            "downstream",
            {"branchFallbacks": {"branches": []}},
        )
        is None
    )
    assert record.operation == "ACP-01"
    assert record.status == "inconclusive"


def test_u5_internal_specs_pin_the_three_south_edge_operations():
    assert set(ACP_OPERATION_SPECS) == {"ACP-04", "ACP-08"}
    assert set(TRANSFORM_LINEAGE_GET_OPERATION_SPECS) == {"ACP-01", "ACP-03"}
    assert TRANSFORM_LINEAGE_GET_OPERATION_SPECS["ACP-01"].path == (
        "/build2/api/jobspecs/datasets/{dataset_rid}"
    )
    assert TRANSFORM_LINEAGE_GET_OPERATION_SPECS["ACP-03"].path == (
        "/stemma/api/repos/{repo_rid}/paths/contents/{path}"
    )
    assert CONJURE_POST_OPERATION_SPECS["ACP-02"].path.endswith("/{direction}-jobspecs")


def test_service_detects_graphql_defined_on_real_internal_client_class():
    internal_client = object.__new__(FoundryInternalClient)

    service = DependencyGraphService(
        client=SimpleNamespace(),
        conjure_provider=SimpleNamespace(client=internal_client),
    )

    assert service._graphql_client is internal_client


def test_monocle_graph_v3_posts_exact_v3_branch_spec_body():
    object_type_rid = "ri.ontology.main.object-type.exact"
    _, internal_client = _analyze_object(
        [_dependent("ri.workshop.main.module.one", "Module", "One")],
        object_type_rid=object_type_rid,
        returned_rid=object_type_rid,
        requested_branch="release/2026-07",
    )

    monocle_call = next(
        call
        for call in internal_client.conjure.call_args_list
        if call.args[:2] == ("POST", "/monocle/api/links/graphV3")
    )
    assert monocle_call.kwargs["json_body"] == {
        "resourceIdentifiers": [object_type_rid],
        "branch": {
            "type": "legacyBranch",
            "legacyBranch": {
                "branch": "release/2026-07",
                "fallbacks": [],
            },
        },
        "serviceTypeFilter": [],
    }
    assert monocle_call.kwargs["expected"] is None
    assert monocle_call.kwargs["request_timeout"] == 30


def test_next_page_token_keeps_real_edges_but_poison_surface_as_truncated():
    result, _ = _analyze_object(
        [_dependent("ri.workshop.main.module.one", "Module", "One")],
        next_page_token="opaque-token",
    )

    assert any(
        edge["relation_kind"] == "object-consumed-by-workshop"
        for edge in result["graph"]["edges"]
    )
    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "silent-truncation"
        for item in result["coverage"]
    )
    assert any(
        gap["surface"] == "object-type-consumers"
        and gap["reason_code"] == "silent-truncation"
        and gap["coverage"] == "inconclusive"
        for gap in result["gaps"]
    )


def test_full_boundary_without_token_is_still_silent_truncation():
    values = [
        _dependent(f"ri.workshop.main.module.{index}", "Module", f"Module {index}")
        for index in range(ACP_05_DEPENDENTS_PAGE_BOUNDARY)
    ]

    result, _ = _analyze_object(values)

    assert (
        len(
            [
                edge
                for edge in result["graph"]["edges"]
                if edge["relation_kind"] == "object-consumed-by-workshop"
            ]
        )
        == ACP_05_DEPENDENTS_PAGE_BOUNDARY
    )
    assert any(
        gap["reason_code"] == "silent-truncation"
        and gap["surface"] == "object-type-consumers"
        for gap in result["gaps"]
    )


def test_null_object_type_is_not_found_without_sibling_effect():
    result, _ = _analyze_object([], graphql_object=False)

    assert any(
        edge["relation_kind"] == "column-backs-property"
        for edge in result["graph"]["edges"]
    )
    assert not any(
        edge["relation_kind"].startswith("object-consumed-by")
        for edge in result["graph"]["edges"]
    )
    assert any(
        gap["surface"] == "object-type-consumers" and gap["reason_code"] == "not-found"
        for gap in result["gaps"]
    )


def test_monocle_dropped_rid_does_not_flip_graphql_surface_to_covered_empty():
    result, _ = _analyze_object(
        [_dependent("ri.workshop.main.module.one", "Module", "One")],
        monocle_response={"nodes": []},
    )

    statuses = [
        item["status"]
        for item in result["coverage"]
        if item["surface"] == "object-type-consumers"
    ]
    assert statuses == ["covered"]
    assert "covered-empty" not in statuses


@pytest.mark.parametrize(
    ("monocle_error", "monocle_http_response"),
    [
        (TokenExpiredError("expired"), None),
        (None, (401, {"errorName": "Default:Unauthorized"}, "expired")),
    ],
)
def test_monocle_token_expiry_does_not_downgrade_graphql_coverage(
    monocle_error, monocle_http_response
):
    result, _ = _analyze_object(
        [_dependent("ri.workshop.main.module.one", "Module", "One")],
        monocle_error=monocle_error,
        monocle_http_response=monocle_http_response,
    )

    coverage = [
        item
        for item in result["coverage"]
        if item["surface"] == "object-type-consumers"
    ]
    assert [(item["status"], item["reason"]) for item in coverage] == [
        ("covered", None)
    ]
    assert any(
        edge["relation_kind"] == "object-consumed-by-workshop"
        for edge in result["graph"]["edges"]
    )


def test_monocle_budget_exhaustion_does_not_abort_graphql_coverage():
    result, _ = _analyze_object(
        [_dependent("ri.workshop.main.module.one", "Module", "One")],
        internal_budget=DiscoveryBudget(max_requests=2),
    )

    coverage = [
        item
        for item in result["coverage"]
        if item["surface"] == "object-type-consumers"
    ]
    assert [(item["status"], item["reason"]) for item in coverage] == [
        ("covered", None)
    ]
    assert any(
        edge["relation_kind"] == "object-consumed-by-workshop"
        for edge in result["graph"]["edges"]
    )
    assert result["internal_budget"]["used"]["requests"] == 2


def test_missing_object_type_rid_is_inconclusive_without_graphql_call():
    result, internal_client = _analyze_object([], object_type_rid=None)

    internal_client.graphql.assert_not_called()
    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "object-type-rid-unavailable"
        for item in result["coverage"]
    )
    assert any(
        gap["reason_code"] == "object-type-rid-unavailable"
        and gap["locator"] == "object_type.rid"
        for gap in result["gaps"]
    )


def test_pre_call_internal_budget_exhaustion_is_inconclusive():
    result, internal_client = _analyze_object(
        [], internal_budget=DiscoveryBudget(max_requests=1)
    )

    internal_client.graphql.assert_not_called()
    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "internal-budget-exhausted"
        for item in result["coverage"]
    )
    assert any(
        gap["operation"] == "ACP-05"
        and gap["reason_code"] == "budget-exhausted"
        and gap["retryable"] is True
        and gap["budget_snapshot"]["used"]["requests"] == 1
        for gap in result["gaps"]
    )


def test_graphql_token_expiry_is_a_distinct_consumer_gap():
    result, _ = _analyze_object([], graphql_error=TokenExpiredError("expired"))

    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "token-expired"
        and item["reason"] == "token-expired"
        for item in result["coverage"]
    )
    assert any(
        gap["operation"] == "ACP-05"
        and gap["reason_code"] == "token-expired"
        and gap["coverage"] == "token-expired"
        for gap in result["gaps"]
    )


def test_expected_graphql_transport_failure_is_inconclusive():
    result, _ = _analyze_object([], graphql_error=requests.Timeout("slow gateway"))

    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "timeout"
        for item in result["coverage"]
    )
    assert any(
        gap["operation"] == "ACP-05"
        and gap["reason_code"] == "timeout"
        and gap["retryable"] is True
        for gap in result["gaps"]
    )


def test_unexpected_graphql_failure_is_not_laundered_into_a_gap():
    with pytest.raises(ValueError, match="broken collector"):
        _analyze_object([], graphql_error=ValueError("broken collector"))


def test_graphql_errors_make_consumer_coverage_inconclusive():
    result, _ = _analyze_object(
        [],
        graphql_response=GraphQLResult(
            errors=[{"message": "dependents resolver unavailable"}]
        ),
    )

    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "graphql-errors"
        for item in result["coverage"]
    )
    assert any(
        gap["reason_code"] == "graphql-errors"
        and gap["message"] == "dependents resolver unavailable"
        for gap in result["gaps"]
    )


def test_inconclusive_graphql_retry_result_preserves_reason():
    result, _ = _analyze_object(
        [],
        graphql_response=GraphQLResult(
            status="inconclusive", reason="graphql-gateway-retry-failed: HTTP 500"
        ),
    )

    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "graphql-gateway-retry-failed: HTTP 500"
        for item in result["coverage"]
    )
    assert any(
        gap["reason_code"] == "graphql-gateway-retry-failed: HTTP 500"
        and gap["retryable"] is True
        for gap in result["gaps"]
    )


def test_mismatched_graphql_object_rid_is_response_shape_drift():
    result, _ = _analyze_object([], returned_rid="ri.ontology.main.object-type.other")

    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "response-shape-drift"
        for item in result["coverage"]
    )
    assert any(
        gap["reason_code"] == "response-shape-drift"
        and gap["locator"] == "objectTypeV2.rid"
        for gap in result["gaps"]
    )


@pytest.mark.parametrize(
    "dependents_override",
    [[], {"values": []}, {"values": "not-a-list", "nextPageToken": None}],
)
def test_malformed_graphql_dependents_are_response_shape_drift(
    dependents_override,
):
    result, _ = _analyze_object([], dependents_override=dependents_override)

    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "response-shape-drift"
        for item in result["coverage"]
    )
    assert any(
        gap["reason_code"] == "response-shape-drift"
        and gap["locator"] == "objectTypeV2.dependents"
        for gap in result["gaps"]
    )


def test_empty_graphql_dependents_are_inconclusive_not_covered_empty():
    result, _ = _analyze_object([])

    coverage = [
        item
        for item in result["coverage"]
        if item["surface"] == "object-type-consumers"
    ]
    assert [(item["status"], item["reason"]) for item in coverage] == [
        ("inconclusive", "endpoint-empty-inconclusive")
    ]
    assert all(item["status"] != "covered-empty" for item in coverage)
    assert any(
        gap["operation"] == "ACP-05"
        and gap["reason_code"] == "endpoint-empty-inconclusive"
        for gap in result["gaps"]
    )


def test_unmatched_and_invalid_dependents_poison_consumer_coverage():
    result, _ = _analyze_object(
        [
            _dependent("ri.ontology.main.relation.unknown", "Link type"),
            None,
        ]
    )

    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "response-shape-drift"
        for item in result["coverage"]
    )
    locators = {
        gap["locator"]
        for gap in result["gaps"]
        if gap["operation"] == "ACP-05" and gap["reason_code"] == "response-shape-drift"
    }
    assert locators == {
        "objectTypeV2.dependents.values[0]",
        "objectTypeV2.dependents.values[1]",
    }
    assert not any(
        edge["relation_kind"].startswith("object-consumed-by")
        for edge in result["graph"]["edges"]
    )


def test_internal_budget_exhaustion_is_inconclusive_and_sdk_collectors_continue():
    result, _ = _analyze_object(
        [
            _dependent("ri.workshop.main.module.one", "Module", "One"),
            _dependent("ri.workshop.main.module.two", "Module", "Two"),
        ],
        internal_budget=DiscoveryBudget(max_items=1),
    )

    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "internal-budget-exhausted"
        for item in result["coverage"]
    )
    assert any(
        gap["surface"] == "object-type-consumers"
        and gap["reason_code"] == "budget-exhausted"
        and gap["coverage"] == "inconclusive"
        for gap in result["gaps"]
    )
    sdk_methods = {
        item["sdk_method"]
        for item in result["operation_provenance"]
        if item["transport"] == "sdk"
    }
    assert "list" in sdk_methods
    assert result["budget"]["used"]["items"] == 0
    assert result["internal_budget"]["used"]["items"] == 1


def test_consumer_nodes_respect_the_user_graph_node_budget():
    result, _ = _analyze_object(
        [_dependent("ri.workshop.main.module.one", "Module", "One")],
        graph_budget=DiscoveryBudget(max_depth=1, max_nodes=3),
    )

    assert result["budget"]["used"]["nodes"] == 3
    assert not any(
        node["kind"] == "workshop-module" for node in result["graph"]["nodes"]
    )
    assert any(
        item["surface"] == "object-type-consumers"
        and item["status"] == "inconclusive"
        and item["reason"] == "graph-budget-exhausted"
        for item in result["coverage"]
    )


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_graphql_bulk_demuxes_out_of_order_object_dependents(storage_class, request):
    storage_class.return_value.get_profile.return_value = {
        "host": "https://example.test",
        "token": "token",
    }
    response = Mock(status_code=200)
    response.text = "\n\n".join(
        [
            'data:{"data":{"objectTypeV2":null},"extensions":{"requestIndex":1}}',
            'data:{"data":{"objectTypeV2":{"rid":"ri.first"}},"extensions":{"requestIndex":0}}',
        ]
    )
    request.return_value = response

    results = FoundryInternalClient("profile").graphql_bulk(
        [
            GraphQLOperation(
                "GetObjectTypeDependents",
                GET_OBJECT_TYPE_DEPENDENTS_QUERY,
                {"rid": "ri.first"},
            ),
            GraphQLOperation(
                "GetObjectTypeDependents",
                GET_OBJECT_TYPE_DEPENDENTS_QUERY,
                {"rid": "ri.missing"},
            ),
        ]
    )

    assert results[0].data == {"objectTypeV2": {"rid": "ri.first"}}
    assert results[1].data == {"objectTypeV2": None}
