"""Read-only cross-resource search via the Foundry GraphQL gateway."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..auth.base import ProfileNotFoundError
from ..auth.manager import AuthManager
from .foundry_internal_client import FoundryInternalClient, GraphQLResult


# VERIFIED against a live stack (see the GraphQL gateway reference): `search`
# accepts exactly `title: String!` and `limit: Int!` and returns
# `[SearchTitlesResult!]!`. `ResourceMetadata` is a confirmed member of that
# abstract type; select `rid`/`name`/`path`/`type` as scalars only. Do NOT add
# a resource-type filter argument — none is verified to exist. The query has
# NO page token, so results are capped at `limit` and the gateway does not
# report whether further matches exist (silent-truncation risk).
SEARCH_TITLES_QUERY = """query SearchTitles($t: String!, $l: Int!) {
  search(title: $t, limit: $l) {
    __typename
    ... on ResourceMetadata {
      rid
      name
      path
      type { name __typename }
    }
  }
}"""

TRUNCATION_NOTE = (
    "search(title:) has no page token; results are capped at --limit and the "
    "gateway does not report whether more matches exist"
)


class SearchService:
    """Search Foundry resources by title without treating absence as empty."""

    def __init__(
        self,
        profile: Optional[str] = None,
        *,
        client: Optional[FoundryInternalClient] = None,
    ) -> None:
        if client is not None:
            self.client = client
            return
        effective_profile = profile or AuthManager().get_current_profile()
        if not effective_profile:
            raise ProfileNotFoundError(
                "No profile specified and no default profile configured. "
                "Run 'pltr configure configure' to set up authentication."
            )
        self.client = FoundryInternalClient(effective_profile)

    def search(self, title: str, limit: int = 25) -> dict[str, Any]:
        """Return a fail-safe classification of one title search."""

        response = self.client.graphql(
            "SearchTitles",
            SEARCH_TITLES_QUERY,
            {"t": title, "l": limit},
        )
        if response.errors:
            return self._inconclusive(self._error_reason(response))
        if response.status == "inconclusive":
            return self._inconclusive(
                response.reason or "graphql-response-inconclusive"
            )

        data = response.data
        raw_results = data.get("search") if isinstance(data, Mapping) else None
        if not isinstance(raw_results, list):
            return self._inconclusive("search-null")

        results: list[dict[str, Any]] = []
        for entry in raw_results:
            if not isinstance(entry, Mapping):
                continue
            type_info = entry.get("type")
            results.append(
                {
                    "rid": entry.get("rid"),
                    "name": entry.get("name"),
                    "path": entry.get("path"),
                    "type": (
                        type_info.get("name")
                        if isinstance(type_info, Mapping)
                        else None
                    ),
                    "typename": entry.get("__typename"),
                }
            )
        return {
            "status": "ok",
            "reason": None,
            "query": title,
            "limit": limit,
            "truncation_note": TRUNCATION_NOTE,
            "results": results,
        }

    @staticmethod
    def _inconclusive(reason: str) -> dict[str, Any]:
        return {
            "status": "inconclusive",
            "reason": reason,
            "results": None,
        }

    @staticmethod
    def _error_reason(response: GraphQLResult) -> str:
        messages = [
            str(error.get("message"))
            for error in response.errors
            if error.get("message")
        ]
        return "; ".join(messages) or response.reason or "graphql-error"
