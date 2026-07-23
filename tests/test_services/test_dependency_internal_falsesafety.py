"""False-safety invariants for internal dependency providers."""

import ast
from dataclasses import replace
from datetime import date
import inspect
import re
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from pltr.services.dependency import (
    AnalysisContext,
    BudgetExhausted,
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
    InternalOperationSpec,
)
from pltr.services.dependency_providers import (
    ConjureRestProvider,
    ResultSemantics,
    SdkProvider,
    classify_conjure_response,
)
from pltr.services.foundry_internal_client import (
    FoundryInternalClient,
    TokenExpiredError,
)


def _context() -> AnalysisContext:
    return AnalysisContext.create(profile="test", host="https://example.test")


def _internal_specs() -> dict[str, InternalOperationSpec]:
    registries = (
        ACP_OPERATION_SPECS,
        TRANSFORM_LINEAGE_GET_OPERATION_SPECS,
        CONJURE_POST_OPERATION_SPECS,
        CONSUMER_CHARACTERIZATION_OPERATION_SPECS,
        GRAPHQL_OPERATION_SPECS,
    )
    specs: dict[str, InternalOperationSpec] = {}
    for registry in registries:
        assert not specs.keys() & registry.keys(), "ACP ids must be globally unique"
        specs.update(registry)
    return specs


@pytest.mark.parametrize("empty", [[], {}])
def test_internal_200_empty_is_inconclusive_never_covered_empty(empty):
    spec = ACP_OPERATION_SPECS["ACP-04"]
    assert ResultSemantics(spec, (200, empty, "")) == "empty"

    client = Mock()
    client.conjure.return_value = (200, empty, "")
    context = _context()
    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "empty"
    assert result.coverage_status == "inconclusive"
    assert result.coverage_status != "covered-empty"
    assert context.budget.used_requests == 0
    assert context.internal_budget.used_requests == 1


def test_operation_specific_empty_collection_is_also_inconclusive():
    spec = ACP_OPERATION_SPECS["ACP-04"]
    assert ResultSemantics(spec, (200, {"datasources": []}, "{}")) == "empty"


def test_internal_next_page_token_is_truncated():
    spec = ACP_OPERATION_SPECS["ACP-04"]
    payload = {
        "datasources": [
            {
                "definition": {
                    "type": "dataset",
                    "propertyMapping": {"employeeId": "employee_id"},
                }
            }
        ],
        "nextPageToken": "abc123",
    }

    assert ResultSemantics(spec, (200, payload, "...")) == "truncated"


def test_internal_truncated_response_is_inconclusive_never_covered():
    client = Mock()
    client.conjure.return_value = (
        200,
        {
            "datasources": [
                {
                    "definition": {
                        "type": "dataset",
                        "propertyMapping": {"employeeId": "employee_id"},
                    }
                }
            ],
            "nextPageToken": "abc123",
        },
        "...",
    )
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "truncated"
    assert result.coverage_status == "inconclusive"
    assert result.coverage_status not in {"covered", "covered-empty"}


def test_missing_required_discriminator_emits_shape_drift_gap_without_crashing():
    client = Mock()
    client.conjure.return_value = (
        200,
        {"datasources": [{"definition": {"type": "dataset"}}]},
        "{}",
    )
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "shape-drift"
    assert result.error_class == "response-shape-drift"
    assert any(
        gap.reason_code == "response-shape-drift" and gap.coverage == "inconclusive"
        for gap in context.gaps.values()
    )


def test_conforming_acp_04_response_is_covered_without_gap():
    client = Mock()
    client.conjure.return_value = (
        200,
        {
            "datasources": [
                {
                    "definition": {
                        "type": "dataset",
                        "propertyMapping": {"employeeId": "employee_id"},
                    },
                    "additiveServerField": True,
                }
            ],
            "additiveTopLevelField": {"ignored": True},
        },
        "{}",
    )
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "ok"
    assert result.coverage_status == "covered"
    assert result.error_class is None
    assert context.gaps == {}


