"""Tests for fail-safe notepad reads and the GraphQL-SSE transport."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from pltr.services.foundry_internal_client import (
    FoundryInternalClient,
    GraphQLOperation,
    GraphQLResult,
    TokenExpiredError,
)
from pltr.services.notepad import GET_NOTEPAD_CONTENTS_QUERY, NotepadService


def _readable_frame() -> GraphQLResult:
    body = [
        {"type": "paragraph", "children": [{"text": "Read this prose."}]},
        {
            "type": "container",
            "children": [
                {
                    "type": "custom-section",
                    "config": {
                        "sectionTypeId": (
                            "rich-text-editor.section.v1."
                            "compass-resource-section-plugin"
                        ),
                        "sectionConfig": {
                            "config": {"rid": "ri.foundry.main.dataset.example"}
                        },
                    },
                    "children": [],
                },
                {
                    "type": "custom-section",
                    "config": {
                        "sectionTypeId": (
                            "rich-text-editor.section.v1."
                            "stored-image-custom-section-plugin"
                        ),
                        "sectionConfig": {
                            "config": {
                                "name": "chart.png",
                                "snapshotRid": "ri.snapshot.1",
                            }
                        },
                    },
                    "children": [],
                },
            ],
        },
    ]
    return GraphQLResult(
        data={
            "notepad": {
                "rid": "ri.notepad.1",
                "metadata": {
                    "name": "Example",
                    "lastModifiedAt": "2026-07-22T00:00:00Z",
                    "description": "A test",
                    "tags": ["test"],
                },
                "latestVersion": {
                    "name": "Version 1",
                    "version": 1,
                    "contents": json.dumps(body),
                },
            }
        }
    )


def test_readable_notepad_extracts_two_level_configs_and_plain_text():
    client = Mock()
    client.graphql.return_value = _readable_frame()

    result = NotepadService(client=client).get("ri.notepad.1")

    assert result["status"] == "readable"
    assert result["name"] == "Example"
    assert result["version"] == 1
    assert "Read this prose." in result["body_text"]
    assert result["references"] == [
        {
            "section_type_id": (
                "rich-text-editor.section.v1.compass-resource-section-plugin"
            ),
            "kind": "compass-resource-section-plugin",
            "config": {"rid": "ri.foundry.main.dataset.example"},
        },
        {
            "section_type_id": (
                "rich-text-editor.section.v1.stored-image-custom-section-plugin"
            ),
            "kind": "stored-image-custom-section-plugin",
            "config": {"name": "chart.png", "snapshotRid": "ri.snapshot.1"},
        },
    ]
    client.graphql.assert_called_once_with(
        "GetNotepadContentsQuery",
        GET_NOTEPAD_CONTENTS_QUERY,
        {"notepadRid": "ri.notepad.1"},
    )
    assert "permissions" not in GET_NOTEPAD_CONTENTS_QUERY
    assert "mutation" not in GET_NOTEPAD_CONTENTS_QUERY.lower()


def test_notepad_null_is_inconclusive_and_never_empty():
    client = Mock()
    client.graphql.return_value = GraphQLResult(data={"notepad": None})

    result = NotepadService(client=client).get("ri.notepad.missing")

    assert result["status"] == "inconclusive"
    assert result["reason"] == "notepad-null"
    assert result["status"] != "empty-document"


def test_empty_contents_is_a_valid_empty_document():
    client = Mock()
    client.graphql.return_value = GraphQLResult(
        data={
            "notepad": {
                "metadata": {"name": "Empty"},
                "latestVersion": {"version": 2, "contents": ""},
            }
        }
    )

    result = NotepadService(client=client).get("ri.notepad.empty")

    assert result["status"] == "empty-document"
    assert result["body"] == []
    assert result["references"] == []


def test_null_contents_is_inconclusive_and_never_empty():
    client = Mock()
    client.graphql.return_value = GraphQLResult(
        data={
            "notepad": {
                "metadata": {"name": "Unreadable"},
                "latestVersion": {"version": 2, "contents": None},
            }
        }
    )

    result = NotepadService(client=client).get("ri.notepad.unreadable")

    assert result["status"] == "inconclusive"
    assert result["reason"] == "contents-null"
    assert result["status"] != "empty-document"


def test_graphql_validation_error_is_inconclusive():
    client = Mock()
    client.graphql.return_value = GraphQLResult(
        data=None,
        errors=[
            {
                "message": (
                    "Field 'permissions' of type 'NotepadPermissions!' must have "
                    "a selection of subfields."
                ),
                "extensions": {"errorType": "ValidationError"},
            }
        ],
    )

    result = NotepadService(client=client).get("ri.notepad.1")

    assert result["status"] == "inconclusive"
    assert "permissions" in result["reason"]
    assert result["status"] not in {"readable", "empty-document"}


def test_token_expired_propagates_from_service():
    client = Mock()
    client.graphql.side_effect = TokenExpiredError("expired")

    with pytest.raises(TokenExpiredError):
        NotepadService(client=client).get("ri.notepad.1")


def _response(status: int, text: str) -> Mock:
    return Mock(status_code=status, text=text)


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_graphql_sse_demuxes_out_of_order_frames(storage_class, request):
    storage_class.return_value.get_profile.return_value = {
        "host": "https://foundry.example/",
        "token": "token",
    }
    request.return_value = _response(
        200,
        "\n".join(
            [
                'data:{"data":{"notepad":{"rid":"second"}},"extensions":{"requestIndex":1}}',
                'data:{"data":{"notepad":{"rid":"first"}},"extensions":{"requestIndex":0}}',
            ]
        ),
    )
    operations = [
        GraphQLOperation("First", "query First { first }", {}),
        GraphQLOperation("Second", "query Second { second }", {}),
    ]

    results = FoundryInternalClient("qa").graphql_bulk(operations)

    assert results[0].data == {"notepad": {"rid": "first"}}
    assert results[1].data == {"notepad": {"rid": "second"}}
    assert request.call_args.kwargs["url"] == (
        "https://foundry.example/graphql-gateway/api/bulk"
    )
    assert request.call_args.kwargs["headers"] == {
        "Authorization": "Bearer token",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "fetch-user-agent": "hubble/6.525.9 forge-graphql-client/0.0.0",
    }
    assert request.call_args.kwargs["json"] == {
        "operations": {
            "0": "query First { first }",
            "1": "query Second { second }",
        },
        "requests": [
            {"hash": "0", "name": "First", "variables": {}},
            {"hash": "1", "name": "Second", "variables": {}},
        ],
    }


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_service_posts_exact_pinned_notepad_query(storage_class, request):
    storage_class.return_value.get_profile.return_value = {
        "host": "https://foundry.example",
        "token": "token",
    }
    request.return_value = _response(
        200,
        'data:{"data":{"notepad":{"rid":"ri.notepad.1",'
        '"metadata":{"name":"Empty"},"latestVersion":{"name":"v1",'
        '"contents":"","version":1}}},"extensions":{"requestIndex":0}}',
    )

    result = NotepadService(client=FoundryInternalClient("qa")).get("ri.notepad.1")

    assert result["status"] == "empty-document"
    assert request.call_args.kwargs["json"] == {
        "operations": {"0": GET_NOTEPAD_CONTENTS_QUERY},
        "requests": [
            {
                "hash": "0",
                "name": "GetNotepadContentsQuery",
                "variables": {"notepadRid": "ri.notepad.1"},
            }
        ],
    }
    assert "permissions" not in request.call_args.kwargs["json"]["operations"]["0"]


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_multi_operation_500_does_not_expand_into_many_retries(storage_class, request):
    storage_class.return_value.get_profile.return_value = {
        "host": "foundry.example",
        "token": "token",
    }
    request.return_value = _response(500, "gateway failure")

    results = FoundryInternalClient("qa").graphql_bulk(
        [
            GraphQLOperation("First", "query First { first }", {}),
            GraphQLOperation("Second", "query Second { second }", {}),
        ]
    )

    assert request.call_count == 1
    assert [result.status for result in results] == [
        "inconclusive",
        "inconclusive",
    ]


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_graphql_sse_preserves_validation_errors(storage_class, request):
    storage_class.return_value.get_profile.return_value = {
        "host": "foundry.example",
        "token": "token",
    }
    request.return_value = _response(
        200,
        'data:{"errors":[{"message":"SubselectionRequired",'
        '"extensions":{"errorType":"ValidationError"}}],'
        '"extensions":{"requestIndex":0}}',
    )

    result = FoundryInternalClient("qa").graphql(
        "GetNotepadContentsQuery",
        GET_NOTEPAD_CONTENTS_QUERY,
        {"notepadRid": "ri.notepad.1"},
    )

    assert result.data is None
    assert result.errors == [
        {
            "message": "SubselectionRequired",
            "extensions": {"errorType": "ValidationError"},
        }
    ]


@pytest.mark.parametrize(
    "query",
    [
        "mutation Write { updateSomething }",
        "# disguised by a leading comment\nmutation Write { updateSomething }",
    ],
)
@patch("pltr.services.foundry_internal_client.requests.request")
def test_graphql_transport_rejects_mutations_without_http(request, query):
    with pytest.raises(ValueError, match="only permits GraphQL reads"):
        FoundryInternalClient("qa").graphql(
            "Write",
            query,
            {},
        )

    request.assert_not_called()


@pytest.mark.parametrize("status", [401, 403])
@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_graphql_auth_failure_is_loud(storage_class, request, status):
    storage_class.return_value.get_profile.return_value = {
        "host": "foundry.example",
        "token": "expired",
    }
    request.return_value = _response(status, "expired")

    with pytest.raises(TokenExpiredError):
        FoundryInternalClient("qa").graphql("Read", "query Read { value }", {})


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_graphql_500_retries_single_request_once(storage_class, request):
    storage_class.return_value.get_profile.side_effect = [
        {"host": "foundry.example", "token": "first"},
        {"host": "https://foundry.example", "token": "second"},
    ]
    request.side_effect = [
        _response(500, "gateway failure"),
        _response(
            200,
            'data:{"data":{"notepad":{"rid":"ok"}},"extensions":{"requestIndex":0}}',
        ),
    ]

    result = FoundryInternalClient("qa").graphql(
        "GetNotepadContentsQuery",
        GET_NOTEPAD_CONTENTS_QUERY,
        {"notepadRid": "ri.notepad.1"},
    )

    assert result.data == {"notepad": {"rid": "ok"}}
    assert request.call_count == 2
    assert storage_class.return_value.get_profile.call_count == 2
    assert (
        request.call_args_list[0].kwargs["json"]
        == request.call_args_list[1].kwargs["json"]
    )


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_graphql_failed_retry_is_classified_without_looping(storage_class, request):
    storage_class.return_value.get_profile.return_value = {
        "host": "foundry.example",
        "token": "token",
    }
    request.side_effect = [
        _response(500, "gateway failure"),
        _response(200, "not an SSE frame"),
    ]

    result = FoundryInternalClient("qa").graphql(
        "GetNotepadContentsQuery",
        GET_NOTEPAD_CONTENTS_QUERY,
        {"notepadRid": "ri.notepad.1"},
    )

    assert result.status == "inconclusive"
    assert result.errors == []
    assert result.reason == ("graphql-gateway-retry-failed: missing-response-frame")
    assert request.call_count == 2
