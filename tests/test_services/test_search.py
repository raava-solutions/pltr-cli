"""Tests for fail-safe title search via the GraphQL gateway."""

from __future__ import annotations

from unittest.mock import Mock

from pltr.services.foundry_internal_client import GraphQLResult
from pltr.services.search import SEARCH_TITLES_QUERY, SearchService, TRUNCATION_NOTE


def _ok_frame(entries: list[dict]) -> GraphQLResult:
    return GraphQLResult(data={"search": entries})


def test_search_returns_normalized_results_and_truncation_note():
    client = Mock()
    client.graphql.return_value = _ok_frame(
        [
            {
                "__typename": "ResourceMetadata",
                "rid": "ri.foundry.main.dataset.1",
                "name": "Flights",
                "path": "/AIP Now Ontology/Data/Flights",
                "type": {"name": "Dataset", "__typename": "ResourceTypeMetadata"},
            },
            {
                "__typename": "ResourceMetadata",
                "rid": "ri.workshop.main.module.2",
                "name": "Flights Map",
                "path": "/Apps/Flights Map",
                "type": {"name": "Module", "__typename": "ResourceTypeMetadata"},
            },
        ]
    )

    result = SearchService(client=client).search("Flight", limit=4)

    assert result["status"] == "ok"
    assert result["reason"] is None
    assert result["query"] == "Flight"
    assert result["limit"] == 4
    assert result["truncation_note"] == TRUNCATION_NOTE
    assert [r["name"] for r in result["results"]] == ["Flights", "Flights Map"]
    assert result["results"][0]["type"] == "Dataset"
    assert result["results"][1]["rid"] == "ri.workshop.main.module.2"
    client.graphql.assert_called_once_with(
        "SearchTitles", SEARCH_TITLES_QUERY, {"t": "Flight", "l": 4}
    )


def test_empty_result_list_is_ok_not_inconclusive():
    client = Mock()
    client.graphql.return_value = _ok_frame([])

    result = SearchService(client=client).search("nothing matches")

    assert result["status"] == "ok"
    assert result["results"] == []


def test_null_search_field_is_inconclusive_not_empty():
    client = Mock()
    client.graphql.return_value = GraphQLResult(data={"search": None})

    result = SearchService(client=client).search("Flight")

    assert result["status"] == "inconclusive"
    assert result["reason"] == "search-null"
    assert result["results"] is None


def test_graphql_errors_are_inconclusive_with_message():
    client = Mock()
    client.graphql.return_value = GraphQLResult(
        errors=[{"message": "Validation error (FieldUndefined@[search/x]) : ..."}]
    )

    result = SearchService(client=client).search("Flight")

    assert result["status"] == "inconclusive"
    assert "FieldUndefined" in result["reason"]


def test_inconclusive_transport_status_propagates():
    client = Mock()
    client.graphql.return_value = GraphQLResult(
        status="inconclusive", reason="missing-response-frame"
    )

    result = SearchService(client=client).search("Flight")

    assert result["status"] == "inconclusive"
    assert result["reason"] == "missing-response-frame"


def test_malformed_entries_are_skipped_not_fatal():
    client = Mock()
    client.graphql.return_value = _ok_frame(
        [
            "not-a-mapping",
            {
                "__typename": "ResourceMetadata",
                "rid": "ri.compass.main.folder.3",
                "name": "Flight Sensor",
                "path": "/Data/Flight Sensor",
                "type": None,
            },
        ]
    )

    result = SearchService(client=client).search("Flight")

    assert result["status"] == "ok"
    assert len(result["results"]) == 1
    assert result["results"][0]["type"] is None


def test_query_text_matches_verified_shape():
    assert "search(title: $t, limit: $l)" in SEARCH_TITLES_QUERY
    assert "mutation" not in SEARCH_TITLES_QUERY.lower()


def test_hostile_text_travels_only_via_variables():
    # Injection-safe design pin: user text must only reach the gateway as a
    # GraphQL variable, never interpolated into the static query constant.
    client = Mock()
    client.graphql.return_value = _ok_frame([])

    hostile = 'mutation { x } "quoted"\nwith newline'
    SearchService(client=client).search(hostile, limit=7)

    operation, query, variables = client.graphql.call_args.args
    assert operation == "SearchTitles"
    assert query == SEARCH_TITLES_QUERY
    assert variables == {"t": hostile, "l": 7}
    assert hostile not in SEARCH_TITLES_QUERY
    assert "$t" in SEARCH_TITLES_QUERY