@pytest.mark.parametrize(
    ("status", "payload", "expected_class", "expected_coverage"),
    [
        (
            400,
            {"errorName": "Default:InvalidArgument", "parameters": {}},
            "missing-required-field",
            "inconclusive",
        ),
        (
            422,
            {"errorName": "Conjure:UnprocessableEntity"},
            "invalid-request",
            "inconclusive",
        ),
        (
            403,
            {"errorName": "Default:PermissionDenied"},
            "inaccessible",
            "inaccessible",
        ),
        (200, {}, "inconclusive", "inconclusive"),
        (
            404,
            {"errorName": "Route:RouteNotMounted"},
            "route-not-mounted",
            "inconclusive",
        ),
    ],
)
def test_conjure_taxonomy(status, payload, expected_class, expected_coverage):
    classified = classify_conjure_response(status, payload)
    assert classified.error_class == expected_class
    assert classified.coverage == expected_coverage


def test_permission_denied_stays_inaccessible_even_when_semantics_are_ambiguous():
    client = Mock()
    client.conjure.return_value = (
        403,
        {"errorName": "Default:PermissionDenied"},
        "denied",
    )
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.result_semantics == "permission-ambiguous"
    assert result.coverage_status == "inaccessible"
    assert result.error_class == "inaccessible"
    assert any(gap.coverage == "inaccessible" for gap in context.gaps.values())


def test_provider_propagates_token_expired_without_inconclusive_result():
    client = Mock()
    client.conjure.side_effect = TokenExpiredError("expired")
    context = _context()

    with pytest.raises(TokenExpiredError) as raised:
        ConjureRestProvider(client).invoke(
            context,
            "ACP-04",
            "GET",
            "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
            None,
            target="property-node",
        )

    assert raised.value.error_class == "token-expired"
    assert not context.gaps
    classification = classify_conjure_response(
        401, {"errorName": "Default:Unauthorized"}
    )
    assert classification.coverage == "token-expired"
    assert classification.coverage != "inconclusive"


@pytest.mark.parametrize(
    ("error", "expected_class"),
    [
        (requests.ConnectionError("offline"), "connection"),
        (requests.Timeout("slow"), "timeout"),
        (requests.exceptions.SSLError("bad certificate"), "connection"),
    ],
)
def test_internal_transport_failure_degrades_to_retryable_coverage_gap(
    error, expected_class
):
    client = Mock()
    client.conjure.side_effect = error
    context = _context()

    result = ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert result.payload is None
    assert result.result_semantics is None
    assert result.coverage_status == "partial"
    assert result.error_class == expected_class
    assert result.retryable is True
    assert any(
        gap.reason_code == expected_class
        and gap.coverage == "partial"
        and gap.retryable is True
        for gap in context.gaps.values()
    )
    assert result.operation_provenance_id in context.operation_provenance


def test_finish_coverage_rejects_internal_covered_empty():
    service = DependencyGraphService(client=SimpleNamespace())
    record = service._coverage_record(
        _context(),
        "property",
        "property-column-mapping",
        "property-node",
        operation="ACP-04",
        transport="conjure-rest",
        empty_is_inconclusive=True,
    )

    with pytest.raises(ValueError, match="internal coverage cannot be covered-empty"):
        service._finish_coverage(record, "covered-empty")


def test_matrix_seeded_record_merges_internal_metadata_before_covered_empty_guard():
    service = DependencyGraphService(client=SimpleNamespace())
    context = _context()
    node = service._add_node(
        context,
        "property",
        "employeeId",
        {"property": "employeeId"},
        is_target=True,
    )
    target = DependencyTarget(
        "property",
        {"property": "employeeId"},
        "employeeId",
        node.id,
    )

    service._initialize_matrix(context, target)
    record = service._coverage_record(
        context,
        "property",
        "property-column-mapping",
        node.id,
        operation="ACP-04",
        transport="conjure-rest",
        empty_is_inconclusive=True,
    )

    assert record.operation == "ACP-04"
    assert record.transport == "conjure-rest"
    assert record.empty_is_inconclusive is True
    with pytest.raises(ValueError, match="internal coverage cannot be covered-empty"):
        service._finish_coverage(record, "covered-empty")


