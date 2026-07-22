from types import SimpleNamespace
from unittest.mock import Mock

from pltr.services.dependency import DependencyGraphService, DiscoveryBudget
from pltr.services.dependency_providers import ConjureRestProvider
from pltr.services.foundry_internal_client import TokenExpiredError


def _sdk_client(*property_names: str) -> SimpleNamespace:
    metadata = SimpleNamespace(
        object_type=SimpleNamespace(
            properties={name: SimpleNamespace() for name in property_names}
        ),
        link_types=[],
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
