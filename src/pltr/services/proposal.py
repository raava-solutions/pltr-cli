"""Typed, fail-closed proposal lifecycle service.

The authenticated Foundry MCP catalog exposes a proposal surface that is not
present in the pinned ``foundry-platform-sdk`` client.  This service keeps that
distinction explicit: catalog verification alone does not authorize inventing
an SDK path or a raw HTTP endpoint.
"""

from enum import Enum
from typing import Any, Dict, Optional

from ..auth.base import MissingCredentialsError, ProfileNotFoundError
from .base import BaseService


class ProposalType(str, Enum):
    """Proposal systems supported by the unified command contract."""

    CODE_PR = "code-pr"
    GLOBAL_PROPOSAL = "global-proposal"


class ProposalAction(str, Enum):
    """Lifecycle actions exposed by the proposal command group."""

    CREATE = "create"
    LIST = "list"
    GET = "get"
    COMMENT = "comment"
    APPROVE = "approve"
    REQUEST_CHANGES = "request-changes"
    MERGE = "merge"
    ACCEPT = "accept"
    CLOSE = "close"


class ProposalError(Exception):
    """Base error with a stable category and CLI exit code."""

    category = "remote-service"
    exit_code = 7

    def to_payload(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "category": self.category,
                "message": str(self),
            },
        }


class ProposalAuthenticationError(ProposalError):
    category = "authentication"
    exit_code = 2


class ProposalAuthorizationError(ProposalError):
    category = "authorization"
    exit_code = 3


class ProposalValidationError(ProposalError):
    category = "validation"
    exit_code = 4


class ProposalConflictError(ProposalError):
    category = "conflict"
    exit_code = 5


class UnsupportedProposalCapabilityError(ProposalError):
    category = "unsupported-capability"
    exit_code = 6

    def __init__(self, proposal_type: ProposalType, action: ProposalAction):
        super().__init__(
            f"{action.value} is unavailable for {proposal_type.value}: "
            "foundry-platform-sdk 1.95.0 exposes no Code Repositories or "
            "Global Proposal client; no raw endpoint fallback is permitted"
        )
        self.proposal_type = proposal_type
        self.action = action

    def to_payload(self) -> Dict[str, Any]:
        payload = super().to_payload()
        payload["error"].update(
            {
                "proposal_type": self.proposal_type.value,
                "action": self.action.value,
            }
        )
        return payload


class ProposalRemoteServiceError(ProposalError):
    category = "remote-service"
    exit_code = 7


# Verified through the authenticated MCP catalog supplied with the approved
# plan. These operations are provider capabilities, not SDK reachability.
MCP_VERIFIED_CAPABILITIES = frozenset(
    {
        (ProposalType.CODE_PR, ProposalAction.CREATE),
        (ProposalType.CODE_PR, ProposalAction.LIST),
        (ProposalType.CODE_PR, ProposalAction.GET),
        (ProposalType.CODE_PR, ProposalAction.COMMENT),
        (ProposalType.GLOBAL_PROPOSAL, ProposalAction.CREATE),
        (ProposalType.GLOBAL_PROPOSAL, ProposalAction.GET),
        (ProposalType.GLOBAL_PROPOSAL, ProposalAction.CLOSE),
    }
)

# The pinned SDK's FoundryClient has no namespace for either proposal system.
# Consequently none of the catalog operations is callable by this CLI today.
SDK_REACHABLE_CAPABILITIES: frozenset[tuple[ProposalType, ProposalAction]] = frozenset()


def parse_proposal_type(value: str) -> ProposalType:
    """Parse an explicit proposal type without letting Typer infer it."""

    try:
        return ProposalType(value)
    except ValueError as exc:
        choices = ", ".join(item.value for item in ProposalType)
        raise ProposalValidationError(
            f"Unknown proposal type '{value}'. Choose one of: {choices}"
        ) from exc