@pytest.mark.parametrize(
    ("response_name", "response"),
    [
        ("empty-object", (200, {}, "{}")),
        ("empty-list", (200, [], "[]")),
        ("truncated", (200, {"nextPageToken": "next"}, "{}")),
        ("permission-empty", (403, {}, "{}")),
    ],
)
@pytest.mark.parametrize("acp_id", [f"ACP-{index:02d}" for index in range(1, 9)])
def test_every_acp_ambiguous_response_finishes_inconclusive_not_covered_empty(
    acp_id, response_name, response
):
    spec = _internal_specs()[acp_id]
    semantics = ResultSemantics(spec, response)
    assert semantics in {
        "empty",
        "truncated",
        "shape-drift",
        "permission-ambiguous",
    }, f"{acp_id} classified {response_name} as authoritative"

    service = DependencyGraphService(client=SimpleNamespace())
    record = service._coverage_record(
        _context(),
        spec.target_kind,
        spec.coverage_surface,
        f"{acp_id}:{response_name}",
        operation=spec.acp_id,
        transport=spec.transport,
        empty_is_inconclusive=spec.empty_is_inconclusive,
    )
    service._finish_coverage(
        record,
        "inconclusive",
        reason=f"{semantics}-internal-response",
    )

    assert record.status == "inconclusive"
    assert record.status != "covered-empty"
    with pytest.raises(ValueError, match="internal coverage cannot be covered-empty"):
        service._finish_coverage(record, "covered-empty")
    assert record.status == "inconclusive"


def test_acp_01_is_the_only_fully_guarded_internal_covered_empty():
    service = DependencyGraphService(client=SimpleNamespace())
    spec = _internal_specs()["ACP-01"]
    record = service._coverage_record(
        _context(),
        spec.target_kind,
        spec.coverage_surface,
        "dataset:empty",
        operation=spec.acp_id,
        transport=spec.transport,
        empty_is_inconclusive=spec.empty_is_inconclusive,
    )

    service._finish_coverage(
        record,
        "covered-empty",
        reason_code="authoritative-empty-no-producer",
        positive_control_status="passed",
        existence_confirmed=True,
    )

    assert record.status == "covered-empty"
    assert record.reason_code == "authoritative-empty-no-producer"
    assert record.positive_control_status == "passed"
    assert record.existence_confirmed is True


@pytest.mark.parametrize(
    ("reason_code", "positive_control_status", "existence_confirmed"),
    [
        (None, "passed", True),
        ("authoritative-empty-no-producer", "not-run", True),
        ("authoritative-empty-no-producer", "passed", False),
    ],
)
def test_acp_01_covered_empty_rejects_each_missing_safety_guard(
    reason_code, positive_control_status, existence_confirmed
):
    service = DependencyGraphService(client=SimpleNamespace())
    spec = _internal_specs()["ACP-01"]
    record = service._coverage_record(
        _context(),
        spec.target_kind,
        spec.coverage_surface,
        "dataset:unguarded-empty",
        operation=spec.acp_id,
        transport=spec.transport,
        empty_is_inconclusive=spec.empty_is_inconclusive,
    )

    with pytest.raises(ValueError, match="internal coverage cannot be covered-empty"):
        service._finish_coverage(
            record,
            "covered-empty",
            reason_code=reason_code,
            positive_control_status=positive_control_status,
            existence_confirmed=existence_confirmed,
        )


def test_acp_registry_is_complete_and_matches_collector_references():
    specs = _internal_specs()
    registry_names = {
        "ACP_OPERATION_SPECS",
        "CONJURE_POST_OPERATION_SPECS",
        "CONSUMER_CHARACTERIZATION_OPERATION_SPECS",
        "GRAPHQL_OPERATION_SPECS",
        "TRANSFORM_LINEAGE_GET_OPERATION_SPECS",
    }
    service_source = textwrap.dedent(inspect.getsource(DependencyGraphService))
    collector_acp_ids = {
        node.slice.value
        for node in ast.walk(ast.parse(service_source))
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id in registry_names
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
        and re.fullmatch(r"ACP-\d{2}", node.slice.value)
    }

    assert set(specs) == {f"ACP-{index:02d}" for index in range(1, 9)}
    assert collector_acp_ids == set(specs)
    for acp_id, spec in specs.items():
        assert spec.acp_id == acp_id
        assert spec.contract_pins == {
            "mcp": "0.397.0",
            "verified_on": "2026-07-21",
        }
        assert re.fullmatch(r"\d+\.\d+\.\d+", spec.contract_pins["mcp"])
        assert date.fromisoformat(spec.contract_pins["verified_on"]) == date(
            2026, 7, 21
        )
        assert isinstance(spec.shape_descriptor, dict)
        assert "required" in spec.shape_descriptor
        assert callable(spec.positive_control)
        assert spec.positive_control_enabled is False


