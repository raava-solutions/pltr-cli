"""HTTP client for inspectable, read-only Foundry internal API requests."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

import requests

from ..auth.storage import CredentialStorage


class TokenExpiredError(RuntimeError):
    """A loud authentication failure that internal providers must not degrade."""

    error_class = "token-expired"
    retryable = False

    def __init__(self, raw: str = "") -> None:
        super().__init__(
            "Foundry session token expired; re-authenticate before dependency analysis"
        )
        self.raw = raw


@dataclass(frozen=True)
class GraphQLResult:
    """One demultiplexed GraphQL gateway result."""

    data: Optional[Mapping[str, Any]] = None
    errors: list[Mapping[str, Any]] = field(default_factory=list)
    status: str = "ok"
    reason: Optional[str] = None


@dataclass(frozen=True)
class GraphQLOperation:
    """A named read query and its variables for the bulk gateway."""

    name: str
    query: str
    variables: Mapping[str, Any]


class FoundryInternalClient:
    """Issue inspectable Conjure-style requests with fresh credentials each time."""

    def __init__(self, profile: str) -> None:
        self.profile = profile

    @staticmethod
    def _base_url(raw_host: Any) -> str:
        """Normalize a stored profile host into a scheme-qualified base URL.

        Stored profiles keep ``host`` verbatim, so it may or may not carry a
        scheme. A bare host would make ``requests`` raise ``MissingSchema``;
        prepend ``https://`` only when no scheme is present, so an explicit
        ``http://`` profile is preserved. Shared by the Conjure and GraphQL
        request paths so both normalize identically.
        """

        host = str(raw_host or "").strip().rstrip("/")
        if host.startswith(("http://", "https://")):
            return host
        return f"https://{host}"

    def conjure(
        self,
        verb: str,
        path: str,
        *,
        json_body: Optional[Mapping[str, Any]] = None,
        expected: Optional[int | Iterable[int]] = None,
        request_timeout: float = 30.0,
    ) -> tuple[int, Any, str]:
        """Return status, permissively parsed payload, and raw body.

        Statuses are intentionally not raised: internal response semantics use
        400/422 responses as contract signals. ``expected`` is accepted as
        operation metadata for callers but does not suppress inspection.
        """

        credentials = CredentialStorage().get_profile(self.profile)
        base_url = self._base_url(credentials.get("host", ""))
        token = credentials.get("token")
        response = requests.request(
            method=verb.upper(),
            url=f"{base_url}/{path.lstrip('/')}",
            json=dict(json_body) if json_body is not None else None,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=request_timeout,
        )
        raw = response.text
        try:
            parsed: Any = response.json()
        except (requests.JSONDecodeError, ValueError):
            parsed = raw
        if response.status_code == 401:
            raise TokenExpiredError(raw)
        return response.status_code, parsed, raw

    def graphql_bulk(
        self,
        operations: Sequence[GraphQLOperation | Mapping[str, Any]],
        *,
        request_timeout: float = 30.0,
    ) -> list[GraphQLResult]:
        """Run read queries through the GraphQL bulk gateway.

        Results retain request order, but response frames are assigned only by
        ``extensions.requestIndex`` because the SSE stream can arrive out of
        order. An unusable HTTP 500 for a single-operation batch is retried
        once with the same operation; a second failure is inconclusive.
        """

        normalized = [self._normalize_graphql_operation(item) for item in operations]
        if not normalized:
            return []
        for operation in normalized:
            if re.search(r"(?i)\bmutation\b", operation.query):
                raise ValueError("FoundryInternalClient only permits GraphQL reads")

        status, results, usable = self._graphql_request(
            normalized, request_timeout=request_timeout
        )
        if status == 500 and not usable and len(normalized) == 1:
            retry_status, retry_results, retry_usable = self._graphql_request(
                normalized, request_timeout=request_timeout
            )
            if retry_usable:
                return retry_results
            retry_result = retry_results[0]
            return [
                GraphQLResult(
                    data=retry_result.data,
                    errors=retry_result.errors,
                    status="inconclusive",
                    reason=(
                        "graphql-gateway-retry-failed: "
                        f"{retry_result.reason or f'HTTP {retry_status}'}"
                    ),
                )
            ]
        return results

    def graphql(
        self,
        operation_name: str,
        query: str,
        variables: Mapping[str, Any],
        *,
        request_timeout: float = 30.0,
    ) -> GraphQLResult:
        """Run one read query and return its data and GraphQL errors."""

        return self.graphql_bulk(
            [GraphQLOperation(operation_name, query, variables)],
            request_timeout=request_timeout,
        )[0]

    @staticmethod
    def _normalize_graphql_operation(
        operation: GraphQLOperation | Mapping[str, Any],
    ) -> GraphQLOperation:
        if isinstance(operation, GraphQLOperation):
            return operation
        return GraphQLOperation(
            name=str(operation["name"]),
            query=str(operation["query"]),
            variables=operation.get("variables", {}),
        )

    def _graphql_request(
        self,
        operations: Sequence[GraphQLOperation],
        *,
        request_timeout: float,
    ) -> tuple[int, list[GraphQLResult], bool]:
        credentials = CredentialStorage().get_profile(self.profile)
        base_url = self._base_url(credentials.get("host", ""))
        token = credentials.get("token")
        body = {
            "operations": {
                str(index): operation.query
                for index, operation in enumerate(operations)
            },
            "requests": [
                {
                    "hash": str(index),
                    "name": operation.name,
                    "variables": dict(operation.variables),
                }
                for index, operation in enumerate(operations)
            ],
        }
        response = requests.request(
            method="POST",
            url=f"{base_url}/graphql-gateway/api/bulk",
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                "fetch-user-agent": "hubble/6.525.9 forge-graphql-client/0.0.0",
            },
            timeout=request_timeout,
        )
        raw = response.text
        if response.status_code in {401, 403}:
            raise TokenExpiredError(raw)

        frames = self._parse_graphql_sse(raw, len(operations))
        usable = bool(frames)
        if not 200 <= response.status_code < 300:
            reason = f"graphql-gateway-http-{response.status_code}"
            return (
                response.status_code,
                [
                    frames.get(
                        index,
                        self._inconclusive_graphql_result(response.status_code, reason),
                    )
                    for index in range(len(operations))
                ],
                usable,
            )
        return (
            response.status_code,
            [
                frames.get(
                    index,
                    GraphQLResult(
                        status="inconclusive", reason="missing-response-frame"
                    ),
                )
                for index in range(len(operations))
            ],
            usable,
        )

    @staticmethod
    def _parse_graphql_sse(raw: str, operation_count: int) -> dict[int, GraphQLResult]:
        frames: dict[int, GraphQLResult] = {}
        for line in raw.splitlines():
            if not line.startswith("data:"):
                continue
            payload_text = line[len("data:") :].strip()
            if not payload_text or payload_text == "[DONE]":
                continue
            try:
                payload = json.loads(payload_text)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, Mapping):
                continue
            extensions = payload.get("extensions")
            if not isinstance(extensions, Mapping):
                continue
            raw_request_index = extensions.get("requestIndex")
            if not isinstance(raw_request_index, (int, str)):
                continue
            try:
                request_index = int(raw_request_index)
            except ValueError:
                continue
            if not 0 <= request_index < operation_count:
                continue
            data = payload.get("data")
            errors = payload.get("errors")
            normalized_errors = (
                [error for error in errors if isinstance(error, Mapping)]
                if isinstance(errors, list)
                else []
            )
            existing = frames.get(request_index)
            combined_errors = [
                *(existing.errors if existing else []),
                *normalized_errors,
            ]
            frames[request_index] = GraphQLResult(
                data=data
                if isinstance(data, Mapping)
                else (existing.data if existing else None),
                errors=combined_errors,
                status="ok",
            )
        return frames

    @staticmethod
    def _inconclusive_graphql_result(status: int, reason: str) -> GraphQLResult:
        return GraphQLResult(
            status="inconclusive",
            reason=f"{reason} (HTTP {status})",
        )