def normalize_proposal_error(error: Exception) -> ProposalError:
    """Map authentication and provider failures into stable categories."""

    if isinstance(error, ProposalError):
        return error
    if isinstance(error, (ProfileNotFoundError, MissingCredentialsError)):
        return ProposalAuthenticationError(str(error))

    error_name = type(error).__name__
    if error_name in {"NotAuthenticated", "UnauthorizedError"}:
        return ProposalAuthenticationError(str(error))
    if "PermissionDenied" in error_name or error_name == "ForbiddenError":
        return ProposalAuthorizationError(str(error))
    if error_name in {
        "ValidationError",
        "BadRequestError",
        "UnprocessableEntityError",
    }:
        return ProposalValidationError(str(error))
    if "Conflict" in error_name:
        return ProposalConflictError(str(error))
    return ProposalRemoteServiceError(str(error))


class ProposalService(BaseService):
    """Capability-gated proposal service for the pinned Foundry SDK."""

    def _get_service(self) -> Any:
        """Return the root client only after a capability has been verified."""

        return self.client

    @staticmethod
    def _unsupported(
        proposal_type: ProposalType, action: ProposalAction
    ) -> UnsupportedProposalCapabilityError:
        return UnsupportedProposalCapabilityError(proposal_type, action)

    def _require_reachable(
        self, proposal_type: ProposalType, action: ProposalAction
    ) -> None:
        if (proposal_type, action) not in SDK_REACHABLE_CAPABILITIES:
            raise self._unsupported(proposal_type, action)

    def require_capability(
        self, proposal_type: ProposalType, action: ProposalAction
    ) -> None:
        """Fail before reads, prompts, or writes when an action is unreachable."""

        self._require_reachable(proposal_type, action)

    def create(
        self,
        proposal_type: ProposalType,
        *,
        parent_rid: str,
        title: str,
        source_ref: str,
        target_ref: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_reachable(proposal_type, ProposalAction.CREATE)
        raise self._unsupported(proposal_type, ProposalAction.CREATE)

    def list(
        self, proposal_type: ProposalType, *, parent_rid: str
    ) -> list[Dict[str, Any]]:
        self._require_reachable(proposal_type, ProposalAction.LIST)
        raise self._unsupported(proposal_type, ProposalAction.LIST)

    def get(
        self,
        proposal_type: ProposalType,
        proposal_id: str,
        *,
        parent_rid: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_reachable(proposal_type, ProposalAction.GET)
        raise self._unsupported(proposal_type, ProposalAction.GET)

    def comment(
        self,
        proposal_type: ProposalType,
        proposal_id: str,
        message: str,
        *,
        parent_rid: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_reachable(proposal_type, ProposalAction.COMMENT)
        raise self._unsupported(proposal_type, ProposalAction.COMMENT)

    def approve(
        self,
        proposal_type: ProposalType,
        proposal_id: str,
        *,
        parent_rid: Optional[str] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_reachable(proposal_type, ProposalAction.APPROVE)
        raise self._unsupported(proposal_type, ProposalAction.APPROVE)

    def request_changes(
        self,
        proposal_type: ProposalType,
        proposal_id: str,
        *,
        parent_rid: Optional[str] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_reachable(proposal_type, ProposalAction.REQUEST_CHANGES)
        raise self._unsupported(proposal_type, ProposalAction.REQUEST_CHANGES)

    def merge(
        self,
        proposal_type: ProposalType,
        proposal_id: str,
        *,
        parent_rid: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_reachable(proposal_type, ProposalAction.MERGE)
        raise self._unsupported(proposal_type, ProposalAction.MERGE)

    def accept(
        self,
        proposal_type: ProposalType,
        proposal_id: str,
        *,
        parent_rid: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_reachable(proposal_type, ProposalAction.ACCEPT)
        raise self._unsupported(proposal_type, ProposalAction.ACCEPT)

    def close(
        self,
        proposal_type: ProposalType,
        proposal_id: str,
        *,
        parent_rid: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_reachable(proposal_type, ProposalAction.CLOSE)
        raise self._unsupported(proposal_type, ProposalAction.CLOSE)