@pytest.mark.parametrize("acp_id", [f"ACP-{index:02d}" for index in range(1, 9)])
def test_positive_control_callable_accepts_response_and_enabled_canary_contract(acp_id):
    control = _internal_specs()[acp_id].positive_control
    inspect.signature(control).bind({}, enabled=False)
    assert control({}, enabled=False) == "not-run"


def test_drifted_positive_control_response_surfaces_shape_drift():
    spec = _internal_specs()["ACP-04"]

    def positive_control(response, *, enabled=False):
        if not enabled:
            return "not-run"
        return "passed" if ResultSemantics(spec, response) == "ok" else "failed"

    drifted_spec = replace(spec, positive_control=positive_control)
    drifted_response = (200, {"datasources": [{"definition": {}}]}, "{}")
    assert drifted_spec.positive_control(drifted_response, enabled=True) == "failed"

    service = DependencyGraphService(client=SimpleNamespace())
    record = service._coverage_record(
        _context(),
        spec.target_kind,
        spec.coverage_surface,
        "property:drifted-canary",
        operation=spec.acp_id,
        transport=spec.transport,
        empty_is_inconclusive=spec.empty_is_inconclusive,
    )
    service._finish_coverage(
        record,
        "inconclusive",
        reason="response-shape-drift",
        reason_code="response-shape-drift",
        positive_control_status="failed",
    )

    assert record.status == "inconclusive"
    assert record.reason_code == "response-shape-drift"
    assert record.positive_control_status == "failed"


def test_sse_out_of_order_demux_is_a_permanent_false_safety_guard():
    raw = "\n\n".join(
        [
            'data: {"data":{"value":"second"},"extensions":{"requestIndex":1}}',
            'data: {"data":{"value":"first"},"extensions":{"requestIndex":0}}',
            'data: {"data":{"value":"third"},"extensions":{"requestIndex":2}}',
            'data: {"data":{"value":"fourth"},"extensions":{"requestIndex":3}}',
        ]
    )

    frames = FoundryInternalClient._parse_graphql_sse(raw, operation_count=4)

    assert frames[0].data == {"value": "first"}
    assert frames[1].data == {"value": "second"}
    assert frames[2].data == {"value": "third"}
    assert frames[3].data == {"value": "fourth"}


def test_acp_02_missing_branch_fallbacks_remains_inconclusive_without_request():
    internal_client = SimpleNamespace(conjure=Mock())
    service = DependencyGraphService(
        client=SimpleNamespace(),
        conjure_provider=ConjureRestProvider(internal_client),
    )
    context = _context()

    assert (
        service._invoke_build2_walk(
            context,
            "dataset:target",
            "master",
            "downstream",
            {},
        )
        is None
    )

    record = next(iter(context.coverage_records.values()))
    assert record.status == "inconclusive"
    assert record.status != "covered-empty"
    internal_client.conjure.assert_not_called()


def test_internal_budget_exhaustion_does_not_starve_sdk_requests():
    context = AnalysisContext.create(
        profile="test",
        host="https://example.test",
        internal_budget=DiscoveryBudget(max_requests=1),
    )
    internal_client = Mock()
    internal_client.conjure.return_value = (200, {}, "{}")
    internal = ConjureRestProvider(internal_client)
    internal.invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    with pytest.raises(BudgetExhausted):
        internal.invoke(
            context,
            "ACP-04",
            "GET",
            "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
            None,
            target="property-node",
        )

    sdk_result = SdkProvider(Mock(return_value={"rid": "build"})).invoke(
        context, "build.get", {}, target="build"
    )
    assert sdk_result.result_semantics == "ok"
    assert context.internal_budget.used_requests == 1
    assert context.budget.used_requests == 1


def test_internal_provider_forwards_the_budgeted_request_timeout():
    context = AnalysisContext.create(
        profile="test",
        host="https://example.test",
        request_timeout_seconds=7,
    )
    client = Mock()
    client.conjure.return_value = (200, {}, "{}")

    ConjureRestProvider(client).invoke(
        context,
        "ACP-04",
        "GET",
        "/api/v2/ontologies/o/objectTypes/Employee?includeDatasources=true",
        None,
        target="property-node",
    )

    assert client.conjure.call_args.kwargs["request_timeout"] == 7
