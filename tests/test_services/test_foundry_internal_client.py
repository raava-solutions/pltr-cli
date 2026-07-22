"""Characterization tests for the GET-only Foundry internal HTTP client."""

from unittest.mock import Mock, patch

import pytest

from pltr.services.foundry_internal_client import (
    FoundryInternalClient,
    TokenExpiredError,
)


def _response(status: int, parsed, raw: str = "") -> Mock:
    response = Mock(status_code=status, text=raw)
    response.json.return_value = parsed
    return response


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_conjure_refreshes_host_and_token_for_every_request(storage_class, request):
    storage_class.return_value.get_profile.side_effect = [
        {"host": "https://first.example", "token": "first-token"},
        {"host": "https://second.example/", "token": "second-token"},
    ]
    request.side_effect = [
        _response(200, {"rid": "one"}, '{"rid":"one"}'),
        _response(200, {"rid": "two"}, '{"rid":"two"}'),
    ]
    client = FoundryInternalClient("profile")

    assert client.conjure("GET", "/one")[:2] == (200, {"rid": "one"})
    assert client.conjure("GET", "/two")[:2] == (200, {"rid": "two"})

    assert storage_class.return_value.get_profile.call_args_list == [
        (("profile",),),
        (("profile",),),
    ]
    assert request.call_args_list[0].kwargs["url"] == "https://first.example/one"
    assert request.call_args_list[1].kwargs["url"] == "https://second.example/two"
    assert (
        request.call_args_list[0].kwargs["headers"]["Authorization"]
        == "Bearer first-token"
    )
    assert (
        request.call_args_list[1].kwargs["headers"]["Authorization"]
        == "Bearer second-token"
    )


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_conjure_forwards_the_callers_request_timeout(storage_class, request):
    storage_class.return_value.get_profile.return_value = {
        "host": "https://example.test",
        "token": "token",
    }
    request.return_value = _response(200, {"rid": "one"})

    FoundryInternalClient("profile").conjure("GET", "/resource", request_timeout=7)

    assert request.call_args.kwargs["timeout"] == 7


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_conjure_does_not_raise_for_inspectable_non_success(storage_class, request):
    storage_class.return_value.get_profile.return_value = {
        "host": "https://example.test",
        "token": "token",
    }
    request.return_value = _response(
        422, {"errorName": "Conjure:UnprocessableEntity"}, "unprocessable"
    )

    assert FoundryInternalClient("profile").conjure("GET", "/resource") == (
        422,
        {"errorName": "Conjure:UnprocessableEntity"},
        "unprocessable",
    )
    request.return_value.raise_for_status.assert_not_called()


@patch("pltr.services.foundry_internal_client.requests.request")
@patch("pltr.services.foundry_internal_client.CredentialStorage")
def test_401_is_a_distinct_loud_token_expired_error(storage_class, request):
    storage_class.return_value.get_profile.return_value = {
        "host": "https://example.test",
        "token": "expired",
    }
    request.return_value = _response(
        401, {"errorName": "Default:Unauthorized"}, "expired"
    )

    with pytest.raises(TokenExpiredError) as raised:
        FoundryInternalClient("profile").conjure("GET", "/resource")

    assert raised.value.error_class == "token-expired"
    assert raised.value.error_class not in {"inaccessible", "inconclusive"}
