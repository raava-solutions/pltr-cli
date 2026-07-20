"""Verified Compass discovery operations.

The pinned SDK exposes filesystem Spaces, but it does not expose a separate
namespace or project-template catalog.  This service keeps that distinction
explicit: spaces can be listed as the native namespace-like discovery surface,
while template listing fails closed with a documented blocker.
"""

from typing import Any, Dict, List, Optional

from ..utils.pagination import PaginationMetadata, PaginationResult
from .base import BaseService


class UnsupportedCapabilityError(RuntimeError):
    """Raised when the pinned public SDK has no contract for an operation."""


class CompassService(BaseService):
    """Service wrapper for verified Compass filesystem discovery APIs."""

    def _get_service(self) -> Any:
        return self.client.filesystem

    def list_namespaces(
        self,
        *,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> PaginationResult:
        """List Compass Spaces, the SDK's top-level filesystem containers.

        There is no ``Namespace`` resource in SDK 1.95.0.  The result marks
        each record as a namespace discovery record while retaining the exact
        native ``space`` source type for callers that need the distinction.
        """
        try:
            params: Dict[str, Any] = {}
            if page_size is not None:
                params["page_size"] = page_size
            if page_token is not None:
                params["page_token"] = page_token

            iterator = self.service.Space.list(**params)
            raw_items, next_token = self._read_sdk_page(iterator)
            namespaces = [self._format_namespace(item) for item in raw_items]
            return PaginationResult(
                data=namespaces,
                metadata=PaginationMetadata(
                    current_page=1,
                    items_fetched=len(namespaces),
                    next_page_token=next_token,
                    has_more=next_token is not None,
                    total_pages_fetched=1,
                ),
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to list Foundry namespaces: {self._format_error_detail(e)}"
            )

    def list_project_templates(
        self,
        *,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> PaginationResult:
        """Fail closed because SDK 1.95.0 has no template-list operation.

        The SDK verifies ``Project.create_from_template`` and defines a
        ``ProjectTemplateRid`` type, but it provides no endpoint or model for
        enumerating templates.  A template RID can therefore be used for the
        existing create command only when supplied by the operator.
        """
        del page_size, page_token
        raise UnsupportedCapabilityError(
            "Project template listing is unavailable in foundry-platform-sdk "
            "1.95.0: the public filesystem SDK exposes create_from_template "
            "but no list-project-templates operation or documented template "
            "catalog endpoint. Supply a verified template RID explicitly."
        )

    @staticmethod
    def _read_sdk_page(iterator: Any) -> tuple[List[Any], Optional[str]]:
        page_data = getattr(iterator, "data", None)
        if page_data is not None and not isinstance(page_data, (list, tuple)):
            raise TypeError("SDK page data must be a list")
        if isinstance(page_data, (list, tuple)):
            raw_items = list(page_data)
        else:
            if isinstance(iterator, (str, bytes, dict)):
                raise TypeError("SDK page response must be an iterator")
            raw_items = list(iterator)
        next_token = getattr(iterator, "next_page_token", None)
        if not isinstance(next_token, str) or not next_token:
            next_token = None
        return raw_items, next_token

    @staticmethod
    def _format_namespace(space: Any) -> Dict[str, Any]:
        return {
            "rid": getattr(space, "rid", None),
            "display_name": getattr(space, "display_name", None),
            "description": getattr(space, "description", None),
            "path": getattr(space, "path", None),
            "file_system_id": getattr(space, "file_system_id", None),
            "usage_account_rid": getattr(space, "usage_account_rid", None),
            "organizations": list(getattr(space, "organizations", None) or []),
            "deletion_policy_organizations": list(
                getattr(space, "deletion_policy_organizations", None) or []
            ),
            "default_role_set_id": getattr(space, "default_role_set_id", None),
            "space_maven_identifier": getattr(space, "space_maven_identifier", None),
            "type": "namespace",
            "source_type": "space",
        }

    @staticmethod
    def _format_error_detail(error: Exception) -> str:
        message = str(error).strip()
        if message:
            return message
        return error.__class__.__name__
