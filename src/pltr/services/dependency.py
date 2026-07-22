"""Bounded, evidence-backed Foundry dependency graph discovery.

The graph deliberately stores intrinsic relations independently from the
direction in which a particular root traverses them.  Every SDK read is also
recorded as immutable operation provenance; collectors never infer coverage
from an empty graph alone.
"""

from __future__ import annotations

import ast
import base64
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from time import monotonic
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from urllib.parse import quote

import requests
from foundry_sdk import FoundryClient
from foundry_sdk import _errors as sdk_errors

from .base import BaseService
from .dataset import DatasetService
from .orchestration import OrchestrationService


SDK_PACKAGE = "foundry-platform-sdk"
METADATA_WALK_MAX_DEPTH = 64
CAPABILITY_IDS = frozenset(f"CAP-{number:02d}" for number in range(1, 17))
ACTION_LOGIC_RULE_TYPES = frozenset(
    {
        "modifyObject",
        "deleteLink",
        "modifyInterface",
        "createOrModifyObject",
        "createObject",
        "createLink",
        "batchedFunction",
        "createOrModifyObjectV2",
        "deleteInterfaceLink",
        "deleteObject",
        "function",
        "createInterfaceLink",
        "createInterface",
        "applyScenario",
    }
)
QUERY_DATA_TYPE_TYPES = frozenset(
    {
        "array",
        "attachment",
        "boolean",
        "date",
        "double",
        "entrySet",
        "float",
        "integer",
        "interfaceObject",
        "interfaceObjectSet",
        "long",
        "mediaReference",
        "null",
        "object",
        "objectSet",
        "set",
        "string",
        "struct",
        "threeDimensionalAggregation",
        "timestamp",
        "twoDimensionalAggregation",
        "typeReference",
        "union",
        "unsupported",
        "void",
    }
)


@dataclass(frozen=True)
class SDKOperationSpec:
    capability_ids: tuple[str, ...]
    branch: bool
    preview: bool
    namespace: str
    method: str

    def __post_init__(self) -> None:
        if not self.capability_ids or not set(self.capability_ids) <= CAPABILITY_IDS:
            raise ValueError("SDK operation must reference valid capability IDs")


SDK_OPERATION_SPECS: dict[str, SDKOperationSpec] = {
    "object-type.get-full-metadata": SDKOperationSpec(
        ("CAP-01", "CAP-16"),
        True,
        True,
        "client.ontologies.Ontology.ObjectType",
        "get_full_metadata",
    ),
    "object-type.get-outgoing-link-type": SDKOperationSpec(
        ("CAP-01", "CAP-16"),
        True,
        False,
        "client.ontologies.Ontology.ObjectType",
        "get_outgoing_link_type",
    ),
    "action-type.get-full-metadata": SDKOperationSpec(
        ("CAP-02", "CAP-16"),
        True,
        True,
        "client.ontologies.ActionTypeFullMetadata",
        "get",
    ),
    "action-type.list-full-metadata": SDKOperationSpec(
        ("CAP-02", "CAP-03", "CAP-13", "CAP-16"),
        True,
        True,
        "client.ontologies.ActionTypeFullMetadata",
        "list",
    ),
    "query-type.list": SDKOperationSpec(
        ("CAP-04", "CAP-05", "CAP-13", "CAP-16"),
        True,
        False,
        "client.ontologies.Ontology.QueryType",
        "list",
    ),
    "dataset.get-schedules": SDKOperationSpec(
        ("CAP-06", "CAP-13", "CAP-16"),
        True,
        False,
        "client.datasets.Dataset",
        "get_schedules",
    ),
    "schedule.get": SDKOperationSpec(
        ("CAP-07", "CAP-16"), False, True, "client.orchestration.Schedule", "get"
    ),
    "schedule.get-affected-resources": SDKOperationSpec(
        ("CAP-07", "CAP-16"),
        False,
        True,
        "client.orchestration.Schedule",
        "get_affected_resources",
    ),
    "schedule.runs": SDKOperationSpec(
        ("CAP-07", "CAP-13", "CAP-16"),
        False,
        False,
        "client.orchestration.Schedule",
        "runs",
    ),
    "build.get": SDKOperationSpec(
        ("CAP-08", "CAP-09", "CAP-16"),
        False,
        False,
        "client.orchestration.Build",
        "get",
    ),
    "build.jobs": SDKOperationSpec(
        ("CAP-08", "CAP-09", "CAP-13", "CAP-16"),
        False,
        False,
        "client.orchestration.Build",
        "jobs",
    ),
    "filesystem.resource.get": SDKOperationSpec(
        ("CAP-10", "CAP-16"), False, False, "client.filesystem.Resource", "get"
    ),
    "third-party-application.get": SDKOperationSpec(
        ("CAP-10", "CAP-16"),
        False,
        True,
        "client.third_party_applications.ThirdPartyApplication",
        "get",
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_id(prefix: str, *values: Any) -> str:
    material = "\x1f".join(str(value) for value in values)
    return f"{prefix}_{sha256(material.encode()).hexdigest()[:24]}"


def _sdk_version() -> str:
    try:
        return version(SDK_PACKAGE)
    except PackageNotFoundError:
        return "unknown"


@dataclass(frozen=True)
class ArgumentObservation:
    mode: str
    value: Optional[str | bool] = None

    def __post_init__(self) -> None:
        if self.mode not in {"explicit", "server-default", "not-applicable"}:
            raise ValueError(f"invalid argument observation mode: {self.mode}")
        if self.mode != "explicit" and self.value is not None:
            raise ValueError("only explicit arguments may carry values")


@dataclass(frozen=True)
class OperationProvenance:
    id: str
    read_context_id: str
    sdk_namespace: str
    sdk_method: str
    capability_ids: tuple[str, ...]
    invocation_sdk_version: str
    invoked_at: str
    observed_at: str
    branch_argument: ArgumentObservation
    preview_argument: ArgumentObservation
    request_timeout_seconds: int
    known_limitations: tuple[dict[str, Any], ...] = ()
    transport: str = "sdk"
    acp_id: Optional[str] = None
    http_verb: Optional[str] = None
    path: Optional[str] = None
    contract_pins: Optional[dict[str, str]] = None
    operation_name: Optional[str] = None
    document_sha256: Optional[str] = None
    request_variables: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ReadContext:
    id: str
    profile: str
    host_fingerprint: str
    invocation_sdk_package: str
    invocation_sdk_version: str
    observed_at: str
    ontology_rid: Optional[str] = None
    requested_branch: Optional[str] = None
    dataset_branch: Optional[str] = None


@dataclass(frozen=True)
class DependencyTarget:
    kind: str
    identifiers: dict[str, str]
    display_name: Optional[str] = None
    node_id: Optional[str] = None


@dataclass(frozen=True)
class Node:
    id: str
    kind: str
    display_name: str
    identifiers: dict[str, str]
    read_context_id: str
    is_target: bool = False


@dataclass(frozen=True)
class Evidence:
    id: str
    operation_provenance_id: str
    locator: str
    field_path: str
    raw_type: str
    response_discriminator: Optional[str] = None


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    target: str
    relation_kind: str
    traversal_class: str
    intrinsic_orientation: str
    evidence_ids: tuple[str, ...]
    coverage: str = "verified"


@dataclass(frozen=True)
class PathStep:
    edge_id: str
    from_node: str
    to_node: str
    traversal_direction: str
    evidence_ids: tuple[str, ...]


@dataclass
class CoverageRecord:
    target_kind: str
    surface: str
    subject_node_id: str
    read_context_id: str
    parent_record_id: Optional[str] = None
    applicability_evidence_id: Optional[str] = None
    status: Optional[str] = None
    attempted: bool = False
    complete: bool = False
    evidence_ids: list[str] = field(default_factory=list)
    error_id: Optional[str] = None
    reason: Optional[str] = None
    operation: Optional[str] = None
    transport: str = "sdk"
    empty_is_inconclusive: bool = False
    reason_code: Optional[str] = None
    positive_control_status: Optional[str] = None
    existence_confirmed: Optional[bool] = None

    @property
    def id(self) -> str:
        return _stable_id(
            "coverage", self.subject_node_id, self.surface, self.read_context_id
        )


@dataclass(frozen=True)
class CoverageGap:
    surface: str
    target: str
    coverage: str
    reason_code: str
    message: str
    read_context_id: str
    retryable: bool
    operation: Optional[str] = None
    budget_snapshot: Optional[dict[str, Any]] = None
    locator: Optional[str] = None

    @property
    def id(self) -> str:
        # The same failure class may occur at several independently actionable
        # locations in one response.  Message is part of the fallback identity
        # for older callers that do not yet provide a structured locator.
        return _stable_id(
            "gap",
            self.target,
            self.surface,
            self.reason_code,
            self.locator or self.message,
            self.read_context_id,
        )


@dataclass(frozen=True)
class ClassifiedFailure:
    error_class: str
    coverage: str
    retryable: bool


class DependencyFatalError(RuntimeError):
    def __init__(
        self,
        error_class: str,
        target: str,
        operation: str,
        message: str,
        retryable: bool,
        read_context_id: str,
    ):
        super().__init__(message)
        self.error_class = error_class
        self.target = target
        self.operation = operation
        self.retryable = retryable
        self.read_context_id = read_context_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_class": self.error_class,
            "target": self.target,
            "operation": self.operation,
            "message": str(self),
            "retryable": self.retryable,
            "read_context_id": self.read_context_id,
        }


class BudgetExhausted(RuntimeError):
    def __init__(self, dimension: str, snapshot: dict[str, Any]):
        super().__init__(f"discovery {dimension} budget exhausted")
        self.dimension = dimension
        self.snapshot = snapshot
        self.partial_action_references: list[tuple[str, str, str, str]] = []
        self.partial_query_leaves: list[tuple[str, str, str]] = []


@dataclass
class DiscoveryBudget:
    max_requests: int = 200
    max_pages: int = 100
    max_items: int = 10_000
    max_nodes: int = 150
    max_depth: int = 2
    time_budget_seconds: float = 60.0
    used_requests: int = 0
    used_pages: int = 0
    used_items: int = 0
    used_nodes: int = 0
    _started_at: float = field(default_factory=monotonic, repr=False)

    HARD_CEILINGS = {
        "max_requests": 1000,
        "max_pages": 500,
        "max_items": 100_000,
        "max_nodes": 1000,
        "max_depth": 10,
        "time_budget_seconds": 600,
    }

    def __post_init__(self) -> None:
        for name, ceiling in self.HARD_CEILINGS.items():
            value = getattr(self, name)
            if value <= 0 or value > ceiling:
                raise ValueError(f"{name} must be between 1 and {ceiling}")

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, monotonic() - self._started_at)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.time_budget_seconds - self.elapsed_seconds)

    def request_timeout(self, configured: float) -> int:
        self._check_time()
        timeout = int(min(float(configured), self.remaining_seconds))
        if timeout < 1:
            raise BudgetExhausted("time", self.snapshot())
        return timeout

    def charge(self, dimension: str, amount: int = 1) -> None:
        self._check_time()
        used_name = f"used_{dimension}"
        limit_name = f"max_{dimension}"
        if not hasattr(self, used_name) or not hasattr(self, limit_name):
            raise ValueError(f"unknown budget dimension: {dimension}")
        if getattr(self, used_name) + amount > getattr(self, limit_name):
            raise BudgetExhausted(dimension, self.snapshot())
        setattr(self, used_name, getattr(self, used_name) + amount)

    def check_depth(self, depth: int) -> None:
        self._check_time()
        if depth > self.max_depth:
            raise BudgetExhausted("depth", self.snapshot())

    def check_metadata_depth(self, depth: int) -> None:
        """Bound nested metadata independently from graph-hop depth."""
        self._check_time()
        if depth > METADATA_WALK_MAX_DEPTH:
            snapshot = self.snapshot()
            snapshot["limits"]["metadata_depth"] = METADATA_WALK_MAX_DEPTH
            raise BudgetExhausted("metadata_depth", snapshot)

    def reserve_page(self, requested_size: int) -> int:
        """Reserve a remote page read and cap it to remaining item capacity."""
        self._check_time()
        # Preserve request-budget precedence from the invocation boundary while
        # ensuring a failed request preflight does not consume a page.
        if self.used_requests >= self.max_requests:
            raise BudgetExhausted("requests", self.snapshot())
        if self.used_pages >= self.max_pages:
            raise BudgetExhausted("pages", self.snapshot())
        remaining_items = self.max_items - self.used_items
        if remaining_items <= 0:
            raise BudgetExhausted("items", self.snapshot())
        self.charge("pages")
        return min(requested_size, remaining_items)

    def _check_time(self) -> None:
        if self.elapsed_seconds >= self.time_budget_seconds:
            raise BudgetExhausted("time", self.snapshot())

    def snapshot(self) -> dict[str, Any]:
        return {
            "used": {
                "requests": self.used_requests,
                "pages": self.used_pages,
                "items": self.used_items,
                "nodes": self.used_nodes,
                "elapsed_seconds": round(self.elapsed_seconds, 6),
            },
            "limits": {
                "requests": self.max_requests,
                "pages": self.max_pages,
                "items": self.max_items,
                "nodes": self.max_nodes,
                "depth": self.max_depth,
                "time_budget_seconds": self.time_budget_seconds,
            },
        }


@dataclass
class AnalysisContext:
    read_context: ReadContext
    budget: DiscoveryBudget
    configured_request_timeout_seconds: float = 30.0
    operation_provenance: dict[str, OperationProvenance] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    coverage_records: dict[str, CoverageRecord] = field(default_factory=dict)
    gaps: dict[str, CoverageGap] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    caches: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    internal_budget: DiscoveryBudget = field(default_factory=DiscoveryBudget)

    @classmethod
    def create(
        cls,
        profile: str = "default",
        host: str = "",
        ontology_rid: Optional[str] = None,
        requested_branch: Optional[str] = None,
        dataset_branch: Optional[str] = None,
        budget: Optional[DiscoveryBudget] = None,
        request_timeout_seconds: float = 30.0,
        internal_budget: Optional[DiscoveryBudget] = None,
    ) -> "AnalysisContext":
        sdk_version = _sdk_version()
        host_fingerprint = (
            sha256(host.rstrip("/").lower().encode()).hexdigest()[:16]
            if host
            else "unknown"
        )
        observed_at = _utc_now()
        context_id = _stable_id(
            "readctx",
            profile,
            host_fingerprint,
            ontology_rid,
            requested_branch,
            dataset_branch,
            SDK_PACKAGE,
            sdk_version,
        )
        read_context = ReadContext(
            context_id,
            profile,
            host_fingerprint,
            SDK_PACKAGE,
            sdk_version,
            observed_at,
            ontology_rid,
            requested_branch,
            dataset_branch,
        )
        return cls(
            read_context,
            budget or DiscoveryBudget(),
            request_timeout_seconds,
            internal_budget=internal_budget or DiscoveryBudget(),
        )


RELATION_KINDS: dict[str, tuple[str, str]] = {
    "action-affects-object": ("dependency-flow", "source_to_target"),
    "action-uses-function": ("dependency-flow", "source_to_target"),
    "query-returns-object": ("dependency-flow", "source_to_target"),
    "query-accepts-object": ("dependency-flow", "source_to_target"),
    "schedule-consumes-resource": ("dependency-flow", "source_to_target"),
    "schedule-produces-resource": ("dependency-flow", "source_to_target"),
    "schedule-triggered-by-resource": ("dependency-flow", "source_to_target"),
    "run-submitted-build": ("dependency-flow", "source_to_target"),
    "schedule-run": ("dependency-flow", "source_to_target"),
    "build-produced-output": ("dependency-flow", "source_to_target"),
    "column-backs-property": ("dependency-flow", "source_to_target"),
    "transform-builds-dataset": ("dependency-flow", "source_to_target"),
    "dataset-feeds-transform": ("dependency-flow", "source_to_target"),
    "code-repo-builds-dataset": ("dependency-flow", "source_to_target"),
    "object-consumed-by-app": ("dependency-flow", "source_to_target"),
    "object-consumed-by-workshop": ("dependency-flow", "source_to_target"),
    "declared-link": ("adjacent-structural", "declared_source_to_target"),
    "container-member": ("adjacent-structural", "container_to_member"),
    "peer": ("adjacent-structural", "peer_canonical"),
    "project-scope": ("adjacent-structural", "container_to_member"),
    "build-co-output": ("adjacent-structural", "peer_canonical"),
}


STATIC_SURFACES = (
    "ontology-structure-backing",
    "full-action-metadata",
    "query-related-function-metadata",
    "dataset-orchestration",
    "application-internals",
    "workshop-internals",
    "compass-metadata",
    "property-column-mapping",
)

OBJECT_TYPE_CONSUMER_SURFACE = "object-type-consumers"
TRANSFORM_DATASET_LINEAGE_SURFACE = "transform-dataset-lineage"

# --- Agent-native impact model (AU2-AU7) -----------------------------------

CHANGE_TYPES = (
    "rename",
    "type-change",
    "optional-to-required",
    "required-to-optional",
    "remove-delete",
    "action-input-change",
    "query-output-change",
)

IMPACT_CATEGORIES = (
    "contract-break",
    "schema-break",
    "semantic-break",
    "runtime-break",
    "workflow-break",
    "governance-risk",
    "unknown",
)

# Base category per relation_kind. Contract-presuming categories only apply to
# downstream dependency-flow paths; upstream variants are remapped by
# IMPACT_CATEGORY_DIRECTION_BASE so a contract category is never assigned to a
# reversed or directionless relationship by the base table alone.
IMPACT_CATEGORY_BASE: dict[str, str] = {
    "action-affects-object": "runtime-break",
    "action-uses-function": "runtime-break",
    "query-returns-object": "contract-break",
    "query-accepts-object": "contract-break",
    "schedule-consumes-resource": "workflow-break",
    "schedule-produces-resource": "workflow-break",
    "schedule-triggered-by-resource": "workflow-break",
    "run-submitted-build": "workflow-break",
    "schedule-run": "workflow-break",
    "build-produced-output": "workflow-break",
    "column-backs-property": "schema-break",
    "transform-builds-dataset": "workflow-break",
    "dataset-feeds-transform": "workflow-break",
    "code-repo-builds-dataset": "workflow-break",
    "object-consumed-by-app": "runtime-break",
    "object-consumed-by-workshop": "workflow-break",
    "declared-link": "schema-break",
    "container-member": "schema-break",
    "peer": "semantic-break",
    "project-scope": "governance-risk",
    "build-co-output": "workflow-break",
}

IMPACT_CATEGORY_DIRECTION_BASE: dict[tuple[str, str], str] = {
    ("query-returns-object", "upstream"): "semantic-break",
    ("query-accepts-object", "upstream"): "semantic-break",
    ("action-affects-object", "upstream"): "workflow-break",
    ("action-uses-function", "upstream"): "workflow-break",
}

# Change-type overrides keyed by (change_type, relation_kind, direction_class).
# Sparse on purpose: a change type only recategorizes the specific
# relation/direction combinations it actually affects; every other combination
# falls back to the direction-aware base tables.
IMPACT_CATEGORY_CHANGE_OVERRIDES: dict[tuple[str, str, str], str] = {
    ("rename", "declared-link", "adjacent"): "contract-break",
    ("rename", "container-member", "adjacent"): "contract-break",
    ("type-change", "query-accepts-object", "downstream"): "contract-break",
    ("type-change", "query-returns-object", "downstream"): "contract-break",
    ("type-change", "declared-link", "adjacent"): "schema-break",
    ("type-change", "container-member", "adjacent"): "schema-break",
    ("optional-to-required", "action-affects-object", "downstream"): "contract-break",
    ("optional-to-required", "query-accepts-object", "downstream"): "contract-break",
    ("required-to-optional", "action-affects-object", "downstream"): "semantic-break",
    ("required-to-optional", "query-accepts-object", "downstream"): "semantic-break",
    ("remove-delete", "declared-link", "adjacent"): "runtime-break",
    ("remove-delete", "container-member", "adjacent"): "runtime-break",
    ("remove-delete", "action-affects-object", "downstream"): "runtime-break",
    ("remove-delete", "query-accepts-object", "downstream"): "runtime-break",
    ("remove-delete", "query-returns-object", "downstream"): "runtime-break",
    ("action-input-change", "action-affects-object", "downstream"): "contract-break",
    ("query-output-change", "query-returns-object", "downstream"): "contract-break",
}

# Deterministic weight tables (no ML, no statistics). Bump the version string
# when weights change so consumers can detect non-comparable scores.
BLAST_RADIUS_WEIGHT_TABLE_VERSION = "blast-radius-weights-v1"
BLAST_RADIUS_WEIGHTS_V1: dict[str, int] = {
    "critical_paths": 10,
    "structural_dependents": 6,
    "indirect_operational_effects": 3,
    "unknown_manual_verification": 2,
}
RELEASE_RISK_WEIGHT_TABLE_VERSION = "release-risk-weights-v1"
RELEASE_RISK_MULTIPLIERS_V1: dict[str, float] = {
    "rename": 1.0,
    "type-change": 1.2,
    "optional-to-required": 1.3,
    "required-to-optional": 0.8,
    "remove-delete": 1.5,
    "action-input-change": 1.2,
    "query-output-change": 1.2,
}

AGENT_SCHEMA_VERSION = "dependency-agent-v1"

MATRIX_GAPS: dict[str, dict[str, str]] = {
    "object-type": {
        "dataset-orchestration": "unsupported-dataset-orchestration",
        "application-internals": "unsupported-application-internals",
        "workshop-internals": "unsupported-workshop-internals",
        "compass-metadata": "ontology-compass-mapping-unavailable",
        "property-column-mapping": "unsupported-property-column-mapping",
        "object-type-consumers": "unsupported-object-type-consumers",
    },
    "property": {
        "dataset-orchestration": "dataset-column-lineage-unavailable",
        "application-internals": "unsupported-application-internals",
        "workshop-internals": "unsupported-workshop-internals",
        "compass-metadata": "ontology-compass-mapping-unavailable",
        # U3a registers this surface, but U4 owns the ACP-04 collector. Keep
        # it terminal and non-blocking until that collector lands rather than
        # promising coverage that no Phase A U2a/U3a code path can complete.
        "property-column-mapping": "unsupported-property-column-mapping",
    },
    "link-type": {
        "dataset-orchestration": "unsupported-dataset-orchestration",
        "application-internals": "unsupported-application-internals",
        "workshop-internals": "unsupported-workshop-internals",
        "compass-metadata": "ontology-compass-mapping-unavailable",
        "property-column-mapping": "unsupported-property-column-mapping",
    },
    "action-type": {
        "dataset-orchestration": "unsupported-dataset-orchestration",
        "application-internals": "unsupported-application-internals",
        "workshop-internals": "unsupported-workshop-internals",
        "compass-metadata": "ontology-compass-mapping-unavailable",
        "property-column-mapping": "unsupported-property-column-mapping",
    },
    "query-type": {
        "dataset-orchestration": "unsupported-dataset-orchestration",
        "application-internals": "unsupported-application-internals",
        "workshop-internals": "unsupported-workshop-internals",
        "compass-metadata": "ontology-compass-mapping-unavailable",
        "property-column-mapping": "unsupported-property-column-mapping",
    },
    "dataset": {
        "ontology-structure-backing": "ontology-backing-mapping-unavailable",
        "full-action-metadata": "reverse-action-mapping-unavailable",
        "query-related-function-metadata": "reverse-query-mapping-unavailable",
        "application-internals": "unsupported-application-internals",
        "workshop-internals": "unsupported-workshop-internals",
        "property-column-mapping": "unsupported-property-column-mapping",
        "transform-dataset-lineage": "unsupported-transform-dataset-lineage",
    },
    "third-party-application": {
        surface: "unsupported-application-internals"
        if surface == "application-internals"
        else "unsupported-resource-surface"
        for surface in STATIC_SURFACES
        if surface != "compass-metadata"
    },
    "workshop-resource": {
        surface: "unsupported-workshop-internals"
        if surface == "workshop-internals"
        else "unsupported-resource-surface"
        for surface in STATIC_SURFACES
        if surface != "compass-metadata"
    },
    "generic-resource": {
        surface: "unknown-resource-capabilities"
        for surface in STATIC_SURFACES
        if surface != "compass-metadata"
    },
}

# Reason codes for gaps that are structurally intentional and static -- every
# value MATRIX_GAPS can ever assign, representing a known, permanent
# limitation of this target kind's surface matrix rather than a live
# collector failure.  Only a gap carrying one of these exact reason codes may
# be treated as an intentional structural/no-edge surface in verification
# routing; a dynamic collector failure (e.g. reason_code=="unsupported" from
# an API-not-found error) never qualifies, even if its coverage also reads
# "unsupported".
STATIC_UNSUPPORTED_GAP_REASONS: frozenset[str] = frozenset(
    reason for surfaces in MATRIX_GAPS.values() for reason in surfaces.values()
)


def classify_exception(error: BaseException) -> ClassifiedFailure:
    chain: list[BaseException] = []
    current: Optional[BaseException] = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    for candidate in chain:
        if getattr(candidate, "name", None) == "BranchNotFound":
            return ClassifiedFailure("branch-not-found", "unresolved", False)
        mapping = (
            (
                (requests.Timeout,),
                ClassifiedFailure("timeout", "partial", True),
            ),
            (
                (requests.ConnectionError,),
                ClassifiedFailure("connection", "partial", True),
            ),
            (
                (sdk_errors.UnauthorizedError, sdk_errors.NotAuthenticated),
                ClassifiedFailure("authentication", "inaccessible", False),
            ),
            (
                (sdk_errors.PermissionDeniedError,),
                ClassifiedFailure("permission-denied", "inaccessible", False),
            ),
            (
                (sdk_errors.NotFoundError,),
                ClassifiedFailure("not-found", "unresolved", False),
            ),
            (
                (sdk_errors.ApiNotFoundError,),
                ClassifiedFailure("unsupported", "unsupported", False),
            ),
            (
                (sdk_errors.RateLimitError, sdk_errors.PalantirQoSException),
                ClassifiedFailure("rate-limited", "partial", True),
            ),
            ((sdk_errors.TimeoutError,), ClassifiedFailure("timeout", "partial", True)),
            (
                (sdk_errors.ConnectionError, sdk_errors.ProxyError),
                ClassifiedFailure("connection", "partial", True),
            ),
            (
                (sdk_errors.BadRequestError, sdk_errors.UnprocessableEntityError),
                ClassifiedFailure("invalid-request", "unresolved", False),
            ),
            (
                (sdk_errors.InternalServerError,),
                ClassifiedFailure("internal", "partial", True),
            ),
        )
        for classes, result in mapping:
            if isinstance(candidate, classes):
                return result
        if isinstance(candidate, sdk_errors.PalantirRPCException):
            return ClassifiedFailure("connection", "partial", True)
        if isinstance(candidate, BudgetExhausted):
            return ClassifiedFailure("budget-exhausted", "budget-exhausted", True)
    return ClassifiedFailure("unknown", "unresolved", False)


def _is_expected_collection_failure(error: BaseException) -> bool:
    """Return whether a failed read is safe to represent as a coverage gap.

    SDK/API failures and an exhausted discovery budget are expected operational
    outcomes.  Python errors are implementation or response-shape invariants;
    allowing those to become an ``unknown`` gap would make a broken collector
    look like a successful partial analysis.
    """

    return classify_exception(error).error_class != "unknown"


class DependencyGraphService(BaseService):
    """Resolve targets and compose bounded collectors into one canonical graph."""

    def __init__(
        self,
        profile: Optional[str] = None,
        client: Optional[FoundryClient] = None,
        conjure_provider: Optional[Any] = None,
    ):
        super().__init__(profile)
        if client is not None:
            self._client = client
        self._conjure_provider = conjure_provider
        internal_client = getattr(conjure_provider, "client", None)
        instance_graphql = (
            vars(internal_client).get("graphql")
            if internal_client is not None and hasattr(internal_client, "__dict__")
            else None
        )
        class_graphql = getattr(type(internal_client), "graphql", None)
        self._graphql_client = (
            internal_client
            if callable(instance_graphql) or callable(class_graphql)
            else None
        )

    def _get_service(self) -> FoundryClient:
        return self.client

    def create_context(
        self,
        *,
        host: str = "",
        ontology_rid: Optional[str] = None,
        requested_branch: Optional[str] = None,
        dataset_branch: Optional[str] = None,
        budget: Optional[DiscoveryBudget] = None,
        request_timeout_seconds: float = 30.0,
        internal_budget: Optional[DiscoveryBudget] = None,
    ) -> AnalysisContext:
        return AnalysisContext.create(
            self.profile or "default",
            host,
            ontology_rid,
            requested_branch,
            dataset_branch,
            budget,
            request_timeout_seconds,
            internal_budget,
        )

    def resolve_object_type(
        self, context: AnalysisContext, ontology_rid: str, object_type: str
    ) -> DependencyTarget:
        return self._resolve_ontology_target(
            context, "object-type", ontology_rid, object_type
        )

    def resolve_property(
        self,
        context: AnalysisContext,
        ontology_rid: str,
        object_type: str,
        property_name: str,
    ) -> DependencyTarget:
        target = self._resolve_ontology_target(
            context, "property", ontology_rid, object_type, property_name
        )
        return target

    def resolve_link_type(
        self,
        context: AnalysisContext,
        ontology_rid: str,
        object_type: str,
        link_type: str,
    ) -> DependencyTarget:
        target = self._resolve_ontology_target(
            context, "link-type", ontology_rid, object_type, link_type
        )
        return target

    def resolve_action_type(
        self, context: AnalysisContext, ontology_rid: str, action_type: str
    ) -> DependencyTarget:
        kwargs = {"ontology": ontology_rid, "action_type": action_type, "preview": True}
        if context.read_context.requested_branch is not None:
            kwargs["branch"] = context.read_context.requested_branch
        metadata, operation_id = self._invoke_sdk(
            context,
            "action-type.get-full-metadata",
            self.client.ontologies.ActionTypeFullMetadata.get,
            kwargs,
            target=action_type,
            fatal=True,
        )
        node = self._add_node(
            context,
            "action-type",
            action_type,
            {"ontology_rid": ontology_rid, "action_type": action_type},
            True,
        )
        context.caches[
            (
                "action-metadata",
                ontology_rid,
                context.read_context.requested_branch,
                action_type,
            )
        ] = (metadata, operation_id)
        return DependencyTarget(
            "action-type", node.identifiers, node.display_name, node.id
        )

    def resolve_query_type(
        self, context: AnalysisContext, ontology_rid: str, query_type: str
    ) -> DependencyTarget:
        try:
            index = self._get_query_index(context, ontology_rid)
        except Exception as error:
            if not _is_expected_collection_failure(error):
                raise
            classified = classify_exception(error)
            raise DependencyFatalError(
                classified.error_class,
                query_type,
                "query-type.list",
                str(error),
                classified.retryable,
                context.read_context.id,
            ) from error
        if (
            query_type not in index["by_name"]
            and index.get("incomplete_error") is not None
        ):
            incomplete_error = index["incomplete_error"]
            classified = classify_exception(incomplete_error)
            raise DependencyFatalError(
                classified.error_class,
                query_type,
                "query-type.list",
                str(incomplete_error),
                classified.retryable,
                context.read_context.id,
            ) from incomplete_error
        if query_type not in index["by_name"]:
            raise DependencyFatalError(
                "not-found",
                query_type,
                "query-type.list",
                f"Query type {query_type} was not found",
                False,
                context.read_context.id,
            )
        query, operation_id = index["by_name"][query_type]
        node = self._add_node(
            context,
            "query-type",
            query_type,
            {"ontology_rid": ontology_rid, "query_type": query_type},
            True,
        )
        context.caches[
            (
                "query-metadata",
                ontology_rid,
                context.read_context.requested_branch,
                query_type,
            )
        ] = (query, operation_id)
        return DependencyTarget(
            "query-type", node.identifiers, node.display_name, node.id
        )

    def resolve_resource(
        self, context: AnalysisContext, resource_rid: str
    ) -> DependencyTarget:
        if not resource_rid.startswith("ri."):
            raise DependencyFatalError(
                "unsupported-addressability",
                resource_rid,
                "filesystem.resource.get",
                "resource targets must be resolvable Foundry RIDs",
                False,
                context.read_context.id,
            )
        resource, operation_id = self._invoke_sdk(
            context,
            "filesystem.resource.get",
            self.client.filesystem.Resource.get,
            {"resource_rid": resource_rid},
            target=resource_rid,
            fatal=True,
        )
        data = self._model_dict(resource)
        resource_type = self._resource_type(data)
        kind = self._resource_kind(resource_type)
        display_name = str(data.get("name") or data.get("display_name") or resource_rid)
        node = self._add_node(
            context,
            kind,
            display_name,
            {"resource_rid": resource_rid, "resource_type": resource_type or "unknown"},
            True,
        )
        self._add_evidence(context, operation_id, "resource", "resource", resource)
        context.caches[("resource", resource_rid)] = data
        return DependencyTarget(kind, node.identifiers, node.display_name, node.id)

    def analyze(
        self,
        target: DependencyTarget | Mapping[str, Any],
        context: AnalysisContext,
        direction: str = "both",
        change: Optional[str] = None,
        change_type: Optional[str] = None,
        compare_artifact: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if direction not in {"both", "upstream", "downstream", "adjacent"}:
            raise ValueError(
                "direction must be both, upstream, downstream, or adjacent"
            )
        target = self._coerce_target(target)
        context.caches[("requested-direction",)] = direction
        if target.node_id is None:
            node = self._add_node(
                context,
                target.kind,
                target.display_name or self._target_label(target),
                target.identifiers,
                True,
            )
            target = replace(target, node_id=node.id)
        self._initialize_matrix(context, target)
        self._discover_bfs(target, context, direction)
        self._complete_coverage(context)
        assert target.node_id is not None
        paths = self._derive_paths(context, target.node_id, direction)
        ranked = self._rank_paths(context, paths, change)
        resolved_change_type, change_type_source = self._resolve_change_type(
            change, change_type
        )
        impacts = self._dedupe_ranked_impacts(context, ranked, resolved_change_type)
        classification = self._classify_agent_results(context, impacts)
        result: dict[str, Any] = {
            "target": asdict(target),
            "read_contexts": [self._serialize(context.read_context)],
            "operation_provenance": [
                self._serialize(value)
                for _, value in sorted(context.operation_provenance.items())
            ],
            "evidence": [
                self._serialize(value) for _, value in sorted(context.evidence.items())
            ],
            "graph": {
                "nodes": [
                    self._serialize(value) for _, value in sorted(context.nodes.items())
                ],
                "edges": [
                    self._serialize(value) for _, value in sorted(context.edges.items())
                ],
            },
            "paths": paths,
            "ranked_relationships": ranked,
            "coverage": [
                self._serialize(value)
                for _, value in sorted(context.coverage_records.items())
            ],
            "gaps": [
                dict(self._serialize(value), id=value.id)
                for _, value in sorted(context.gaps.items())
            ],
            "errors": sorted(context.errors, key=lambda value: str(value)),
            "budget": context.budget.snapshot(),
            "summary": {
                "node_count": len(context.nodes),
                "edge_count": len(context.edges),
                "path_count": len(paths),
                "gap_count": len(context.gaps),
            },
        }
        if change is not None:
            result["change_assessment"] = self._assess_change(
                change, ranked, context, classification
            )
        result["agent"] = self._build_agent_block(
            context,
            target,
            change,
            resolved_change_type,
            change_type_source,
            impacts,
            classification,
            compare_artifact,
        )
        return result

    def _discover_bfs(
        self, target: DependencyTarget, context: AnalysisContext, direction: str
    ) -> None:
        assert target.node_id is not None
        queue: deque[tuple[DependencyTarget, int, tuple[str, ...]]] = deque(
            [(target, 0, ())]
        )
        visited: set[str] = set()
        while queue:
            current, depth, directions = queue.popleft()
            assert current.node_id is not None
            if current.node_id in visited:
                continue
            try:
                context.budget.check_depth(depth)
                self._prepare_frontier_target(current, context)
                self._collect_target(current, context)
            except BudgetExhausted as error:
                context.caches[("budget-exhausted",)] = error
                self._budget_gap(context, current.node_id, "graph-discovery", error)
                self._terminalize_frontier_budget(context, current, error)
                # A global (non-depth) budget dimension stops the whole BFS,
                # not just the branch being processed. Every branch still
                # queued behind `current` never gets its own frontier
                # collection attempted, so it must be terminalized here too
                # -- otherwise it carries no coverage/gap record at all and
                # `_diff_graphs`'s budget-truncation propagation has no seed
                # to expand from, misreporting baseline edges beneath an
                # unvisited branch as real deletions instead of truncation.
                pending_ids: set[str] = set()
                for pending_target, _, _ in queue:
                    if (
                        pending_target.node_id is not None
                        and pending_target.node_id not in visited
                        and pending_target.node_id not in pending_ids
                    ):
                        pending_ids.add(pending_target.node_id)
                        self._terminalize_frontier_budget(
                            context, pending_target, error
                        )
                break
            except Exception as error:
                record = self._coverage_record(
                    context, current.kind, "frontier-collection", current.node_id
                )
                self._record_failure(context, record, error, "frontier-collection")
            visited.add(current.node_id)
            if depth >= context.budget.max_depth:
                undispatched: list[DependencyTarget] = []
                for edge in sorted(context.edges.values(), key=lambda value: value.id):
                    if current.node_id not in {edge.source, edge.target}:
                        continue
                    neighbor_id = (
                        edge.target if current.node_id == edge.source else edge.source
                    )
                    if neighbor_id in visited:
                        continue
                    neighbor = context.nodes[neighbor_id]
                    if neighbor.kind in {
                        "object-type",
                        "property",
                        "link-type",
                        "action-type",
                        "query-type",
                        "dataset",
                        "third-party-application",
                        "workshop-resource",
                        "generic-resource",
                    }:
                        undispatched.append(
                            DependencyTarget(
                                neighbor.kind,
                                neighbor.identifiers,
                                neighbor.display_name,
                                neighbor.id,
                            )
                        )
                if undispatched:
                    budget_error = BudgetExhausted("depth", context.budget.snapshot())
                    context.caches[("budget-exhausted",)] = budget_error
                    self._budget_gap(
                        context, current.node_id, "graph-discovery", budget_error
                    )
                    for frontier_target in undispatched:
                        self._terminalize_frontier_budget(
                            context, frontier_target, budget_error
                        )
                continue
            candidates: list[tuple[str, DependencyTarget, tuple[str, ...]]] = []
            for edge in sorted(context.edges.values(), key=lambda value: value.id):
                if current.node_id not in {edge.source, edge.target}:
                    continue
                neighbor_id = (
                    edge.target if current.node_id == edge.source else edge.source
                )
                if neighbor_id in visited:
                    continue
                step_direction = self._traversal_direction(edge, current.node_id)
                next_directions = directions + (step_direction,)
                if direction in {"upstream", "downstream"}:
                    causal_directions = set(next_directions) - {"adjacent"}
                    opposite = "upstream" if direction == "downstream" else "downstream"
                    if opposite in causal_directions:
                        continue
                neighbor = context.nodes[neighbor_id]
                if neighbor.kind in {
                    "object-type",
                    "property",
                    "link-type",
                    "action-type",
                    "query-type",
                    "dataset",
                    "third-party-application",
                    "workshop-resource",
                    "generic-resource",
                }:
                    candidates.append(
                        (
                            neighbor.id,
                            DependencyTarget(
                                neighbor.kind,
                                neighbor.identifiers,
                                neighbor.display_name,
                                neighbor.id,
                            ),
                            next_directions,
                        )
                    )
            for _, next_target, next_directions in sorted(
                candidates, key=lambda value: value[0]
            ):
                queue.append((next_target, depth + 1, next_directions))

    def _prepare_frontier_target(
        self, target: DependencyTarget, context: AnalysisContext
    ) -> None:
        if target.kind == "action-type":
            key = (
                "action-metadata",
                target.identifiers["ontology_rid"],
                context.read_context.requested_branch,
                target.identifiers["action_type"],
            )
            if key not in context.caches:
                index = self._get_action_index(
                    context, target.identifiers["ontology_rid"]
                )
                if target.identifiers["action_type"] not in index["by_name"]:
                    if index.get("incomplete_error") is not None:
                        raise index["incomplete_error"]
                    raise KeyError(target.identifiers["action_type"])
                context.caches[key] = index["by_name"][
                    target.identifiers["action_type"]
                ]
        elif target.kind == "query-type":
            key = (
                "query-metadata",
                target.identifiers["ontology_rid"],
                context.read_context.requested_branch,
                target.identifiers["query_type"],
            )
            if key not in context.caches:
                index = self._get_query_index(
                    context, target.identifiers["ontology_rid"]
                )
                if target.identifiers["query_type"] not in index["by_name"]:
                    if index.get("incomplete_error") is not None:
                        raise index["incomplete_error"]
                    raise KeyError(target.identifiers["query_type"])
                context.caches[key] = index["by_name"][target.identifiers["query_type"]]
        elif target.kind in {"object-type", "property", "link-type"}:
            object_key = (
                "object-metadata",
                target.identifiers["ontology_rid"],
                target.identifiers["object_type"],
            )
            if object_key not in context.caches:
                kwargs: dict[str, Any] = {
                    "ontology": target.identifiers["ontology_rid"],
                    "object_type": target.identifiers["object_type"],
                    "preview": True,
                }
                if context.read_context.requested_branch is not None:
                    kwargs["branch"] = context.read_context.requested_branch
                context.caches[object_key] = self._invoke_sdk(
                    context,
                    "object-type.get-full-metadata",
                    self.client.ontologies.Ontology.ObjectType.get_full_metadata,
                    kwargs,
                    target=target.identifiers["object_type"],
                )
            if target.kind == "link-type":
                link_key = (
                    "link-metadata",
                    target.identifiers["ontology_rid"],
                    target.identifiers["object_type"],
                    target.identifiers["link_type"],
                )
                if link_key not in context.caches:
                    link_kwargs: dict[str, Any] = {
                        "ontology": target.identifiers["ontology_rid"],
                        "object_type": target.identifiers["object_type"],
                        "link_type": target.identifiers["link_type"],
                    }
                    if context.read_context.requested_branch is not None:
                        link_kwargs["branch"] = context.read_context.requested_branch
                    context.caches[link_key] = self._invoke_sdk(
                        context,
                        "object-type.get-outgoing-link-type",
                        self.client.ontologies.Ontology.ObjectType.get_outgoing_link_type,
                        link_kwargs,
                        target=target.identifiers["link_type"],
                    )

    def _terminalize_frontier_budget(
        self, context: AnalysisContext, target: DependencyTarget, error: BudgetExhausted
    ) -> None:
        self._initialize_matrix(context, target)
        for record in sorted(
            context.coverage_records.values(), key=lambda value: value.id
        ):
            if record.subject_node_id != target.node_id or record.complete:
                continue
            self._finish_coverage(
                record, "budget-exhausted", reason="budget-exhausted", attempted=False
            )
            self._add_gap(
                context,
                target.node_id or "",
                record.surface,
                "budget-exhausted",
                "budget-exhausted",
                str(error),
                retryable=True,
                budget_snapshot=error.snapshot,
            )

    def _invoke_sdk(
        self,
        context: AnalysisContext,
        operation: str,
        call: Callable[..., Any],
        kwargs: Mapping[str, Any],
        *,
        target: str,
        fatal: bool = False,
        known_limitations: Sequence[dict[str, Any]] = (),
    ) -> tuple[Any, str]:
        from .dependency_providers import SdkProvider

        result = SdkProvider(call).invoke(
            context,
            operation,
            kwargs,
            target=target,
            fatal=fatal,
            known_limitations=known_limitations,
        )
        return result.payload, result.operation_provenance_id

    @staticmethod
    def _argument_observation(
        supported: bool, kwargs: Mapping[str, Any], name: str
    ) -> ArgumentObservation:
        if not supported:
            return ArgumentObservation("not-applicable")
        argument_name = (
            "branch_name" if name == "branch" and "branch_name" in kwargs else name
        )
        if argument_name not in kwargs or kwargs[argument_name] is None:
            return ArgumentObservation("server-default")
        return ArgumentObservation("explicit", kwargs[argument_name])

    def _resolve_ontology_target(
        self,
        context: AnalysisContext,
        kind: str,
        ontology_rid: str,
        object_type: str,
        member: Optional[str] = None,
    ) -> DependencyTarget:
        kwargs: dict[str, Any] = {
            "ontology": ontology_rid,
            "object_type": object_type,
            "preview": True,
        }
        if context.read_context.requested_branch is not None:
            kwargs["branch"] = context.read_context.requested_branch
        metadata, operation_id = self._invoke_sdk(
            context,
            "object-type.get-full-metadata",
            self.client.ontologies.Ontology.ObjectType.get_full_metadata,
            kwargs,
            target=member or object_type,
            fatal=True,
        )
        identifiers = {"ontology_rid": ontology_rid, "object_type": object_type}
        label = object_type
        if kind == "property":
            object_model = getattr(metadata, "object_type", None)
            properties = getattr(object_model, "properties", {})
            if member not in properties:
                raise DependencyFatalError(
                    "not-found",
                    member or "",
                    "object-type.get-full-metadata",
                    f"Property {member} was not found on {object_type}",
                    False,
                    context.read_context.id,
                )
            identifiers["property"] = member or ""
            label = f"{object_type}.{member}"
        elif kind == "link-type":
            link_kwargs: dict[str, Any] = {
                "ontology": ontology_rid,
                "object_type": object_type,
                "link_type": member,
            }
            if context.read_context.requested_branch is not None:
                link_kwargs["branch"] = context.read_context.requested_branch
            link, link_operation_id = self._invoke_sdk(
                context,
                "object-type.get-outgoing-link-type",
                self.client.ontologies.Ontology.ObjectType.get_outgoing_link_type,
                link_kwargs,
                target=member or "",
                fatal=True,
            )
            context.caches[("link-metadata", ontology_rid, object_type, member)] = (
                link,
                link_operation_id,
            )
            identifiers["link_type"] = member or ""
            label = member or ""
        node = self._add_node(context, kind, label, identifiers, True)
        context.caches[("object-metadata", ontology_rid, object_type)] = (
            metadata,
            operation_id,
        )
        return DependencyTarget(kind, node.identifiers, node.display_name, node.id)

    @staticmethod
    def _coerce_target(
        target: DependencyTarget | Mapping[str, Any],
    ) -> DependencyTarget:
        if isinstance(target, DependencyTarget):
            return target
        identifiers = target.get("identifiers", {})
        return DependencyTarget(
            str(target["kind"]),
            {str(key): str(value) for key, value in identifiers.items()},
            target.get("display_name"),
            target.get("node_id"),
        )

    @staticmethod
    def _target_label(target: DependencyTarget) -> str:
        return next(reversed(target.identifiers.values()), target.kind)

    def _add_node(
        self,
        context: AnalysisContext,
        kind: str,
        display_name: str,
        identifiers: Mapping[str, str],
        is_target: bool = False,
    ) -> Node:
        normalized = {
            str(key): str(value) for key, value in sorted(identifiers.items())
        }
        identity = normalized
        if kind == "dataset-column":
            dataset_rid = normalized.get("dataset_rid")
            column = normalized.get("column")
            if not dataset_rid or not column:
                raise ValueError("dataset-column requires dataset_rid and column")
            node_id = f"{dataset_rid}#{column}"
        elif "resource_rid" in normalized:
            identity = {"resource_rid": normalized["resource_rid"]}
            node_id = _stable_id(
                "node", kind, *[f"{key}={value}" for key, value in identity.items()]
            )
        else:
            node_id = _stable_id(
                "node", kind, *[f"{key}={value}" for key, value in identity.items()]
            )
        existing = context.nodes.get(node_id)
        if existing is not None:
            if is_target and not existing.is_target:
                existing = replace(existing, is_target=True)
                context.nodes[node_id] = existing
            return existing
        context.budget.charge("nodes")
        node = Node(
            node_id,
            kind,
            str(display_name),
            normalized,
            context.read_context.id,
            is_target,
        )
        context.nodes[node_id] = node
        return node

    def _add_evidence(
        self,
        context: AnalysisContext,
        operation_id: str,
        locator: str,
        field_path: str,
        raw_value: Any,
        discriminator: Optional[str] = None,
    ) -> Evidence:
        raw_type = type(raw_value).__name__
        discriminator = discriminator or getattr(raw_value, "type", None)
        evidence_id = _stable_id(
            "evidence", operation_id, locator, field_path, raw_type, discriminator
        )
        evidence = Evidence(
            evidence_id,
            operation_id,
            locator,
            field_path,
            raw_type,
            str(discriminator) if discriminator is not None else None,
        )
        context.evidence[evidence_id] = evidence
        return evidence

    def _add_edge(
        self,
        context: AnalysisContext,
        source: str,
        target: str,
        relation_kind: str,
        evidence_ids: Iterable[str],
        coverage: str = "verified",
    ) -> Edge:
        if relation_kind not in RELATION_KINDS:
            raise ValueError(f"unregistered relation kind: {relation_kind}")
        traversal_class, orientation = RELATION_KINDS[relation_kind]
        if orientation == "peer_canonical" and target < source:
            source, target = target, source
        edge_id = _stable_id("edge", source, target, relation_kind, orientation)
        evidence = tuple(sorted(set(evidence_ids)))
        existing = context.edges.get(edge_id)
        if existing is not None:
            if (
                existing.traversal_class != traversal_class
                or existing.intrinsic_orientation != orientation
            ):
                raise ValueError("conflicting intrinsic relation definition")
            evidence = tuple(sorted(set(existing.evidence_ids) | set(evidence)))
        edge = Edge(
            edge_id,
            source,
            target,
            relation_kind,
            traversal_class,
            orientation,
            evidence,
            coverage,
        )
        context.edges[edge_id] = edge
        return edge

    def _coverage_record(
        self,
        context: AnalysisContext,
        target_kind: str,
        surface: str,
        subject_node_id: str,
        *,
        parent_record_id: Optional[str] = None,
        applicability_evidence_id: Optional[str] = None,
        operation: Optional[str] = None,
        transport: str = "sdk",
        empty_is_inconclusive: bool = False,
    ) -> CoverageRecord:
        record = CoverageRecord(
            target_kind,
            surface,
            subject_node_id,
            context.read_context.id,
            parent_record_id,
            applicability_evidence_id,
            operation=operation,
            transport=transport,
            empty_is_inconclusive=empty_is_inconclusive,
        )
        existing = context.coverage_records.get(record.id)
        if existing is not None:
            if operation is not None:
                if existing.operation not in {None, operation}:
                    raise ValueError("conflicting coverage operation metadata")
                existing.operation = operation
            if transport != "sdk":
                if existing.transport not in {"sdk", transport}:
                    raise ValueError("conflicting coverage transport metadata")
                existing.transport = transport
            existing.empty_is_inconclusive = (
                existing.empty_is_inconclusive or empty_is_inconclusive
            )
            return existing
        context.coverage_records[record.id] = record
        return record

    def _finish_coverage(
        self,
        record: CoverageRecord,
        status: str,
        *,
        evidence_ids: Iterable[str] = (),
        reason: Optional[str] = None,
        attempted: bool = True,
        reason_code: Optional[str] = None,
        positive_control_status: Optional[str] = None,
        existence_confirmed: Optional[bool] = None,
    ) -> None:
        if status not in {
            "covered",
            "covered-empty",
            "partial",
            "inconclusive",
            "token-expired",
            "inaccessible",
            "unsupported",
            "unresolved",
            "budget-exhausted",
        }:
            raise ValueError(f"invalid coverage status: {status}")
        if status == "covered-empty" and (
            record.transport != "sdk" or record.empty_is_inconclusive
        ):
            sanctioned_acp_01_empty = (
                record.operation == "ACP-01"
                and reason_code == "authoritative-empty-no-producer"
                and positive_control_status == "passed"
                and existence_confirmed is True
            )
            if not sanctioned_acp_01_empty:
                raise ValueError("internal coverage cannot be covered-empty")
        record.status = status
        record.attempted = attempted
        record.complete = True
        record.evidence_ids = sorted(set(record.evidence_ids) | set(evidence_ids))
        record.reason = reason
        record.reason_code = reason_code
        record.positive_control_status = positive_control_status
        record.existence_confirmed = existence_confirmed

    def _add_gap(
        self,
        context: AnalysisContext,
        subject_node_id: str,
        surface: str,
        coverage: str,
        reason_code: str,
        message: str,
        *,
        retryable: bool = False,
        operation: Optional[str] = None,
        budget_snapshot: Optional[dict[str, Any]] = None,
        locator: Optional[str] = None,
    ) -> CoverageGap:
        gap = CoverageGap(
            surface,
            subject_node_id,
            coverage,
            reason_code,
            message,
            context.read_context.id,
            retryable,
            operation,
            budget_snapshot,
            locator,
        )
        context.gaps[gap.id] = gap
        return gap

    def _initialize_matrix(
        self, context: AnalysisContext, target: DependencyTarget
    ) -> None:
        assert target.node_id is not None
        surfaces: tuple[str, ...] = STATIC_SURFACES
        if target.kind == "object-type":
            surfaces = (*surfaces, OBJECT_TYPE_CONSUMER_SURFACE)
        if target.kind == "dataset":
            surfaces = (
                *(
                    surface
                    for surface in STATIC_SURFACES
                    if surface != "dataset-orchestration"
                ),
                TRANSFORM_DATASET_LINEAGE_SURFACE,
            )
            self._coverage_record(
                context, target.kind, "schedule-reverse-index", target.node_id
            )
        for surface in surfaces:
            record = self._coverage_record(
                context, target.kind, surface, target.node_id
            )
            reason = MATRIX_GAPS.get(target.kind, {}).get(surface)
            if (
                self._conjure_provider is not None
                and target.kind in {"object-type", "property"}
                and surface == "property-column-mapping"
            ):
                reason = None
            if (
                self._graphql_client is not None
                and target.kind == "object-type"
                and surface == "object-type-consumers"
            ):
                reason = None
            if (
                self._conjure_provider is not None
                and target.kind == "dataset"
                and surface == TRANSFORM_DATASET_LINEAGE_SURFACE
            ):
                reason = None
            if reason:
                self._finish_coverage(
                    record,
                    "unsupported",
                    reason=reason,
                    attempted=False,
                )
                self._add_gap(
                    context,
                    target.node_id,
                    surface,
                    "unsupported",
                    reason,
                    self._gap_message(reason),
                )
            elif not record.complete:
                self._add_gap(
                    context,
                    target.node_id,
                    surface,
                    "unresolved",
                    "collector-did-not-report",
                    f"The applicable {surface} collector did not report a terminal outcome",
                )

    def _complete_coverage(self, context: AnalysisContext) -> None:
        budget_error = context.caches.get(("budget-exhausted",))
        for record_id, record in sorted(context.coverage_records.items()):
            if record.complete and record.status is not None:
                if record.reason != "collector-did-not-report":
                    self._remove_gaps(
                        context,
                        record.subject_node_id,
                        record.surface,
                        "collector-did-not-report",
                    )
                continue
            status = "budget-exhausted" if budget_error is not None else "unresolved"
            reason = (
                "budget-exhausted"
                if budget_error is not None
                else "collector-did-not-report"
            )
            self._finish_coverage(
                record, status, reason=reason, attempted=record.attempted
            )
            if reason != "collector-did-not-report":
                self._remove_gaps(
                    context,
                    record.subject_node_id,
                    record.surface,
                    "collector-did-not-report",
                )
            self._add_gap(
                context,
                record.subject_node_id,
                record.surface,
                status,
                reason,
                str(budget_error)
                if budget_error is not None
                else f"The applicable {record.surface} collector did not report a terminal outcome",
                retryable=budget_error is not None,
                budget_snapshot=budget_error.snapshot
                if isinstance(budget_error, BudgetExhausted)
                else None,
            )

    @staticmethod
    def _remove_gaps(
        context: AnalysisContext,
        subject_node_id: str,
        surface: str,
        reason_code: str,
    ) -> None:
        for gap_id, gap in list(context.gaps.items()):
            if (
                gap.target == subject_node_id
                and gap.surface == surface
                and gap.reason_code == reason_code
            ):
                context.gaps.pop(gap_id, None)

    @staticmethod
    def _has_reported_gap(
        context: AnalysisContext, subject_node_id: str, surface: str
    ) -> bool:
        return any(
            gap.target == subject_node_id
            and gap.surface == surface
            and gap.reason_code != "collector-did-not-report"
            for gap in context.gaps.values()
        )

    def _budget_gap(
        self,
        context: AnalysisContext,
        node_id: str,
        surface: str,
        error: BudgetExhausted,
    ) -> None:
        record = self._coverage_record(
            context,
            context.nodes.get(
                node_id, Node(node_id, "transit", node_id, {}, context.read_context.id)
            ).kind,
            surface,
            node_id,
        )
        self._finish_coverage(record, "budget-exhausted", reason="budget-exhausted")
        self._add_gap(
            context,
            node_id,
            surface,
            "budget-exhausted",
            "budget-exhausted",
            str(error),
            retryable=True,
            budget_snapshot=error.snapshot,
        )

    @staticmethod
    def _gap_message(reason: str) -> str:
        return reason.replace("-", " ").capitalize()

    def _collect_target(
        self, target: DependencyTarget, context: AnalysisContext
    ) -> None:
        if target.kind in {"object-type", "property", "link-type"}:
            self._collect_ontology_target(target, context)
        elif target.kind == "action-type":
            self._collect_action_target(target, context)
        elif target.kind == "query-type":
            self._collect_query_target(target, context)
        elif target.kind == "dataset":
            self._collect_dataset(target, context)
        elif target.kind in {
            "third-party-application",
            "workshop-resource",
            "generic-resource",
        }:
            self._collect_resource(target, context)
        else:
            raise DependencyFatalError(
                "unsupported-addressability",
                self._target_label(target),
                "target-resolution",
                f"Unsupported dependency target kind: {target.kind}",
                False,
                context.read_context.id,
            )

    def _collect_resource(
        self, target: DependencyTarget, context: AnalysisContext
    ) -> None:
        assert target.node_id is not None
        record = self._coverage_record(
            context, target.kind, "compass-metadata", target.node_id
        )
        evidence = [
            value.id
            for value in context.evidence.values()
            if value.locator == "resource"
        ]
        if target.kind == "third-party-application":
            application_rid = target.identifiers["resource_rid"]
            try:
                application, operation_id = self._invoke_sdk(
                    context,
                    "third-party-application.get",
                    self.client.third_party_applications.ThirdPartyApplication.get,
                    {"third_party_application_rid": application_rid, "preview": True},
                    target=application_rid,
                )
            except Exception as error:
                self._record_failure(
                    context, record, error, "third-party-application.get"
                )
                return
            application_evidence = self._add_evidence(
                context,
                operation_id,
                "thirdPartyApplication",
                "third_party_application",
                application,
            )
            evidence.append(application_evidence.id)
        self._finish_coverage(record, "covered", evidence_ids=evidence)

    def _get_action_index(
        self, context: AnalysisContext, ontology_rid: str
    ) -> dict[str, Any]:
        key = (
            "action-index",
            context.read_context.profile,
            ontology_rid,
            context.read_context.requested_branch,
        )
        if key in context.caches:
            return context.caches[key]
        entries: list[tuple[Any, str]] = []
        page_token: Optional[str] = None
        incomplete_error: Optional[BaseException] = None
        try:
            while True:
                page_size = context.budget.reserve_page(500)
                kwargs: dict[str, Any] = {
                    "ontology": ontology_rid,
                    "preview": True,
                    "page_size": page_size,
                }
                if context.read_context.requested_branch is not None:
                    kwargs["branch"] = context.read_context.requested_branch
                if page_token is not None:
                    kwargs["page_token"] = page_token
                page, operation_id = self._invoke_sdk(
                    context,
                    "action-type.list-full-metadata",
                    self.client.ontologies.ActionTypeFullMetadata.list,
                    kwargs,
                    target=ontology_rid,
                )
                data = list(getattr(page, "data", []))
                for item in data:
                    context.budget.charge("items")
                    entries.append((item, operation_id))
                page_token = getattr(page, "next_page_token", None)
                if not page_token:
                    break
        except Exception as error:
            if not _is_expected_collection_failure(error):
                raise
            incomplete_error = error
        index = {
            "entries": entries,
            "by_name": {
                str(getattr(item.action_type, "api_name", "")): (item, operation_id)
                for item, operation_id in entries
            },
            "incomplete_error": incomplete_error,
        }
        context.caches[key] = index
        return index

    def _get_query_index(
        self, context: AnalysisContext, ontology_rid: str
    ) -> dict[str, Any]:
        key = (
            "query-index",
            context.read_context.profile,
            ontology_rid,
            context.read_context.requested_branch,
        )
        if key in context.caches:
            return context.caches[key]
        entries: list[tuple[Any, str]] = []
        page_token: Optional[str] = None
        incomplete_error: Optional[BaseException] = None
        try:
            while True:
                page_size = context.budget.reserve_page(100)
                kwargs: dict[str, Any] = {
                    "ontology": ontology_rid,
                    "page_size": page_size,
                }
                if context.read_context.requested_branch is not None:
                    kwargs["branch"] = context.read_context.requested_branch
                if page_token is not None:
                    kwargs["page_token"] = page_token
                page, operation_id = self._invoke_sdk(
                    context,
                    "query-type.list",
                    self.client.ontologies.Ontology.QueryType.list,
                    kwargs,
                    target=ontology_rid,
                )
                data = list(getattr(page, "data", []))
                for item in data:
                    context.budget.charge("items")
                    entries.append((item, operation_id))
                page_token = getattr(page, "next_page_token", None)
                if not page_token:
                    break
        except Exception as error:
            if not _is_expected_collection_failure(error):
                raise
            incomplete_error = error
        index = {
            "entries": entries,
            "by_name": {
                str(getattr(item, "api_name", "")): (item, operation_id)
                for item, operation_id in entries
            },
            "incomplete_error": incomplete_error,
        }
        context.caches[key] = index
        return index

    def _collect_ontology_target(
        self, target: DependencyTarget, context: AnalysisContext
    ) -> None:
        assert target.node_id is not None
        ontology_rid = target.identifiers["ontology_rid"]
        object_type = target.identifiers["object_type"]
        metadata, operation_id = context.caches[
            ("object-metadata", ontology_rid, object_type)
        ]
        structure = self._coverage_record(
            context, target.kind, "ontology-structure-backing", target.node_id
        )
        evidence_ids: list[str] = []
        object_node = self._add_node(
            context,
            "object-type",
            object_type,
            {"ontology_rid": ontology_rid, "object_type": object_type},
            target.kind == "object-type",
        )
        if target.kind == "property":
            evidence = self._add_evidence(
                context,
                operation_id,
                f"objectType.properties.{target.identifiers['property']}",
                f"object_type.properties.{target.identifiers['property']}",
                getattr(metadata.object_type, "properties", {})[
                    target.identifiers["property"]
                ],
            )
            evidence_ids.append(evidence.id)
            self._add_edge(
                context,
                object_node.id,
                target.node_id,
                "container-member",
                [evidence.id],
            )
        elif target.kind == "link-type":
            link, link_operation = context.caches[
                (
                    "link-metadata",
                    ontology_rid,
                    object_type,
                    target.identifiers["link_type"],
                )
            ]
            linked_type = str(getattr(link, "object_type_api_name", ""))
            evidence = self._add_evidence(
                context,
                link_operation,
                "linkType.objectTypeApiName",
                "object_type_api_name",
                link,
            )
            evidence_ids.append(evidence.id)
            if linked_type:
                linked_node = self._add_node(
                    context,
                    "object-type",
                    linked_type,
                    {"ontology_rid": ontology_rid, "object_type": linked_type},
                )
                self._add_edge(
                    context,
                    object_node.id,
                    linked_node.id,
                    "declared-link",
                    [evidence.id],
                )
        else:
            for index, interface_name in enumerate(
                getattr(metadata, "implements_interfaces", []) or []
            ):
                context.budget.charge("items")
                evidence = self._add_evidence(
                    context,
                    operation_id,
                    f"implementsInterfaces[{index}]",
                    f"implements_interfaces[{index}]",
                    interface_name,
                )
                evidence_ids.append(evidence.id)
                interface_node = self._add_node(
                    context,
                    "interface-type",
                    str(interface_name),
                    {
                        "ontology_rid": ontology_rid,
                        "interface_type": str(interface_name),
                    },
                )
                self._add_edge(
                    context,
                    interface_node.id,
                    object_node.id,
                    "container-member",
                    [evidence.id],
                )
            for index, link in enumerate(getattr(metadata, "link_types", []) or []):
                context.budget.charge("items")
                linked_name = str(getattr(link, "object_type_api_name", ""))
                if not linked_name:
                    continue
                evidence = self._add_evidence(
                    context,
                    operation_id,
                    f"linkTypes[{index}].objectTypeApiName",
                    f"link_types[{index}].object_type_api_name",
                    link,
                )
                evidence_ids.append(evidence.id)
                linked_node = self._add_node(
                    context,
                    "object-type",
                    linked_name,
                    {"ontology_rid": ontology_rid, "object_type": linked_name},
                )
                self._add_edge(
                    context,
                    object_node.id,
                    linked_node.id,
                    "declared-link",
                    [evidence.id],
                )
        if target.kind in {"object-type", "property"}:
            evidence_ids.extend(
                self._collect_object_interface_mappings(
                    context,
                    target,
                    object_node,
                    metadata,
                    operation_id,
                    ontology_rid,
                    object_type,
                )
            )
        if target.kind in {"object-type", "property"}:
            reason = (
                "object-backing-dataset-mapping-unavailable"
                if target.kind == "object-type"
                else "dataset-column-lineage-unavailable"
            )
            self._finish_coverage(
                structure, "partial", evidence_ids=evidence_ids, reason=reason
            )
            self._add_gap(
                context,
                target.node_id,
                structure.surface,
                "partial",
                reason,
                self._gap_message(reason),
            )
        else:
            self._finish_coverage(
                structure,
                "covered" if evidence_ids else "covered-empty",
                evidence_ids=evidence_ids,
            )
        if target.kind in {"object-type", "property"}:
            self._collect_property_column_mappings(target, context, metadata)
        if target.kind == "object-type":
            self._collect_object_type_consumers(target, context, metadata)
        self._collect_reverse_actions(target, context, ontology_rid)
        self._collect_reverse_queries(target, context, ontology_rid)

    def _collect_object_type_consumers(
        self,
        target: DependencyTarget,
        context: AnalysisContext,
        metadata: Any,
    ) -> None:
        """Collect reverse object-type consumers without treating absence as safety."""

        if self._graphql_client is None:
            return
        assert target.node_id is not None
        from .dependency_internal_specs import (
            GET_OBJECT_TYPE_DEPENDENTS_QUERY,
            GRAPHQL_OPERATION_SPECS,
        )
        from .foundry_internal_client import TokenExpiredError

        spec = GRAPHQL_OPERATION_SPECS["ACP-05"]
        assert spec.operation_name is not None
        assert spec.page_boundary is not None
        record = self._coverage_record(
            context,
            target.kind,
            spec.coverage_surface,
            target.node_id,
            operation=spec.acp_id,
            transport=spec.transport,
            empty_is_inconclusive=spec.empty_is_inconclusive,
        )
        object_type_rid = getattr(getattr(metadata, "object_type", None), "rid", None)
        if not isinstance(object_type_rid, str) or not object_type_rid:
            self._finish_coverage(
                record, "inconclusive", reason="object-type-rid-unavailable"
            )
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "object-type-rid-unavailable",
                "ACP-05 requires the SDK-resolved object type RID",
                operation=spec.acp_id,
                locator="object_type.rid",
            )
            return

        variables = {"rid": object_type_rid}
        try:
            timeout = context.internal_budget.request_timeout(
                context.configured_request_timeout_seconds
            )
            context.internal_budget.charge("requests")
        except BudgetExhausted as error:
            self._finish_coverage(
                record, "inconclusive", reason="internal-budget-exhausted"
            )
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "budget-exhausted",
                str(error),
                retryable=True,
                operation=spec.acp_id,
                budget_snapshot=error.snapshot,
                locator=spec.path,
            )
            return
        invoked_at = _utc_now()
        operation_id = _stable_id(
            "operation",
            context.read_context.id,
            spec.acp_id,
            len(context.operation_provenance),
            invoked_at,
        )
        try:
            response = self._graphql_client.graphql(
                spec.operation_name,
                GET_OBJECT_TYPE_DEPENDENTS_QUERY,
                variables,
                request_timeout=timeout,
            )
        except TokenExpiredError as error:
            self._finish_coverage(record, "token-expired", reason="token-expired")
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "token-expired",
                "token-expired",
                str(error),
                operation=spec.acp_id,
                locator=spec.path,
            )
            return
        except Exception as error:
            if not _is_expected_collection_failure(error):
                raise
            classified = classify_exception(error)
            self._finish_coverage(record, "inconclusive", reason=classified.error_class)
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                classified.error_class,
                f"ACP-05 transport failed: {error}",
                retryable=classified.retryable,
                operation=spec.acp_id,
                locator=spec.path,
            )
            return
        finally:
            context.operation_provenance[operation_id] = OperationProvenance(
                operation_id,
                context.read_context.id,
                "internal",
                spec.operation,
                spec.capability_ids,
                context.read_context.invocation_sdk_version,
                invoked_at,
                _utc_now(),
                ArgumentObservation("not-applicable"),
                ArgumentObservation("not-applicable"),
                timeout,
                (),
                transport=spec.transport,
                acp_id=spec.acp_id,
                http_verb=spec.verb,
                path=spec.path,
                contract_pins=dict(spec.contract_pins),
                operation_name=spec.operation_name,
                document_sha256=spec.document_sha256,
                request_variables=variables,
            )

        if response.errors:
            messages = [
                str(error.get("message"))
                for error in response.errors
                if error.get("message")
            ]
            self._finish_coverage(record, "inconclusive", reason="graphql-errors")
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "graphql-errors",
                "; ".join(messages) or response.reason or "GraphQL response failed",
                operation=spec.acp_id,
                locator="objectTypeV2.dependents",
            )
            return
        if response.status == "inconclusive":
            reason = response.reason or "graphql-response-inconclusive"
            self._finish_coverage(record, "inconclusive", reason=reason)
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                reason,
                "ACP-05 did not return a complete GraphQL response",
                retryable=True,
                operation=spec.acp_id,
                locator="objectTypeV2.dependents",
            )
            return

        data = response.data
        object_type = data.get("objectTypeV2") if isinstance(data, Mapping) else None
        if object_type is None:
            self._finish_coverage(record, "inconclusive", reason="not-found")
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "not-found",
                "ACP-05 returned objectTypeV2: null",
                operation=spec.acp_id,
                locator="objectTypeV2",
            )
            return
        returned_rid = (
            object_type.get("rid") if isinstance(object_type, Mapping) else None
        )
        if returned_rid != object_type_rid:
            self._finish_coverage(record, "inconclusive", reason="response-shape-drift")
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "response-shape-drift",
                "ACP-05 returned a different object type RID",
                operation=spec.acp_id,
                locator="objectTypeV2.rid",
            )
            return
        dependents = (
            object_type.get("dependents") if isinstance(object_type, Mapping) else None
        )
        if not isinstance(dependents, Mapping):
            values = None
        else:
            values = dependents.get("values")
        if (
            not isinstance(dependents, Mapping)
            or not isinstance(values, list)
            or "nextPageToken" not in dependents
        ):
            self._finish_coverage(record, "inconclusive", reason="response-shape-drift")
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "response-shape-drift",
                "ACP-05 omitted dependents.values or dependents.nextPageToken",
                operation=spec.acp_id,
                locator="objectTypeV2.dependents",
            )
            return

        try:
            evidence_ids, unmatched_links, invalid_values = (
                self._emit_object_dependents(
                    context,
                    target,
                    metadata,
                    operation_id,
                    values,
                )
            )
        except BudgetExhausted as error:
            evidence_ids = [
                evidence.id
                for evidence in context.evidence.values()
                if evidence.operation_provenance_id == operation_id
            ]
            budget_reason = (
                "graph-budget-exhausted"
                if error.dimension == "nodes"
                else "internal-budget-exhausted"
            )
            self._finish_coverage(
                record,
                "inconclusive",
                evidence_ids=evidence_ids,
                reason=budget_reason,
            )
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "budget-exhausted",
                str(error),
                retryable=True,
                operation=spec.acp_id,
                budget_snapshot=error.snapshot,
                locator="objectTypeV2.dependents.values",
            )
            return
        truncated = (
            dependents.get("nextPageToken") is not None
            or len(values) == spec.page_boundary
        )
        if truncated:
            self._finish_coverage(
                record,
                "inconclusive",
                evidence_ids=evidence_ids,
                reason="silent-truncation",
            )
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "silent-truncation",
                "ACP-05 dependents may be silently truncated",
                operation=spec.acp_id,
                locator="objectTypeV2.dependents",
            )
        elif unmatched_links or invalid_values:
            self._finish_coverage(
                record,
                "inconclusive",
                evidence_ids=evidence_ids,
                reason="response-shape-drift",
            )
            for locator in [*unmatched_links, *invalid_values]:
                self._add_gap(
                    context,
                    target.node_id,
                    spec.coverage_surface,
                    "inconclusive",
                    "response-shape-drift",
                    "ACP-05 dependent could not be matched to a typed consumer edge",
                    operation=spec.acp_id,
                    locator=locator,
                )
        elif not values:
            self._finish_coverage(
                record, "inconclusive", reason="endpoint-empty-inconclusive"
            )
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "endpoint-empty-inconclusive",
                "ACP-05 returned no dependents; absence could not be proven",
                operation=spec.acp_id,
                locator="objectTypeV2.dependents.values",
            )
        else:
            self._finish_coverage(record, "covered", evidence_ids=evidence_ids)

        self._corroborate_object_consumers_with_monocle(
            context, target, metadata, object_type_rid
        )

    def _emit_object_dependents(
        self,
        context: AnalysisContext,
        target: DependencyTarget,
        metadata: Any,
        operation_id: str,
        values: Sequence[Any],
    ) -> tuple[list[str], list[str], list[str]]:
        assert target.node_id is not None
        link_targets = {
            str(getattr(link, "link_type_rid", "")): str(
                getattr(link, "object_type_api_name", "")
            )
            for link in (getattr(metadata, "link_types", None) or [])
            if getattr(link, "link_type_rid", None)
            and getattr(link, "object_type_api_name", None)
        }
        evidence_ids: list[str] = []
        unmatched_links: list[str] = []
        invalid_values: list[str] = []
        for index, dependent in enumerate(values):
            context.internal_budget.charge("items")
            locator = f"objectTypeV2.dependents.values[{index}]"
            if not isinstance(dependent, Mapping):
                invalid_values.append(locator)
                continue
            rid = dependent.get("rid")
            type_metadata = dependent.get("type")
            type_name = (
                type_metadata.get("name")
                if isinstance(type_metadata, Mapping)
                else None
            )
            if not isinstance(rid, str) or not rid or not isinstance(type_name, str):
                invalid_values.append(locator)
                continue
            evidence = self._add_evidence(
                context,
                operation_id,
                locator,
                locator,
                dependent,
                discriminator=type_name,
            )
            evidence_ids.append(evidence.id)
            if type_name == "Module":
                consumer = self._add_consumer_node(
                    context, "workshop-module", rid, dependent
                )
                self._add_edge(
                    context,
                    target.node_id,
                    consumer.id,
                    "object-consumed-by-workshop",
                    [evidence.id],
                )
            elif rid.startswith("ri.third-party-applications.main.application."):
                consumer = self._add_consumer_node(
                    context, "application", rid, dependent
                )
                self._add_edge(
                    context,
                    target.node_id,
                    consumer.id,
                    "object-consumed-by-app",
                    [evidence.id],
                )
            elif type_name == "Link type":
                linked_name = link_targets.get(rid)
                if linked_name is None:
                    unmatched_links.append(locator)
                    continue
                linked_node = self._add_node(
                    context,
                    "object-type",
                    linked_name,
                    {
                        "ontology_rid": target.identifiers["ontology_rid"],
                        "object_type": linked_name,
                    },
                )
                self._add_edge(
                    context,
                    target.node_id,
                    linked_node.id,
                    "declared-link",
                    [evidence.id],
                )
            else:
                invalid_values.append(locator)
        return evidence_ids, unmatched_links, invalid_values

    def _add_consumer_node(
        self,
        context: AnalysisContext,
        kind: str,
        rid: str,
        dependent: Mapping[str, Any],
    ) -> Node:
        identifiers = {"resource_rid": rid}
        for source, destination in (
            ("path", "path"),
            ("description", "description"),
            ("projectRid", "project_rid"),
        ):
            value = dependent.get(source)
            if isinstance(value, str):
                identifiers[destination] = value
        parent = dependent.get("parent")
        if isinstance(parent, Mapping):
            for source, destination in (
                ("rid", "parent_rid"),
                ("name", "parent_name"),
                ("path", "parent_path"),
            ):
                value = parent.get(source)
                if isinstance(value, str):
                    identifiers[destination] = value
        display_name = dependent.get("name")
        return self._add_node(
            context,
            kind,
            display_name if isinstance(display_name, str) and display_name else rid,
            identifiers,
        )

    def _corroborate_object_consumers_with_monocle(
        self,
        context: AnalysisContext,
        target: DependencyTarget,
        metadata: Any,
        object_type_rid: str,
    ) -> None:
        """Merge V3 monocle evidence only onto edges already proven elsewhere."""

        if self._conjure_provider is None:
            return
        assert target.node_id is not None
        from .dependency_internal_specs import CONJURE_POST_OPERATION_SPECS

        spec = CONJURE_POST_OPERATION_SPECS["ACP-06"]
        branch = context.read_context.requested_branch or "master"
        body = {
            "resourceIdentifiers": [object_type_rid],
            "branch": {
                "type": "legacyBranch",
                "legacyBranch": {"branch": branch, "fallbacks": []},
            },
            "serviceTypeFilter": [],
        }
        try:
            result = self._invoke_conjure_post(context, spec, body)
        except BudgetExhausted:
            return
        if result is None:
            return
        payload, operation_id = result
        nodes = payload.get("nodes")
        if not isinstance(nodes, list):
            return
        node_by_rid = {
            node.identifiers.get("resource_rid"): node
            for node in context.nodes.values()
            if node.identifiers.get("resource_rid")
        }
        existing_by_target = {
            edge.target: edge
            for edge in context.edges.values()
            if edge.source == target.node_id
            and edge.relation_kind
            in {
                "declared-link",
                "object-consumed-by-app",
                "object-consumed-by-workshop",
            }
        }
        declared_by_link_rid: dict[str, Edge] = {}
        for link in getattr(metadata, "link_types", None) or []:
            link_rid = getattr(link, "link_type_rid", None)
            linked_name = getattr(link, "object_type_api_name", None)
            if not isinstance(link_rid, str) or not isinstance(linked_name, str):
                continue
            linked_node = next(
                (
                    node
                    for node in context.nodes.values()
                    if node.kind == "object-type"
                    and node.identifiers.get("object_type") == linked_name
                ),
                None,
            )
            if linked_node is None:
                continue
            edge = existing_by_target.get(linked_node.id)
            if edge is not None and edge.relation_kind == "declared-link":
                declared_by_link_rid[link_rid] = edge
        for node_index, node_payload in enumerate(nodes):
            if not isinstance(node_payload, Mapping):
                continue
            if node_payload.get("resourceIdentifier") != object_type_rid:
                continue
            links = node_payload.get("links")
            if not isinstance(links, list):
                continue
            for link_index, link in enumerate(links):
                link_rid = self._monocle_link_id(link)
                existing = (
                    declared_by_link_rid.get(link_rid) if link_rid is not None else None
                )
                if existing is None:
                    neighbor_rid = self._monocle_neighbor_rid(link)
                    consumer_node = node_by_rid.get(neighbor_rid)
                    if consumer_node is None:
                        continue
                    existing = existing_by_target.get(consumer_node.id)
                    if existing is None:
                        continue
                locator = f"nodes[{node_index}].links[{link_index}]"
                evidence = self._add_evidence(
                    context,
                    operation_id,
                    locator,
                    locator,
                    link,
                    discriminator=link.get("type")
                    if isinstance(link, Mapping)
                    else None,
                )
                self._add_edge(
                    context,
                    existing.source,
                    existing.target,
                    existing.relation_kind,
                    [evidence.id],
                    coverage=existing.coverage,
                )

    def _invoke_conjure_post(
        self,
        context: AnalysisContext,
        spec: Any,
        body: Mapping[str, Any],
        *,
        raise_token_expired: bool = False,
    ) -> Optional[tuple[Mapping[str, Any], str]]:
        """Invoke one registered read-via-POST operation without widening GET-only ACP."""

        from .dependency_providers import ResultSemantics, classify_conjure_response
        from .foundry_internal_client import TokenExpiredError

        if spec.verb != "POST":
            raise ValueError(f"{spec.acp_id} is not a POST operation")
        internal_client = getattr(self._conjure_provider, "client", None)
        conjure = getattr(internal_client, "conjure", None)
        if not callable(conjure):
            return None
        timeout = context.internal_budget.request_timeout(
            context.configured_request_timeout_seconds
        )
        context.internal_budget.charge("requests")
        invoked_at = _utc_now()
        operation_id = _stable_id(
            "operation",
            context.read_context.id,
            spec.acp_id,
            len(context.operation_provenance),
            invoked_at,
        )
        try:
            response = conjure(
                spec.verb,
                spec.path,
                json_body=body,
                expected=None,
                request_timeout=timeout,
            )
        except TokenExpiredError:
            if raise_token_expired:
                raise
            return None
        except Exception as error:
            if not _is_expected_collection_failure(error):
                raise
            return None
        finally:
            context.operation_provenance[operation_id] = OperationProvenance(
                operation_id,
                context.read_context.id,
                "internal",
                spec.operation,
                spec.capability_ids,
                context.read_context.invocation_sdk_version,
                invoked_at,
                _utc_now(),
                ArgumentObservation("not-applicable"),
                ArgumentObservation("not-applicable"),
                timeout,
                (),
                transport=spec.transport,
                acp_id=spec.acp_id,
                http_verb=spec.verb,
                path=spec.path,
                contract_pins=dict(spec.contract_pins),
            )
        if not isinstance(response, tuple) or len(response) != 3:
            return None
        status, payload, raw = response
        if (
            raise_token_expired
            and isinstance(status, int)
            and classify_conjure_response(status, payload).coverage == "token-expired"
        ):
            raise TokenExpiredError(raw)
        if (
            not isinstance(status, int)
            or not 200 <= status < 300
            or ResultSemantics(spec, response) != "ok"
            or not isinstance(payload, Mapping)
        ):
            return None
        return payload, operation_id

    def _invoke_transform_lineage_get(
        self,
        context: AnalysisContext,
        spec: Any,
        path: str,
        *,
        target: str,
    ) -> Any:
        """Invoke a Phase B GET without widening the Phase A ACP registry."""

        from .dependency_providers import (
            ProviderResult,
            ResultSemantics,
            classify_conjure_response,
        )

        if spec.verb != "GET":
            raise ValueError(f"{spec.acp_id} is not a GET operation")
        provider = self._conjure_provider
        internal_client = getattr(provider, "client", None)
        conjure = getattr(internal_client, "conjure", None)
        if not callable(conjure):
            if provider is None:
                raise ValueError("internal provider is not configured")
            return provider.invoke(
                context,
                spec.acp_id,
                spec.verb,
                path,
                None,
                target=target,
            )

        timeout = context.internal_budget.request_timeout(
            context.configured_request_timeout_seconds
        )
        context.internal_budget.charge("requests")
        invoked_at = _utc_now()
        operation_id = _stable_id(
            "operation",
            context.read_context.id,
            spec.acp_id,
            len(context.operation_provenance),
            invoked_at,
        )
        try:
            response = conjure(
                spec.verb,
                path,
                json_body=None,
                expected=None,
                request_timeout=timeout,
            )
        except Exception as error:
            if not _is_expected_collection_failure(error):
                raise
            transport_failure = classify_exception(error)
            gap = CoverageGap(
                spec.coverage_surface,
                target,
                transport_failure.coverage,
                transport_failure.error_class,
                f"{spec.acp_id} transport failed: {error}",
                context.read_context.id,
                transport_failure.retryable,
                spec.acp_id,
                None,
                path,
            )
            context.gaps[gap.id] = gap
            return ProviderResult(
                None,
                operation_id,
                None,
                "not-run",
                transport_failure.coverage,
                transport_failure.error_class,
                transport_failure.retryable,
                str(error),
            )
        finally:
            context.operation_provenance[operation_id] = OperationProvenance(
                operation_id,
                context.read_context.id,
                "internal",
                spec.operation,
                spec.capability_ids,
                context.read_context.invocation_sdk_version,
                invoked_at,
                _utc_now(),
                ArgumentObservation("not-applicable"),
                ArgumentObservation("not-applicable"),
                timeout,
                (),
                transport=spec.transport,
                acp_id=spec.acp_id,
                http_verb=spec.verb,
                path=path,
                contract_pins=dict(spec.contract_pins),
            )

        status, payload, raw = response
        semantics = ResultSemantics(spec, response)
        classified = classify_conjure_response(status, payload)
        if 200 <= status < 300:
            coverage_status = (
                "inconclusive"
                if semantics
                in {"empty", "truncated", "shape-drift", "permission-ambiguous"}
                else classified.coverage
            )
        else:
            coverage_status = classified.coverage
        error_class = classified.error_class if classified.error_class != "ok" else None
        if semantics == "shape-drift" and 200 <= status < 300:
            error_class = "response-shape-drift"
        if coverage_status not in {"covered", "token-expired"}:
            reason_code = error_class or f"{semantics}-internal-response"
            gap = CoverageGap(
                spec.coverage_surface,
                target,
                coverage_status,
                reason_code,
                f"{spec.acp_id} returned {semantics}; absence could not be proven",
                context.read_context.id,
                classified.retryable,
                spec.acp_id,
                None,
                path,
            )
            context.gaps[gap.id] = gap
        return ProviderResult(
            payload,
            operation_id,
            semantics,
            "not-run",
            coverage_status,
            error_class,
            classified.retryable,
            raw,
        )

    @staticmethod
    def _monocle_neighbor_rid(link: Any) -> Optional[str]:
        if not isinstance(link, Mapping):
            return None
        discriminator = link.get("type")
        payload = link.get(discriminator) if isinstance(discriminator, str) else None
        if not isinstance(payload, Mapping):
            return None
        for rid_field in ("resourceIdentifier", "objectTypeId"):
            value = payload.get(rid_field)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _monocle_link_id(link: Any) -> Optional[str]:
        if not isinstance(link, Mapping):
            return None
        discriminator = link.get("type")
        payload = link.get(discriminator) if isinstance(discriminator, str) else None
        if not isinstance(payload, Mapping):
            return None
        value = payload.get("linkId")
        return value if isinstance(value, str) and value else None

    def _collect_property_column_mappings(
        self,
        target: DependencyTarget,
        context: AnalysisContext,
        metadata: Any,
    ) -> None:
        """Augment SDK ontology structure with ACP-04 physical column edges."""

        if self._conjure_provider is None:
            return
        assert target.node_id is not None
        from .dependency_internal_specs import ACP_OPERATION_SPECS
        from .foundry_internal_client import TokenExpiredError

        spec = ACP_OPERATION_SPECS["ACP-04"]
        record = self._coverage_record(
            context,
            target.kind,
            spec.coverage_surface,
            target.node_id,
            operation=spec.acp_id,
            transport=spec.transport,
            empty_is_inconclusive=spec.empty_is_inconclusive,
        )
        path = spec.path.format(
            ontology=target.identifiers["ontology_rid"],
            object_type=target.identifiers["object_type"],
        )
        cache_key = (
            spec.acp_id,
            target.identifiers["ontology_rid"],
            target.identifiers["object_type"],
        )
        try:
            cached = context.caches.get(cache_key)
            if isinstance(cached, BaseException):
                raise cached
            if cached is None:
                result = self._conjure_provider.invoke(
                    context,
                    spec.acp_id,
                    spec.verb,
                    path,
                    None,
                    target=target.node_id,
                )
                context.caches[cache_key] = result
            else:
                result = cached
        except TokenExpiredError as error:
            context.caches[cache_key] = error
            self._finish_coverage(record, "token-expired", reason="token-expired")
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "token-expired",
                "token-expired",
                str(error),
                operation=spec.acp_id,
                locator=path,
            )
            return

        shape_drift_payload = (
            result.coverage_status == "inconclusive"
            and result.error_class == "response-shape-drift"
            and isinstance(result.payload, Mapping)
        )
        if result.coverage_status != "covered" and not shape_drift_payload:
            reason = (
                result.error_class or f"{result.result_semantics}-internal-response"
            )
            self._finish_coverage(record, result.coverage_status, reason=reason)
            if not self._has_reported_gap(
                context, target.node_id, spec.coverage_surface
            ):
                self._add_gap(
                    context,
                    target.node_id,
                    spec.coverage_surface,
                    result.coverage_status,
                    reason,
                    f"{spec.acp_id} returned {result.result_semantics}; "
                    "absence could not be proven",
                    retryable=result.retryable,
                    operation=spec.acp_id,
                    locator=path,
                )
            return

        payload = result.payload
        datasources = (
            payload.get("datasources", []) if isinstance(payload, Mapping) else []
        )
        sdk_properties = getattr(
            getattr(metadata, "object_type", None), "properties", {}
        )
        property_names = (
            (target.identifiers["property"],)
            if target.kind == "property"
            else tuple(sorted(str(name) for name in sdk_properties))
        )
        evidence_ids: list[str] = []
        shape_drift_locators: list[str] = []
        for index, datasource in enumerate(datasources):
            if not isinstance(datasource, Mapping):
                continue
            definition = datasource.get("definition")
            if (
                not isinstance(definition, Mapping)
                or definition.get("type") != "dataset"
            ):
                continue
            dataset_rid = definition.get("datasetRid")
            property_mapping = definition.get("propertyMapping")
            base_locator = f"datasources[{index}].definition"
            if not isinstance(dataset_rid, str) or not dataset_rid:
                shape_drift_locators.append(f"{base_locator}.datasetRid")
                continue
            if not isinstance(property_mapping, Mapping):
                shape_drift_locators.append(f"{base_locator}.propertyMapping")
                continue
            for property_name in property_names:
                mapping = property_mapping.get(property_name)
                if mapping is None:
                    continue
                locator = f"{base_locator}.propertyMapping.{property_name}"
                if (
                    not isinstance(mapping, Mapping)
                    or mapping.get("type") != "column"
                    or not isinstance(mapping.get("column"), str)
                    or not mapping["column"]
                ):
                    shape_drift_locators.append(locator)
                    continue
                property_node = (
                    context.nodes[target.node_id]
                    if target.kind == "property"
                    else self._add_node(
                        context,
                        "property",
                        f"{target.identifiers['object_type']}.{property_name}",
                        {
                            "ontology_rid": target.identifiers["ontology_rid"],
                            "object_type": target.identifiers["object_type"],
                            "property": property_name,
                        },
                    )
                )
                column = str(mapping["column"])
                column_node = self._add_node(
                    context,
                    "dataset-column",
                    column,
                    {"dataset_rid": dataset_rid, "column": column},
                )
                evidence = self._add_evidence(
                    context,
                    result.operation_provenance_id,
                    locator,
                    locator,
                    mapping,
                    discriminator="column",
                )
                evidence_ids.append(evidence.id)
                self._add_edge(
                    context,
                    column_node.id,
                    property_node.id,
                    "column-backs-property",
                    [evidence.id],
                )

        if shape_drift_locators:
            self._finish_coverage(
                record,
                "inconclusive",
                evidence_ids=evidence_ids,
                reason="response-shape-drift",
            )
            for locator in shape_drift_locators:
                self._add_gap(
                    context,
                    target.node_id,
                    spec.coverage_surface,
                    "inconclusive",
                    "response-shape-drift",
                    "ACP-04 dataset mapping omitted a required discriminator",
                    operation=spec.acp_id,
                    locator=locator,
                )
            return
        if not evidence_ids:
            self._finish_coverage(
                record,
                "inconclusive",
                reason="property-mapping-not-found",
            )
            self._add_gap(
                context,
                target.node_id,
                spec.coverage_surface,
                "inconclusive",
                "property-mapping-not-found",
                "ACP-04 returned no physical column mapping for the SDK-resolved property",
                operation=spec.acp_id,
                locator="datasources",
            )
            return
        self._finish_coverage(record, "covered", evidence_ids=evidence_ids)

    def _collect_object_interface_mappings(
        self,
        context: AnalysisContext,
        target: DependencyTarget,
        object_node: Node,
        metadata: Any,
        operation_id: str,
        ontology_rid: str,
        object_type: str,
    ) -> list[str]:
        """Collect the richer interface and shared-property metadata surfaces."""

        assert target.node_id is not None
        evidence_ids: list[str] = []
        implementations = getattr(metadata, "implements_interfaces2", None)
        shared_mapping = getattr(metadata, "shared_property_type_mapping", None)
        for field_name, value in (
            ("implementsInterfaces2", implementations),
            ("sharedPropertyTypeMapping", shared_mapping),
        ):
            if not isinstance(value, Mapping):
                self._add_gap(
                    context,
                    target.node_id,
                    "ontology-structure-backing",
                    "unresolved",
                    f"invalid-{field_name}",
                    f"Object metadata field {field_name} is absent or malformed",
                    locator=field_name,
                )

        if isinstance(implementations, Mapping):
            for interface_name, implementation in sorted(
                implementations.items(), key=lambda pair: str(pair[0])
            ):
                context.budget.charge("items")
                locator = f"implementsInterfaces2.{interface_name}"
                evidence = self._add_evidence(
                    context, operation_id, locator, locator, implementation
                )
                evidence_ids.append(evidence.id)
                interface_node = self._add_node(
                    context,
                    "interface-type",
                    str(interface_name),
                    {
                        "ontology_rid": ontology_rid,
                        "interface_type": str(interface_name),
                    },
                )
                self._add_edge(
                    context,
                    interface_node.id,
                    object_node.id,
                    "container-member",
                    [evidence.id],
                )
                properties = getattr(implementation, "properties", None)
                properties_v2 = getattr(implementation, "properties_v2", None)
                links = getattr(implementation, "links", None)
                if not isinstance(properties, Mapping):
                    self._add_gap(
                        context,
                        target.node_id,
                        "ontology-structure-backing",
                        "unresolved",
                        "invalid-interface-property-mapping",
                        f"Interface property mapping is malformed at {locator}.properties",
                        locator=f"{locator}.properties",
                    )
                else:
                    for shared_name, property_name in sorted(
                        properties.items(), key=lambda pair: str(pair[0])
                    ):
                        context.budget.charge("items")
                        mapping_locator = f"{locator}.properties.{shared_name}"
                        mapping_evidence = self._add_evidence(
                            context,
                            operation_id,
                            mapping_locator,
                            mapping_locator,
                            property_name,
                        )
                        evidence_ids.append(mapping_evidence.id)
                        self._add_property_mapping_edge(
                            context,
                            ontology_rid,
                            object_type,
                            str(shared_name),
                            str(property_name),
                            mapping_evidence.id,
                        )
                if not isinstance(properties_v2, Mapping):
                    self._add_gap(
                        context,
                        target.node_id,
                        "ontology-structure-backing",
                        "unresolved",
                        "invalid-interface-property-v2-mapping",
                        f"Interface property V2 mapping is malformed at {locator}.propertiesV2",
                        locator=f"{locator}.propertiesV2",
                    )
                else:
                    for interface_property, property_implementation in sorted(
                        properties_v2.items(), key=lambda pair: str(pair[0])
                    ):
                        context.budget.charge("items")
                        evidence_ids.extend(
                            self._collect_interface_property_v2_implementation(
                                context,
                                target.node_id,
                                operation_id,
                                ontology_rid,
                                object_type,
                                str(interface_name),
                                str(interface_property),
                                property_implementation,
                                f"{locator}.propertiesV2.{interface_property}",
                            )
                        )
                if not isinstance(links, Mapping):
                    self._add_gap(
                        context,
                        target.node_id,
                        "ontology-structure-backing",
                        "unresolved",
                        "invalid-interface-link-mapping",
                        f"Interface link mapping is malformed at {locator}.links",
                        locator=f"{locator}.links",
                    )
                else:
                    for interface_link, local_links in sorted(
                        links.items(), key=lambda pair: str(pair[0])
                    ):
                        context.budget.charge("items")
                        if not isinstance(local_links, Sequence) or isinstance(
                            local_links, (str, bytes)
                        ):
                            self._add_gap(
                                context,
                                target.node_id,
                                "ontology-structure-backing",
                                "unresolved",
                                "invalid-interface-link-mapping",
                                f"Interface link mapping is malformed at {locator}.links.{interface_link}",
                                locator=f"{locator}.links.{interface_link}",
                            )
                            continue
                        interface_link_node = self._add_node(
                            context,
                            "interface-link-type",
                            str(interface_link),
                            {
                                "ontology_rid": ontology_rid,
                                "interface_type": str(interface_name),
                                "interface_link_type": str(interface_link),
                            },
                        )
                        for index, local_link in enumerate(local_links):
                            context.budget.charge("items")
                            link_locator = f"{locator}.links.{interface_link}[{index}]"
                            link_evidence = self._add_evidence(
                                context,
                                operation_id,
                                link_locator,
                                link_locator,
                                local_link,
                            )
                            evidence_ids.append(link_evidence.id)
                            local_link_node = self._add_node(
                                context,
                                "link-type",
                                str(local_link),
                                {
                                    "ontology_rid": ontology_rid,
                                    "object_type": object_type,
                                    "link_type": str(local_link),
                                },
                            )
                            self._add_edge(
                                context,
                                interface_link_node.id,
                                local_link_node.id,
                                "container-member",
                                [link_evidence.id],
                            )

        if isinstance(shared_mapping, Mapping):
            for shared_name, property_name in sorted(
                shared_mapping.items(), key=lambda pair: str(pair[0])
            ):
                context.budget.charge("items")
                locator = f"sharedPropertyTypeMapping.{shared_name}"
                evidence = self._add_evidence(
                    context, operation_id, locator, locator, property_name
                )
                evidence_ids.append(evidence.id)
                self._add_property_mapping_edge(
                    context,
                    ontology_rid,
                    object_type,
                    str(shared_name),
                    str(property_name),
                    evidence.id,
                )
        return evidence_ids

    def _collect_interface_property_v2_implementation(
        self,
        context: AnalysisContext,
        target_node_id: str,
        operation_id: str,
        ontology_rid: str,
        object_type: str,
        interface_type: str,
        interface_property: str,
        implementation: Any,
        locator: str,
        *,
        _seen: Optional[set[int]] = None,
    ) -> list[str]:
        """Materialize every supported local property reachable from propertiesV2."""

        seen = _seen if _seen is not None else set()
        identity = id(implementation)
        if identity in seen:
            self._add_gap(
                context,
                target_node_id,
                "ontology-structure-backing",
                "unresolved",
                "cyclic-interface-property-v2-implementation",
                f"Interface property implementation is cyclic at {locator}",
                locator=locator,
            )
            return []
        seen.add(identity)

        def field(name: str) -> Any:
            if isinstance(implementation, Mapping):
                return implementation.get(name)
            return getattr(implementation, name, None)

        discriminator = field("type")
        evidence_ids: list[str] = []

        def emit_property(property_name: Any, evidence_locator: str, raw: Any) -> None:
            if property_name is None or str(property_name) == "":
                self._add_gap(
                    context,
                    target_node_id,
                    "ontology-structure-backing",
                    "unresolved",
                    "invalid-interface-property-v2-implementation",
                    f"Interface property implementation has no backing property at {evidence_locator}",
                    locator=evidence_locator,
                )
                return
            evidence = self._add_evidence(
                context,
                operation_id,
                evidence_locator,
                evidence_locator,
                raw,
                str(discriminator) if discriminator is not None else None,
            )
            evidence_ids.append(evidence.id)
            self._add_interface_property_mapping_edge(
                context,
                ontology_rid,
                object_type,
                interface_type,
                interface_property,
                str(property_name),
                evidence.id,
            )

        if discriminator == "localPropertyImplementation":
            emit_property(
                field("property_api_name"), f"{locator}.propertyApiName", implementation
            )
        elif discriminator == "structFieldImplementation":
            struct_field = field("struct_field_of_property")
            property_name = (
                struct_field.get("property_api_name")
                if isinstance(struct_field, Mapping)
                else getattr(struct_field, "property_api_name", None)
            )
            struct_field_name = (
                struct_field.get("struct_field_api_name")
                if isinstance(struct_field, Mapping)
                else getattr(struct_field, "struct_field_api_name", None)
            )
            if not struct_field_name:
                self._add_gap(
                    context,
                    target_node_id,
                    "ontology-structure-backing",
                    "unresolved",
                    "invalid-interface-property-v2-implementation",
                    f"Struct field implementation is malformed at {locator}.structFieldOfProperty",
                    locator=f"{locator}.structFieldOfProperty",
                )
            emit_property(
                property_name,
                f"{locator}.structFieldOfProperty.{struct_field_name or 'unknown'}",
                struct_field,
            )
        elif discriminator == "structImplementation":
            mapping = field("mapping")
            if not isinstance(mapping, Mapping):
                self._add_gap(
                    context,
                    target_node_id,
                    "ontology-structure-backing",
                    "unresolved",
                    "invalid-interface-property-v2-implementation",
                    f"Struct implementation mapping is malformed at {locator}.mapping",
                    locator=f"{locator}.mapping",
                )
            else:
                for interface_field, local_implementation in sorted(
                    mapping.items(), key=lambda pair: str(pair[0])
                ):
                    context.budget.charge("items")
                    local_type = (
                        local_implementation.get("type")
                        if isinstance(local_implementation, Mapping)
                        else getattr(local_implementation, "type", None)
                    )
                    local_property = (
                        local_implementation.get("property_api_name")
                        if isinstance(local_implementation, Mapping)
                        else getattr(local_implementation, "property_api_name", None)
                    )
                    local_field = (
                        local_implementation.get("struct_field_api_name")
                        if isinstance(local_implementation, Mapping)
                        else getattr(
                            local_implementation, "struct_field_api_name", None
                        )
                    )
                    field_locator = f"{locator}.mapping.{interface_field}"
                    if local_type not in {"property", "structFieldOfProperty"}:
                        self._add_gap(
                            context,
                            target_node_id,
                            "ontology-structure-backing",
                            "unresolved",
                            f"unknown-interface-property-struct-mapping:{local_type or 'missing'}",
                            f"Unknown struct mapping implementation at {field_locator}",
                            locator=field_locator,
                        )
                        continue
                    if local_type == "structFieldOfProperty" and not local_field:
                        self._add_gap(
                            context,
                            target_node_id,
                            "ontology-structure-backing",
                            "unresolved",
                            "invalid-interface-property-v2-implementation",
                            f"Struct mapping field is missing at {field_locator}",
                            locator=field_locator,
                        )
                    emit_property(
                        local_property,
                        f"{field_locator}.{local_field or 'property'}",
                        local_implementation,
                    )
        elif discriminator == "reducedPropertyImplementation":
            nested = field("implementation")
            if nested is None:
                self._add_gap(
                    context,
                    target_node_id,
                    "ontology-structure-backing",
                    "unresolved",
                    "invalid-interface-property-v2-implementation",
                    f"Reduced property implementation is missing its implementation at {locator}",
                    locator=f"{locator}.implementation",
                )
            else:
                context.budget.charge("items")
                evidence_ids.extend(
                    self._collect_interface_property_v2_implementation(
                        context,
                        target_node_id,
                        operation_id,
                        ontology_rid,
                        object_type,
                        interface_type,
                        interface_property,
                        nested,
                        f"{locator}.implementation",
                        _seen=seen,
                    )
                )
        else:
            self._add_gap(
                context,
                target_node_id,
                "ontology-structure-backing",
                "unresolved",
                f"unknown-interface-property-v2-implementation:{discriminator or 'missing'}",
                f"Unknown interface property implementation at {locator}",
                locator=locator,
            )
        return evidence_ids

    def _add_interface_property_mapping_edge(
        self,
        context: AnalysisContext,
        ontology_rid: str,
        object_type: str,
        interface_type: str,
        interface_property: str,
        property_name: str,
        evidence_id: str,
    ) -> None:
        interface_property_node = self._add_node(
            context,
            "interface-property-type",
            f"{interface_type}.{interface_property}",
            {
                "ontology_rid": ontology_rid,
                "interface_type": interface_type,
                "interface_property_type": interface_property,
            },
        )
        property_node = self._add_node(
            context,
            "property",
            f"{object_type}.{property_name}",
            {
                "ontology_rid": ontology_rid,
                "object_type": object_type,
                "property": property_name,
            },
        )
        self._add_edge(
            context,
            interface_property_node.id,
            property_node.id,
            "container-member",
            [evidence_id],
        )

    def _add_property_mapping_edge(
        self,
        context: AnalysisContext,
        ontology_rid: str,
        object_type: str,
        shared_name: str,
        property_name: str,
        evidence_id: str,
    ) -> None:
        shared_node = self._add_node(
            context,
            "shared-property-type",
            shared_name,
            {"ontology_rid": ontology_rid, "shared_property_type": shared_name},
        )
        property_node = self._add_node(
            context,
            "property",
            f"{object_type}.{property_name}",
            {
                "ontology_rid": ontology_rid,
                "object_type": object_type,
                "property": property_name,
            },
        )
        self._add_edge(
            context,
            shared_node.id,
            property_node.id,
            "container-member",
            [evidence_id],
        )

    def _collect_reverse_actions(
        self,
        target: DependencyTarget,
        context: AnalysisContext,
        ontology_rid: str,
    ) -> None:
        assert target.node_id is not None
        record = self._coverage_record(
            context, target.kind, "full-action-metadata", target.node_id
        )
        evidence_ids: list[str] = []
        index = self._get_action_index(context, ontology_rid)
        entries = index["entries"]
        has_gaps = False
        for metadata, operation_id in entries:
            action_name = str(getattr(metadata.action_type, "api_name", ""))
            action_node: Optional[Node] = None
            try:
                references = self._extract_action_references(
                    metadata, ontology_rid, context, operation_id
                )
            except BudgetExhausted as error:
                partial_evidence = [
                    reference[3]
                    for reference in error.partial_action_references
                    if self._reference_matches_target(reference, target)
                ]
                self._record_failure(
                    context,
                    record,
                    error,
                    "action-type.list-full-metadata",
                    evidence_ids=[*evidence_ids, *partial_evidence],
                )
                return
            has_gaps = has_gaps or self._has_reported_gap(
                context,
                self._action_node_id(metadata, ontology_rid),
                record.surface,
            )
            for reference in references:
                if not self._reference_matches_target(reference, target):
                    continue
                if action_node is None:
                    action_node = self._add_node(
                        context,
                        "action-type",
                        action_name,
                        {"ontology_rid": ontology_rid, "action_type": action_name},
                    )
                evidence_ids.append(reference[3])
                self._add_edge(
                    context,
                    action_node.id,
                    target.node_id,
                    "action-affects-object",
                    [reference[3]],
                )
        if index.get("incomplete_error") is not None:
            self._record_failure(
                context,
                record,
                index["incomplete_error"],
                "action-type.list-full-metadata",
                evidence_ids=evidence_ids,
            )
            return
        self._finish_coverage(
            record,
            "partial" if has_gaps else ("covered" if evidence_ids else "covered-empty"),
            evidence_ids=evidence_ids,
            reason="action-metadata-shape-gap" if has_gaps else None,
        )

    def _collect_reverse_queries(
        self,
        target: DependencyTarget,
        context: AnalysisContext,
        ontology_rid: str,
    ) -> None:
        assert target.node_id is not None
        record = self._coverage_record(
            context,
            target.kind,
            "query-related-function-metadata",
            target.node_id,
        )
        evidence_ids: list[str] = []
        index = self._get_query_index(context, ontology_rid)
        entries = index["entries"]
        has_gaps = False
        for query, operation_id in entries:
            roots = {
                f"parameters.{name}.dataType": parameter.data_type
                for name, parameter in sorted(query.parameters.items())
            }
            roots["output"] = query.output
            try:
                closure = self._build_query_reference_closure(query, roots, context)
            except BudgetExhausted as error:
                for kind, name, locator in error.partial_query_leaves:
                    if not self._reference_matches_target(
                        (kind, name, locator, ""), target
                    ):
                        continue
                    evidence = self._add_evidence(
                        context, operation_id, locator, locator, name
                    )
                    evidence_ids.append(evidence.id)
                self._record_failure(
                    context,
                    record,
                    error,
                    "query-metadata-walk",
                    evidence_ids=evidence_ids,
                )
                return
            for root_name, result in sorted(closure.items()):
                for gap in result["gaps"]:
                    has_gaps = True
                    self._add_gap(
                        context,
                        target.node_id,
                        record.surface,
                        "unsupported"
                        if gap["reason_code"] == "unsupported-query-data-type"
                        else "unresolved",
                        gap["reason_code"],
                        f"{gap['message']} at {gap['locator']}",
                        locator=gap["locator"],
                    )
                for leaf in result["leaves"]:
                    reference = (leaf["kind"], leaf["name"], leaf["locator"], "")
                    if not self._reference_matches_target(reference, target):
                        continue
                    evidence = self._add_evidence(
                        context,
                        operation_id,
                        leaf["locator"],
                        leaf["locator"],
                        leaf["name"],
                    )
                    evidence_ids.append(evidence.id)
                    query_node = self._add_node(
                        context,
                        "query-type",
                        str(query.api_name),
                        {
                            "ontology_rid": ontology_rid,
                            "query_type": str(query.api_name),
                        },
                    )
                    relation = (
                        "query-returns-object"
                        if root_name == "output"
                        else "query-accepts-object"
                    )
                    source, edge_target = (
                        (query_node.id, target.node_id)
                        if root_name == "output"
                        else (target.node_id, query_node.id)
                    )
                    self._add_edge(
                        context, source, edge_target, relation, [evidence.id]
                    )
        if index.get("incomplete_error") is not None:
            self._record_failure(
                context,
                record,
                index["incomplete_error"],
                "query-type.list",
                evidence_ids=evidence_ids,
            )
            return
        self._finish_coverage(
            record,
            "partial" if has_gaps else ("covered" if evidence_ids else "covered-empty"),
            evidence_ids=evidence_ids,
            reason="query-metadata-shape-gap" if has_gaps else None,
        )

    def _collect_action_target(
        self, target: DependencyTarget, context: AnalysisContext
    ) -> None:
        assert target.node_id is not None
        ontology_rid = target.identifiers["ontology_rid"]
        metadata, operation_id = context.caches[
            (
                "action-metadata",
                ontology_rid,
                context.read_context.requested_branch,
                target.identifiers["action_type"],
            )
        ]
        evidence_ids: list[str] = []
        structure_record = self._coverage_record(
            context, target.kind, "ontology-structure-backing", target.node_id
        )
        action_record = self._coverage_record(
            context, target.kind, "full-action-metadata", target.node_id
        )
        try:
            references = self._extract_action_references(
                metadata, ontology_rid, context, operation_id
            )
        except BudgetExhausted as error:
            partial_evidence = [
                reference[3] for reference in error.partial_action_references
            ]
            self._finish_coverage(
                structure_record,
                "partial" if partial_evidence else "covered-empty",
                evidence_ids=partial_evidence,
                reason="action-metadata-walk-incomplete",
            )
            self._record_failure(
                context,
                action_record,
                error,
                "action-metadata-walk",
                evidence_ids=partial_evidence,
            )
            return
        global_owners = sorted(
            {name for kind, name, _, _ in references if kind == "object-type"}
        )
        for kind, name, locator, evidence_id in references:
            evidence_ids.append(evidence_id)
            identifiers = {"ontology_rid": ontology_rid, kind.replace("-", "_"): name}
            if kind == "function":
                identifiers = {"function_rid": name}
            related_kind = kind
            if kind in {"property", "link-type"}:
                prefix = locator.split(".", 1)[0]
                local_owners = sorted(
                    {
                        owner
                        for owner_kind, owner, owner_locator, _ in references
                        if owner_kind == "object-type"
                        and owner_locator.split(".", 1)[0] == prefix
                    }
                )
                owners = local_owners or global_owners
                if len(owners) == 1:
                    identifiers["object_type"] = owners[0]
                else:
                    related_kind = f"unresolved-{kind}-reference"
                    self._add_gap(
                        context,
                        target.node_id,
                        "full-action-metadata",
                        "unresolved",
                        f"ambiguous-{kind}-owner",
                        f"Cannot derive one concrete owning object type for {kind} {name} at {locator}",
                    )
            related = self._add_node(context, related_kind, name, identifiers)
            relation = (
                "action-uses-function"
                if kind == "function"
                else "action-affects-object"
            )
            self._add_edge(context, target.node_id, related.id, relation, [evidence_id])
        for surface, record in (
            ("ontology-structure-backing", structure_record),
            ("full-action-metadata", action_record),
        ):
            has_gaps = self._has_reported_gap(context, target.node_id, surface)
            self._finish_coverage(
                record,
                "partial"
                if has_gaps
                else ("covered" if evidence_ids else "covered-empty"),
                evidence_ids=evidence_ids,
                reason="action-metadata-shape-gap" if has_gaps else None,
            )
        query_record = self._coverage_record(
            context,
            target.kind,
            "query-related-function-metadata",
            target.node_id,
        )
        function_evidence = [
            reference[3] for reference in references if reference[0] == "function"
        ]
        if function_evidence:
            self._finish_coverage(
                query_record,
                "partial",
                evidence_ids=function_evidence,
                reason="function-internals-unavailable",
            )
            self._add_gap(
                context,
                target.node_id,
                query_record.surface,
                "partial",
                "function-internals-unavailable",
                "Function RIDs are observable but function bodies and reverse consumers are unavailable",
            )
        else:
            self._finish_coverage(query_record, "covered-empty")

    def _extract_action_references(
        self,
        metadata: Any,
        ontology_rid: str,
        context: AnalysisContext,
        operation_id: str,
    ) -> list[tuple[str, str, str, str]]:
        references: list[tuple[str, str, str, str]] = []
        parameters = getattr(metadata.action_type, "parameters", {}) or {}

        def emit(kind: str, name: Any, locator: str, raw: Any) -> None:
            if name is None or str(name) == "":
                return
            evidence = self._add_evidence(context, operation_id, locator, locator, raw)
            references.append((kind, str(name), locator, evidence.id))

        work: list[tuple[Any, str, int]] = [
            (parameter.data_type, f"parameters.{parameter_id}.dataType", 0)
            for parameter_id, parameter in reversed(sorted(parameters.items()))
        ]
        # Full logic rules are the dependency contract.  Shallow operations are
        # intentionally neither traversed nor position-correlated.
        for index, rule in enumerate(getattr(metadata, "full_logic_rules", []) or []):
            discriminator = (
                rule.get("type")
                if isinstance(rule, Mapping)
                else getattr(rule, "type", None)
            )
            if discriminator not in ACTION_LOGIC_RULE_TYPES:
                self._add_gap(
                    context,
                    self._action_node_id(metadata, ontology_rid),
                    "full-action-metadata",
                    "unresolved",
                    f"unknown-action-logic-rule:{discriminator or 'missing'}",
                    f"Unknown action logic rule at fullLogicRules[{index}]",
                    locator=f"fullLogicRules[{index}]",
                )
            work.append((rule, f"fullLogicRules[{index}]", 0))

        parameter_fields = {
            "parameter_id",
            "scenario_parameter",
            "object_to_modify",
            "object_to_delete",
            "interface_object_to_modify",
            "source_object",
            "target_object",
        }
        try:
            while work:
                value, locator, depth = work.pop()
                context.budget.check_metadata_depth(depth)
                context.budget.charge("items")
                if value is None or isinstance(value, (str, bool, int, float)):
                    continue
                if isinstance(value, Mapping):
                    children = sorted(value.items(), key=lambda pair: str(pair[0]))
                    for key, item in reversed(children):
                        path = f"{locator}.{key}"
                        if locator.endswith(
                            ("propertyArguments", "sharedPropertyArguments")
                        ):
                            emit("property", key, path, item)
                        work.append((item, path, depth + 1))
                    continue
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    for index in range(len(value) - 1, -1, -1):
                        work.append((value[index], f"{locator}[{index}]", depth + 1))
                    continue
                fields = self._declared_fields(value)
                discriminator = getattr(value, "type", None)
                for name, item in reversed(fields):
                    path = f"{locator}.{self._field_alias(value, name)}"
                    if name in {
                        "object_type_api_name",
                        "object_api_name",
                        "a_side_object_type_api_name",
                        "b_side_object_type_api_name",
                    }:
                        emit("object-type", item, path, value)
                    elif name == "interface_type_api_name":
                        emit("interface-type", item, path, value)
                    elif "link_type_api_name" in name:
                        emit("link-type", item, path, value)
                    elif name == "function_rid":
                        emit("function", item, path, value)
                    elif name == "property_type_api_name":
                        emit("property", item, path, value)
                    elif name == "shared_property_type_rid":
                        emit("shared-property-type", item, path, value)
                    elif name == "object_type_api_names" and isinstance(item, Sequence):
                        for item_index, object_name in enumerate(item):
                            emit(
                                "object-type",
                                object_name,
                                f"{path}[{item_index}]",
                                value,
                            )
                    elif name == "link_types" and isinstance(item, Sequence):
                        for item_index in range(len(item) - 1, -1, -1):
                            link_name = item[item_index]
                            if isinstance(link_name, str):
                                emit(
                                    "link-type",
                                    link_name,
                                    f"{path}[{item_index}]",
                                    value,
                                )
                            else:
                                work.append(
                                    (link_name, f"{path}[{item_index}]", depth + 1)
                                )
                    elif name == "object_type" and isinstance(item, str):
                        if type(value).__name__ == "CreateInterfaceLogicRule":
                            parameter = parameters.get(item)
                            if parameter is None:
                                self._add_gap(
                                    context,
                                    self._action_node_id(metadata, ontology_rid),
                                    "full-action-metadata",
                                    "unresolved",
                                    "unresolved-action-parameter",
                                    f"Rule references missing parameter {item} at {path}",
                                    locator=path,
                                )
                            else:
                                work.append(
                                    (
                                        parameter.data_type,
                                        f"{path}->parameters.{item}.dataType",
                                        depth + 1,
                                    )
                                )
                        else:
                            emit("object-type", item, path, value)
                    elif name in parameter_fields and isinstance(item, str):
                        parameter = parameters.get(item)
                        if parameter is None:
                            self._add_gap(
                                context,
                                self._action_node_id(metadata, ontology_rid),
                                "full-action-metadata",
                                "unresolved",
                                "unresolved-action-parameter",
                                f"Rule references missing parameter {item} at {path}",
                                locator=path,
                            )
                        else:
                            work.append(
                                (
                                    parameter.data_type,
                                    f"{path}->parameters.{item}.dataType",
                                    depth + 1,
                                )
                            )
                    elif name != "type":
                        work.append((item, path, depth + 1))
                if discriminator == "objectType" and not any(
                    name in {"object_type_api_name", "object_api_name"}
                    for name, _ in fields
                ):
                    self._add_gap(
                        context,
                        self._action_node_id(metadata, ontology_rid),
                        "full-action-metadata",
                        "unresolved",
                        "unresolved-action-parameter-type",
                        f"Generic objectType parameter at {locator} does not identify a concrete type",
                        locator=locator,
                    )
        except BudgetExhausted as error:
            unique = {reference[:3]: reference for reference in references}
            error.partial_action_references = [unique[key] for key in sorted(unique)]
            raise
        unique = {reference[:3]: reference for reference in references}
        return [unique[key] for key in sorted(unique)]

    @staticmethod
    def _action_node_id(metadata: Any, ontology_rid: str) -> str:
        return _stable_id(
            "node",
            "action-type",
            f"action_type={metadata.action_type.api_name}",
            f"ontology_rid={ontology_rid}",
        )

    @staticmethod
    def _reference_matches_target(
        reference: tuple[str, str, str, str], target: DependencyTarget
    ) -> bool:
        kind, name = reference[0], reference[1]
        if target.kind == "object-type":
            return kind == "object-type" and name == target.identifiers["object_type"]
        if target.kind == "property":
            return kind == "property" and name == target.identifiers["property"]
        if target.kind == "link-type":
            return kind == "link-type" and name == target.identifiers["link_type"]
        return False

    def _collect_query_target(
        self, target: DependencyTarget, context: AnalysisContext
    ) -> None:
        assert target.node_id is not None
        ontology_rid = target.identifiers["ontology_rid"]
        query, operation_id = context.caches[
            (
                "query-metadata",
                ontology_rid,
                context.read_context.requested_branch,
                target.identifiers["query_type"],
            )
        ]
        roots = {
            f"parameters.{name}.dataType": parameter.data_type
            for name, parameter in sorted(query.parameters.items())
        }
        roots["output"] = query.output
        structure_record = self._coverage_record(
            context, target.kind, "ontology-structure-backing", target.node_id
        )
        query_record = self._coverage_record(
            context,
            target.kind,
            "query-related-function-metadata",
            target.node_id,
        )
        try:
            closure = self._build_query_reference_closure(query, roots, context)
            context.caches[("query-reference-closure", target.node_id)] = closure
        except BudgetExhausted as error:
            partial_evidence = [
                self._add_evidence(context, operation_id, locator, locator, name).id
                for _, name, locator in getattr(error, "partial_query_leaves", ())
            ]
            self._finish_coverage(
                structure_record,
                "partial" if partial_evidence else "covered-empty",
                evidence_ids=partial_evidence,
                reason="query-metadata-walk-incomplete",
            )
            self._record_failure(
                context,
                query_record,
                error,
                "query-metadata-walk",
                evidence_ids=partial_evidence,
            )
            return
        evidence_ids: list[str] = []
        has_gap = False
        for root_name, result in sorted(closure.items()):
            for leaf in result["leaves"]:
                evidence = self._add_evidence(
                    context,
                    operation_id,
                    leaf["locator"],
                    leaf["locator"],
                    leaf["name"],
                )
                evidence_ids.append(evidence.id)
                identifiers = {
                    "ontology_rid": ontology_rid,
                    leaf["kind"].replace("-", "_"): leaf["name"],
                }
                related = self._add_node(
                    context, leaf["kind"], leaf["name"], identifiers
                )
                relation = (
                    "query-returns-object"
                    if root_name == "output"
                    else "query-accepts-object"
                )
                source, edge_target = (
                    (target.node_id, related.id)
                    if root_name == "output"
                    else (related.id, target.node_id)
                )
                self._add_edge(context, source, edge_target, relation, [evidence.id])
            for gap in result["gaps"]:
                has_gap = True
                coverage = (
                    "unsupported"
                    if gap["reason_code"] == "unsupported-query-data-type"
                    else "unresolved"
                )
                self._add_gap(
                    context,
                    target.node_id,
                    "query-related-function-metadata",
                    coverage,
                    gap["reason_code"],
                    f"{gap['message']} at {gap['locator']}",
                    locator=gap["locator"],
                )
        for surface, record in (
            ("ontology-structure-backing", structure_record),
            ("query-related-function-metadata", query_record),
        ):
            self._finish_coverage(
                record,
                "partial"
                if has_gap
                else ("covered" if evidence_ids else "covered-empty"),
                evidence_ids=evidence_ids,
                reason="query-type-reference-gap" if has_gap else None,
            )
        self._collect_reverse_actions(target, context, ontology_rid)

    def _build_query_reference_closure(
        self, query: Any, roots: Mapping[str, Any], context: AnalysisContext
    ) -> dict[str, dict[str, Any]]:
        """Return a complete root-specific closure over recursive type references.

        Reachable definitions are scanned lazily, SCCs are found iteratively,
        and root locators are rebuilt from cached direct scans with a bounded
        witness walk.  Unreachable definitions are never inspected.
        """
        definitions = getattr(query, "type_references", {}) or {}
        reference_graph: dict[str, set[str]] = defaultdict(set)
        direct_leaves: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        direct_gaps: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        direct_references: dict[str, set[tuple[str, str]]] = defaultdict(set)

        def inspect(
            value: Any, locator: str
        ) -> tuple[
            set[tuple[str, str, str]],
            set[tuple[str, str, str]],
            set[tuple[str, str]],
        ]:
            leaves: set[tuple[str, str, str]] = set()
            gaps: set[tuple[str, str, str]] = set()
            references: set[tuple[str, str]] = set()
            work: list[tuple[Any, str, int]] = [(value, locator, 0)]
            try:
                while work:
                    current, current_locator, depth = work.pop()
                    context.budget.check_metadata_depth(depth)
                    context.budget.charge("items")
                    discriminator = getattr(current, "type", None)
                    if discriminator == "typeReference":
                        reference_id = getattr(current, "type_id", None)
                        if reference_id is None:
                            gaps.add(
                                (
                                    "invalid-response",
                                    current_locator,
                                    "Missing query type reference ID",
                                )
                            )
                        else:
                            references.add((str(reference_id), current_locator))
                        continue
                    if discriminator in {"object", "objectSet"}:
                        name = getattr(
                            current, "object_type_api_name", None
                        ) or getattr(current, "object_api_name", None)
                        if name:
                            leaves.add(("object-type", str(name), current_locator))
                        else:
                            gaps.add(
                                (
                                    "invalid-response",
                                    current_locator,
                                    "Object query type has no concrete API name",
                                )
                            )
                        continue
                    if discriminator in {"interfaceObject", "interfaceObjectSet"}:
                        name = getattr(current, "interface_type_api_name", None)
                        if name:
                            leaves.add(("interface-type", str(name), current_locator))
                        else:
                            gaps.add(
                                (
                                    "invalid-response",
                                    current_locator,
                                    "Interface query type has no concrete API name",
                                )
                            )
                        continue
                    if (
                        discriminator == "unsupported"
                        or type(current).__name__ == "UnsupportedType"
                    ):
                        gaps.add(
                            (
                                "unsupported-query-data-type",
                                current_locator,
                                "Reachable query data type is unsupported by the SDK",
                            )
                        )
                        continue
                    children: list[tuple[str, Any]] = []
                    if discriminator in {"array", "set"}:
                        children.append(("subType", getattr(current, "sub_type", None)))
                    elif discriminator == "union":
                        children.extend(
                            (f"unionTypes[{index}]", item)
                            for index, item in enumerate(
                                getattr(current, "union_types", []) or []
                            )
                        )
                    elif discriminator == "struct":
                        children.extend(
                            (
                                f"fields[{index}].fieldType",
                                getattr(item, "field_type", None),
                            )
                            for index, item in enumerate(
                                getattr(current, "fields", []) or []
                            )
                        )
                    elif discriminator in {
                        "entrySet",
                        "twoDimensionalAggregation",
                        "threeDimensionalAggregation",
                    }:
                        children.extend(
                            (
                                ("keyType", getattr(current, "key_type", None)),
                                ("valueType", getattr(current, "value_type", None)),
                            )
                        )
                    elif discriminator not in QUERY_DATA_TYPE_TYPES:
                        gaps.add(
                            (
                                "invalid-response",
                                current_locator,
                                f"Unknown reachable query data type variant: {discriminator or type(current).__name__}",
                            )
                        )
                    for child_name, child in reversed(children):
                        child_locator = f"{current_locator}.{child_name}"
                        if child is None:
                            gaps.add(
                                (
                                    "invalid-response",
                                    child_locator,
                                    "Missing query data type child",
                                )
                            )
                        else:
                            work.append((child, child_locator, depth + 1))
            except BudgetExhausted as error:
                partial = list(getattr(error, "partial_query_leaves", ()))
                partial.extend(sorted(leaves))
                error.partial_query_leaves = partial
                raise
            return leaves, gaps, references

        root_scans: dict[str, tuple[set[Any], set[Any], set[Any]]] = {}
        for name, value in sorted(roots.items()):
            try:
                root_scans[name] = inspect(value, name)
            except BudgetExhausted as error:
                prior_leaves = {
                    leaf
                    for root_leaves, _, _ in root_scans.values()
                    for leaf in root_leaves
                }
                error.partial_query_leaves.extend(
                    leaf
                    for leaf in sorted(prior_leaves)
                    if leaf not in error.partial_query_leaves
                )
                raise

        def preserve_partial(error: BudgetExhausted) -> None:
            leaves = {
                leaf
                for root_leaves, _, _ in root_scans.values()
                for leaf in root_leaves
            }
            for definition_leaves in direct_leaves.values():
                leaves.update(definition_leaves)
            error.partial_query_leaves.extend(
                leaf
                for leaf in sorted(leaves)
                if leaf not in error.partial_query_leaves
            )

        reachable: set[str] = set()
        frontier: deque[tuple[str, int]] = deque(
            (reference_id, 0)
            for reference_id in sorted(
                {
                    reference_id
                    for _, _, references in root_scans.values()
                    for reference_id, _ in references
                }
            )
        )
        while frontier:
            reference_id, depth = frontier.popleft()
            try:
                context.budget.check_metadata_depth(depth)
                context.budget.charge("items")
            except BudgetExhausted as error:
                preserve_partial(error)
                raise
            if reference_id in reachable:
                continue
            reachable.add(reference_id)
            if reference_id not in definitions:
                direct_gaps[reference_id].add(
                    (
                        "invalid-response",
                        f"typeReferences.{reference_id}",
                        f"Missing reachable type reference {reference_id}",
                    )
                )
                continue
            base = f"typeReferences.{reference_id}"
            try:
                leaves, gaps, references = inspect(definitions[reference_id], base)
            except BudgetExhausted as error:
                preserve_partial(error)
                raise
            direct_leaves[reference_id].update(leaves)
            direct_gaps[reference_id].update(gaps)
            direct_references[reference_id].update(references)
            reference_graph[reference_id].update(child for child, _ in references)
            for child in sorted(reference_graph[reference_id]):
                if child not in reachable:
                    frontier.append((child, depth + 1))

        reachable_graph: dict[str, set[str]] = {
            node: set(reference_graph.get(node, ())).intersection(reachable)
            for node in reachable
        }
        try:
            components = self._tarjan_scc(reachable_graph, context)
        except BudgetExhausted as error:
            preserve_partial(error)
            raise

        results: dict[str, dict[str, Any]] = {}
        for root_name, (root_leaves, root_gaps, root_references) in root_scans.items():
            leaves = set(root_leaves)
            gaps = set(root_gaps)
            queue: deque[tuple[str, str]] = deque(
                sorted(root_references, key=lambda value: (value[1], value[0]))
            )
            visited: set[str] = set()
            while queue:
                reference_id, witness = queue.popleft()
                try:
                    context.budget.charge("items")
                except BudgetExhausted as error:
                    preserve_partial(error)
                    raise
                if reference_id in visited:
                    continue
                visited.add(reference_id)
                if reference_id not in definitions:
                    gaps.add(
                        (
                            "invalid-response",
                            witness,
                            f"Missing reachable type reference {reference_id}",
                        )
                    )
                    continue
                base = f"typeReferences.{reference_id}"
                for kind, name, locator in direct_leaves[reference_id]:
                    suffix = locator[len(base) :]
                    leaves.add((kind, name, f"{witness}->{base}{suffix}"))
                for reason, locator, message in direct_gaps[reference_id]:
                    suffix = locator[len(base) :] if locator.startswith(base) else ""
                    gaps.add((reason, f"{witness}->{base}{suffix}", message))
                for child, child_locator in sorted(direct_references[reference_id]):
                    suffix = child_locator[len(base) :]
                    queue.append((child, f"{witness}->{base}{suffix}"))
            results[root_name] = {
                "leaves": [
                    {"kind": kind, "name": name, "locator": locator}
                    for kind, name, locator in sorted(leaves)
                ],
                "gaps": [
                    {"reason_code": reason, "locator": locator, "message": message}
                    for reason, locator, message in sorted(gaps)
                ],
                "sccs": [list(component) for component in components],
            }
        return results

    @staticmethod
    def _tarjan_scc(
        graph: Mapping[str, set[str]], context: Optional[AnalysisContext] = None
    ) -> list[tuple[str, ...]]:
        visited: set[str] = set()
        order: list[str] = []
        for start in sorted(graph):
            if start in visited:
                continue
            work: list[tuple[str, bool]] = [(start, False)]
            while work:
                if context is not None:
                    context.budget.charge("items")
                node, expanded = work.pop()
                if expanded:
                    order.append(node)
                    continue
                if node in visited:
                    continue
                visited.add(node)
                work.append((node, True))
                for child in reversed(sorted(graph.get(node, ()))):
                    if child in graph and child not in visited:
                        work.append((child, False))
        reverse_graph: dict[str, set[str]] = {node: set() for node in graph}
        for node, children in graph.items():
            for child in children:
                if child in reverse_graph:
                    reverse_graph[child].add(node)
        components: list[tuple[str, ...]] = []
        assigned: set[str] = set()
        for start in reversed(order):
            if start in assigned:
                continue
            component: list[str] = []
            work = [(start, False)]
            assigned.add(start)
            while work:
                if context is not None:
                    context.budget.charge("items")
                node, _ = work.pop()
                component.append(node)
                for parent in reversed(sorted(reverse_graph[node])):
                    if parent not in assigned:
                        assigned.add(parent)
                        work.append((parent, False))
            components.append(tuple(sorted(component)))
        return sorted(components, key=lambda component: component[0])

    def _collect_dataset(
        self, target: DependencyTarget, context: AnalysisContext
    ) -> None:
        assert target.node_id is not None
        dataset_rid = target.identifiers["resource_rid"]
        if self._conjure_provider is not None:
            self._collect_transform_dataset_lineage(target, context)
        dataset_service = DatasetService(self.profile)
        dataset_service._client = self.client
        orchestration = OrchestrationService(self.profile)
        orchestration._client = self.client
        record = self._coverage_record(
            context, "dataset", "schedule-reverse-index", target.node_id
        )
        compass = self._coverage_record(
            context, target.kind, "compass-metadata", target.node_id
        )
        resource_evidence = [
            evidence.id
            for evidence in context.evidence.values()
            if evidence.locator == "resource"
        ]
        self._finish_coverage(compass, "covered", evidence_ids=resource_evidence)
        page_token: Optional[str] = None
        reverse_evidence: list[str] = []
        schedule_work: list[tuple[Node, Mapping[str, CoverageRecord]]] = []
        staleness = {
            "reason_code": "schedule-index-may-be-stale",
            "message": "Results may lag recent schedule changes by up to one hour",
            "max_lag_seconds": 3600,
        }
        try:
            while True:
                page_size = context.budget.reserve_page(100)
                kwargs: dict[str, Any] = {
                    "dataset_rid": dataset_rid,
                    "page_size": page_size,
                }
                branch = (
                    context.read_context.dataset_branch
                    or context.read_context.requested_branch
                )
                if branch is not None:
                    kwargs["branch_name"] = branch
                if page_token is not None:
                    kwargs["page_token"] = page_token
                page, operation_id = self._invoke_sdk(
                    context,
                    "dataset.get-schedules",
                    dataset_service.get_schedule_rids_page,
                    kwargs,
                    target=dataset_rid,
                    known_limitations=(staleness,),
                )
                schedule_rids = list(page.get("schedule_rids", []))
                for index, schedule_rid in enumerate(schedule_rids):
                    context.budget.charge("items")
                    evidence = self._add_evidence(
                        context,
                        operation_id,
                        f"scheduleRids[{index}]",
                        f"schedule_rids[{index}]",
                        schedule_rid,
                    )
                    reverse_evidence.append(evidence.id)
                    schedule_node = self._add_node(
                        context,
                        "schedule",
                        str(schedule_rid),
                        {"schedule_rid": str(schedule_rid)},
                    )
                    self._add_edge(
                        context,
                        schedule_node.id,
                        target.node_id,
                        "schedule-produces-resource",
                        [evidence.id],
                    )
                    child_records = {
                        surface: self._coverage_record(
                            context,
                            "schedule",
                            surface,
                            schedule_node.id,
                            parent_record_id=record.id,
                            applicability_evidence_id=evidence.id,
                        )
                        for surface in (
                            "schedule-detail-action",
                            "schedule-trigger",
                            "schedule-affected-resources",
                            "schedule-runs",
                        )
                    }
                    schedule_work.append((schedule_node, child_records))
                page_token = page.get("next_page_token")
                if not page_token:
                    break
        except Exception as error:
            self._record_failure(
                context,
                record,
                error,
                "dataset.get-schedules",
                evidence_ids=reverse_evidence,
            )
            return
        self._finish_coverage(
            record,
            "partial",
            evidence_ids=reverse_evidence,
            reason="schedule-index-may-be-stale",
        )
        self._add_gap(
            context,
            target.node_id,
            record.surface,
            "partial",
            "schedule-index-may-be-stale",
            "Returned schedule RIDs are verified, but results may lag recent schedule changes by up to one hour",
            retryable=True,
            operation="dataset.get-schedules",
        )
        for schedule_node, schedule_mapping in schedule_work:
            child_records = dict(schedule_mapping)
            self._collect_schedule(
                context,
                target,
                schedule_node,
                orchestration,
                child_records,
            )

    def _collect_transform_dataset_lineage(
        self, target: DependencyTarget, context: AnalysisContext
    ) -> None:
        """Collect the fail-closed build2/stemma south edge for one dataset."""

        assert target.node_id is not None
        from .dependency_internal_specs import TRANSFORM_LINEAGE_GET_OPERATION_SPECS
        from .foundry_internal_client import TokenExpiredError

        spec = TRANSFORM_LINEAGE_GET_OPERATION_SPECS["ACP-01"]
        provider = self._conjure_provider
        if provider is None:
            return
        record = self._coverage_record(
            context,
            "dataset",
            TRANSFORM_DATASET_LINEAGE_SURFACE,
            target.node_id,
            operation=spec.acp_id,
            transport=spec.transport,
            empty_is_inconclusive=spec.empty_is_inconclusive,
        )
        dataset_rid = target.identifiers["resource_rid"]
        path = spec.path.format(dataset_rid=quote(dataset_rid, safe=""))
        try:
            result = self._invoke_transform_lineage_get(
                context,
                spec,
                path,
                target=target.node_id,
            )
        except TokenExpiredError as error:
            self._record_lineage_token_expiry(
                context, target.node_id, spec.acp_id, path, error
            )
            return
        except BudgetExhausted as error:
            self._finish_coverage(
                record, "inconclusive", reason="internal-budget-exhausted"
            )
            self._add_gap(
                context,
                target.node_id,
                record.surface,
                "inconclusive",
                "budget-exhausted",
                str(error),
                retryable=True,
                operation=spec.acp_id,
                budget_snapshot=error.snapshot,
                locator=path,
            )
            return

        if result.result_semantics == "empty" and result.payload == {}:
            existence_confirmed = False
            if result.positive_control_status == "passed":
                existence_confirmed = self._confirm_dataset_exists(
                    context, target.node_id, dataset_rid
                )
                if record.status == "token-expired":
                    return
            if result.positive_control_status == "passed" and existence_confirmed:
                self._remove_operation_gaps(
                    context, target.node_id, record.surface, spec.acp_id
                )
                self._finish_coverage(
                    record,
                    "covered-empty",
                    reason="authoritative-empty-no-producer",
                    reason_code="authoritative-empty-no-producer",
                    positive_control_status="passed",
                    existence_confirmed=True,
                )
                return
            self._finish_coverage(
                record,
                "inconclusive",
                reason="authoritative-empty-guard-failed",
                reason_code="authoritative-empty-guard-failed",
                positive_control_status=result.positive_control_status,
                existence_confirmed=existence_confirmed,
            )
            if not self._has_reported_gap(context, target.node_id, record.surface):
                self._add_gap(
                    context,
                    target.node_id,
                    record.surface,
                    "inconclusive",
                    "authoritative-empty-guard-failed",
                    "ACP-01 was empty without both same-run safety controls",
                    operation=spec.acp_id,
                    locator=path,
                )
            return

        if result.coverage_status != "covered":
            reason = (
                result.error_class or f"{result.result_semantics}-internal-response"
            )
            terminal_status = (
                "token-expired"
                if result.coverage_status == "token-expired"
                else "inconclusive"
            )
            self._finish_coverage(record, terminal_status, reason=reason)
            self._add_gap(
                context,
                target.node_id,
                record.surface,
                terminal_status,
                reason,
                "ACP-01 could not prove transform lineage",
                retryable=result.retryable,
                operation=spec.acp_id,
                locator=path,
            )
            return
        if not isinstance(result.payload, Mapping):
            self._finish_lineage_gap(
                context,
                record,
                "inconclusive",
                "response-shape-drift",
                "ACP-01 did not return a branch-keyed mapping",
                spec.acp_id,
                path,
            )
            return

        evidence_ids: list[str] = []
        unresolved = False
        inconclusive = False
        token_expired = False
        jobspec_count = 0
        branch_jobspecs, branch_shape_gaps = self._branch_jobspecs(result.payload)
        for locator in branch_shape_gaps:
            inconclusive = True
            self._add_gap(
                context,
                target.node_id,
                record.surface,
                "inconclusive",
                "response-shape-drift",
                "ACP-01 branch jobspec shape was not recognized",
                operation=spec.acp_id,
                locator=locator,
            )
        for branch, job_index, job_spec in branch_jobspecs:
            jobspec_count += 1
            base_locator = f"{branch}.jobSpecs[{job_index}]"
            jobspec_rid = self._first_string(job_spec, "jobSpecRid", "rid")
            if jobspec_rid is None:
                unresolved = True
                self._add_gap(
                    context,
                    target.node_id,
                    record.surface,
                    "inconclusive",
                    "response-shape-drift",
                    "ACP-01 jobspec omitted its RID",
                    operation=spec.acp_id,
                    locator=f"{base_locator}.rid",
                )
                continue
            transform = self._add_node(
                context,
                "transform-jobspec",
                jobspec_rid,
                {"resource_rid": jobspec_rid, "branch": branch},
            )
            input_datasets: list[tuple[Node, str]] = []
            repos: list[tuple[Node, str]] = []
            outputs: list[tuple[Node, str]] = []
            for input_index, input_spec in self._mapping_items(
                job_spec.get("inputSpecs")
            ):
                locator = f"{base_locator}.inputSpecs[{input_index}]"
                if input_spec.get("inputType") == "artifacts":
                    repo_rid = self._dataset_locator_rid(input_spec, "artifacts")
                    if repo_rid is None:
                        unresolved = True
                        self._add_gap(
                            context,
                            target.node_id,
                            record.surface,
                            "inconclusive",
                            "response-shape-drift",
                            "ACP-01 artifacts input omitted its repository RID",
                            operation=spec.acp_id,
                            locator=f"{locator}.datasetLocator.datasetRid",
                        )
                        continue
                    repo = self._add_node(
                        context,
                        "code-repo",
                        repo_rid,
                        {"resource_rid": repo_rid},
                    )
                    repos.append((repo, locator))
                    continue
                if input_spec.get("type") != "foundry":
                    continue
                input_rid = self._dataset_locator_rid(input_spec, "foundry")
                if input_rid is None:
                    inconclusive = True
                    self._add_gap(
                        context,
                        target.node_id,
                        record.surface,
                        "inconclusive",
                        "response-shape-drift",
                        "ACP-01 foundry input omitted its dataset RID",
                        operation=spec.acp_id,
                        locator=f"{locator}.datasetLocator.datasetRid",
                    )
                    continue
                input_datasets.append(
                    (
                        self._add_node(
                            context,
                            "dataset",
                            input_rid,
                            {"resource_rid": input_rid},
                        ),
                        locator,
                    )
                )
            for output_index, output_spec in self._mapping_items(
                job_spec.get("outputSpecs")
            ):
                locator = f"{base_locator}.outputSpecs[{output_index}]"
                if output_spec.get("type") != "foundry":
                    continue
                output_rid = self._dataset_locator_rid(output_spec, "foundry")
                if output_rid is None:
                    inconclusive = True
                    self._add_gap(
                        context,
                        target.node_id,
                        record.surface,
                        "inconclusive",
                        "response-shape-drift",
                        "ACP-01 foundry output omitted its dataset RID",
                        operation=spec.acp_id,
                        locator=f"{locator}.datasetLocator.datasetRid",
                    )
                    continue
                output_node = (
                    context.nodes[target.node_id]
                    if output_rid == dataset_rid
                    else self._add_node(
                        context,
                        "dataset",
                        output_rid,
                        {"resource_rid": output_rid},
                    )
                )
                outputs.append((output_node, locator))

            for input_node, locator in input_datasets:
                evidence = self._add_evidence(
                    context,
                    result.operation_provenance_id,
                    locator,
                    f"{locator}.datasetLocator.datasetRid",
                    job_spec,
                    discriminator="foundry",
                )
                evidence_ids.append(evidence.id)
                self._add_edge(
                    context,
                    input_node.id,
                    transform.id,
                    "dataset-feeds-transform",
                    [evidence.id],
                )
            for output_node, locator in outputs:
                evidence = self._add_evidence(
                    context,
                    result.operation_provenance_id,
                    locator,
                    f"{locator}.datasetLocator.datasetRid",
                    job_spec,
                    discriminator="foundry",
                )
                evidence_ids.append(evidence.id)
                self._add_edge(
                    context,
                    transform.id,
                    output_node.id,
                    "transform-builds-dataset",
                    [evidence.id],
                )
                for repo, repo_locator in repos:
                    repo_evidence = self._add_evidence(
                        context,
                        result.operation_provenance_id,
                        repo_locator,
                        f"{repo_locator}.datasetLocator.datasetRid",
                        job_spec,
                        discriminator="artifacts",
                    )
                    evidence_ids.append(repo_evidence.id)
                    self._add_edge(
                        context,
                        repo.id,
                        output_node.id,
                        "code-repo-builds-dataset",
                        [repo_evidence.id, evidence.id],
                    )
            source_path = self._jobspec_source_path(job_spec)
            if repos and outputs:
                if source_path is None:
                    unresolved = True
                    self._add_gap(
                        context,
                        target.node_id,
                        record.surface,
                        "unresolved",
                        "transform-source-unresolved",
                        "ACP-01 jobspec did not expose a canonical Python source path",
                        operation=spec.acp_id,
                        locator=base_locator,
                    )
                else:
                    for repo, _ in repos:
                        resolved_ids, source_status = self._collect_transform_source(
                            context,
                            target,
                            repo,
                            source_path,
                            result.operation_provenance_id,
                        )
                        evidence_ids.extend(resolved_ids)
                        unresolved = unresolved or source_status == "unresolved"
                        inconclusive = inconclusive or source_status == "inconclusive"
                        token_expired = (
                            token_expired or source_status == "token-expired"
                        )

        if jobspec_count == 0:
            self._finish_lineage_gap(
                context,
                record,
                "inconclusive",
                "response-shape-drift",
                "ACP-01 returned no parseable branch jobspecs",
                spec.acp_id,
                path,
            )
        elif not evidence_ids:
            self._finish_lineage_gap(
                context,
                record,
                "inconclusive",
                "no-supported-lineage",
                "ACP-01 contained no foundry dataset lineage",
                spec.acp_id,
                path,
            )
        elif token_expired:
            self._finish_coverage(
                record,
                "token-expired",
                evidence_ids=evidence_ids,
                reason="token-expired",
            )
        elif inconclusive:
            self._finish_coverage(
                record,
                "inconclusive",
                evidence_ids=evidence_ids,
                reason="transform-source-inconclusive",
            )
        elif unresolved:
            self._finish_coverage(
                record,
                "inconclusive",
                evidence_ids=evidence_ids,
                reason="transform-source-unresolved",
            )
        else:
            self._finish_coverage(record, "covered", evidence_ids=evidence_ids)

    def _confirm_dataset_exists(
        self, context: AnalysisContext, target_node_id: str, dataset_rid: str
    ) -> bool:
        from .dependency_internal_specs import ACP_OPERATION_SPECS
        from .foundry_internal_client import TokenExpiredError

        spec = ACP_OPERATION_SPECS["ACP-08"]
        provider = self._conjure_provider
        if provider is None:
            return False
        path = spec.path.format(rid=quote(dataset_rid, safe=""))
        try:
            result = provider.invoke(
                context,
                spec.acp_id,
                spec.verb,
                path,
                None,
                target=target_node_id,
            )
        except TokenExpiredError as error:
            self._record_lineage_token_expiry(
                context, target_node_id, spec.acp_id, path, error
            )
            return False
        except Exception as error:
            if not isinstance(
                error, BudgetExhausted
            ) and not _is_expected_collection_failure(error):
                raise
            return False
        return (
            result.coverage_status == "covered"
            and isinstance(result.payload, Mapping)
            and result.payload.get("rid") == dataset_rid
        )

    def _collect_transform_source(
        self,
        context: AnalysisContext,
        target: DependencyTarget,
        repo: Node,
        source_path: str,
        jobspec_operation_id: str,
    ) -> tuple[list[str], Optional[str]]:
        from .dependency_internal_specs import TRANSFORM_LINEAGE_GET_OPERATION_SPECS
        from .foundry_internal_client import TokenExpiredError

        assert target.node_id is not None
        spec = TRANSFORM_LINEAGE_GET_OPERATION_SPECS["ACP-03"]
        provider = self._conjure_provider
        if provider is None:
            return [], "inconclusive"
        repo_rid = repo.identifiers["resource_rid"]
        encoded_repo_rid = quote(repo_rid, safe="")
        encoded_path = quote(source_path.lstrip("/"), safe="")
        contents_path = spec.path.format(repo_rid=encoded_repo_rid, path=encoded_path)
        blame_path = f"/stemma/api/repos/{encoded_repo_rid}/paths/blame/{encoded_path}"
        results = []
        for request_path in (contents_path, blame_path):
            try:
                result = self._invoke_transform_lineage_get(
                    context,
                    spec,
                    request_path,
                    target=target.node_id,
                )
            except TokenExpiredError as error:
                self._record_lineage_token_expiry(
                    context, target.node_id, spec.acp_id, request_path, error
                )
                return [], "token-expired"
            except Exception as error:
                if not isinstance(
                    error, BudgetExhausted
                ) and not _is_expected_collection_failure(error):
                    raise
                self._add_gap(
                    context,
                    target.node_id,
                    TRANSFORM_DATASET_LINEAGE_SURFACE,
                    "inconclusive",
                    "transform-source-unresolved",
                    str(error),
                    retryable=isinstance(error, BudgetExhausted),
                    operation=spec.acp_id,
                    locator=request_path,
                )
                return [], "inconclusive"
            if result.coverage_status != "covered" or not isinstance(
                result.payload, Mapping
            ):
                status = (
                    "token-expired"
                    if result.coverage_status == "token-expired"
                    else "inconclusive"
                )
                self._add_gap(
                    context,
                    target.node_id,
                    TRANSFORM_DATASET_LINEAGE_SURFACE,
                    status,
                    result.error_class or "transform-source-unresolved",
                    "ACP-03 could not resolve transform source and blame",
                    retryable=result.retryable,
                    operation=spec.acp_id,
                    locator=request_path,
                )
                return [], status
            results.append(result)
        contents_result, blame_result = results
        encoded_contents = contents_result.payload.get("fileContents")
        blame_rows = blame_result.payload.get("blameRows")
        if not isinstance(encoded_contents, str) or not isinstance(blame_rows, list):
            self._add_gap(
                context,
                target.node_id,
                TRANSFORM_DATASET_LINEAGE_SURFACE,
                "inconclusive",
                "response-shape-drift",
                "ACP-03 omitted fileContents or blameRows",
                operation=spec.acp_id,
                locator=source_path,
            )
            return [], "inconclusive"
        try:
            source = base64.b64decode(encoded_contents, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            self._add_gap(
                context,
                target.node_id,
                TRANSFORM_DATASET_LINEAGE_SURFACE,
                "unresolved",
                "transform-source-unresolved",
                str(error),
                operation=spec.acp_id,
                locator=source_path,
            )
            return [], "inconclusive"
        matches, issues = self._parse_transform_decorators(source)
        for issue in issues:
            self._add_gap(
                context,
                target.node_id,
                TRANSFORM_DATASET_LINEAGE_SURFACE,
                "unresolved",
                "transform-source-unresolved",
                issue["message"],
                operation=spec.acp_id,
                locator=f"{source_path}:{issue['line']}",
            )
        evidence_ids: list[str] = []
        unresolved = bool(issues)
        terminal_status: Optional[str] = None
        for match in matches:
            for output_path, output_line in match["outputs"]:
                resolved, resolution_status = self._resolve_compass_path(
                    context, target.node_id, output_path
                )
                if resolved is None:
                    unresolved = unresolved or resolution_status == "unresolved"
                    failure_status = resolution_status or "inconclusive"
                    if failure_status == "token-expired":
                        terminal_status = "token-expired"
                    elif terminal_status != "token-expired":
                        terminal_status = "inconclusive"
                    self._add_gap(
                        context,
                        target.node_id,
                        TRANSFORM_DATASET_LINEAGE_SURFACE,
                        failure_status,
                        "compass-path-unresolved",
                        "ACP-08 could not resolve the transform output path",
                        operation="ACP-08",
                        locator=output_path,
                    )
                    continue
                output_node = (
                    context.nodes[target.node_id]
                    if resolved == target.identifiers["resource_rid"]
                    else self._add_node(
                        context,
                        "dataset",
                        resolved,
                        {"resource_rid": resolved},
                    )
                )
                span_locator = (
                    f"{source_path}:{match['start_line']}-{match['end_line']}"
                )
                span_evidence = self._add_evidence(
                    context,
                    contents_result.operation_provenance_id,
                    span_locator,
                    "@transform",
                    source,
                    discriminator="transform",
                )
                blame_locator = self._blame_locator(blame_rows, output_line)
                if blame_locator is None:
                    unresolved = True
                    self._add_gap(
                        context,
                        target.node_id,
                        TRANSFORM_DATASET_LINEAGE_SURFACE,
                        "unresolved",
                        "blame-row-unresolved",
                        "ACP-03 blame did not cover the Output argument row",
                        operation=spec.acp_id,
                        locator=f"{source_path}:{output_line}",
                    )
                    continue
                blame_evidence = self._add_evidence(
                    context,
                    blame_result.operation_provenance_id,
                    blame_locator,
                    f"blameRows.outputLine[{output_line}]",
                    blame_rows,
                )
                jobspec_evidence = self._add_evidence(
                    context,
                    jobspec_operation_id,
                    source_path,
                    "sourcePath",
                    source_path,
                )
                evidence_ids.extend(
                    [span_evidence.id, blame_evidence.id, jobspec_evidence.id]
                )
                self._add_edge(
                    context,
                    repo.id,
                    output_node.id,
                    "code-repo-builds-dataset",
                    [span_evidence.id, blame_evidence.id, jobspec_evidence.id],
                )
        if not matches and not issues:
            unresolved = True
            self._add_gap(
                context,
                target.node_id,
                TRANSFORM_DATASET_LINEAGE_SURFACE,
                "unresolved",
                "transform-source-unresolved",
                "No canonical @transform decorator was found",
                operation=spec.acp_id,
                locator=source_path,
            )
        return evidence_ids, terminal_status or ("unresolved" if unresolved else None)

    def _resolve_compass_path(
        self, context: AnalysisContext, target_node_id: str, resource_path: str
    ) -> tuple[Optional[str], Optional[str]]:
        from .dependency_internal_specs import ACP_OPERATION_SPECS
        from .foundry_internal_client import TokenExpiredError

        spec = ACP_OPERATION_SPECS["ACP-08"]
        provider = self._conjure_provider
        if provider is None:
            return None, "inconclusive"
        path = f"/compass/api/resources?path={quote(resource_path, safe='')}"
        try:
            result = provider.invoke(
                context,
                spec.acp_id,
                spec.verb,
                path,
                None,
                target=target_node_id,
            )
        except TokenExpiredError as error:
            self._record_lineage_token_expiry(
                context, target_node_id, spec.acp_id, path, error
            )
            return None, "token-expired"
        except Exception as error:
            if not isinstance(
                error, BudgetExhausted
            ) and not _is_expected_collection_failure(error):
                raise
            return None, "inconclusive"
        if result.coverage_status != "covered" or not isinstance(
            result.payload, Mapping
        ):
            status = (
                "token-expired"
                if result.coverage_status == "token-expired"
                else "inconclusive"
            )
            return None, status
        rid = result.payload.get("rid")
        if not isinstance(rid, str) or not rid:
            return None, "inconclusive"
        return rid, None

    def _record_lineage_token_expiry(
        self,
        context: AnalysisContext,
        target_node_id: str,
        operation: str,
        locator: str,
        error: BaseException,
    ) -> None:
        record = self._coverage_record(
            context,
            "dataset",
            TRANSFORM_DATASET_LINEAGE_SURFACE,
            target_node_id,
            transport="conjure-rest",
            empty_is_inconclusive=True,
        )
        self._finish_coverage(record, "token-expired", reason="token-expired")
        self._add_gap(
            context,
            target_node_id,
            TRANSFORM_DATASET_LINEAGE_SURFACE,
            "token-expired",
            "token-expired",
            str(error),
            operation=operation,
            locator=locator,
        )

    def _invoke_build2_walk(
        self,
        context: AnalysisContext,
        target_node_id: str,
        branch: str,
        direction: str,
        body: Mapping[str, Any],
    ) -> Optional[Mapping[str, Any]]:
        """Deferred ACP-02 helper with its required-map trap enforced locally."""

        from .dependency_internal_specs import CONJURE_POST_OPERATION_SPECS
        from .foundry_internal_client import TokenExpiredError

        spec = CONJURE_POST_OPERATION_SPECS["ACP-02"]
        record = self._coverage_record(
            context,
            "dataset",
            spec.coverage_surface,
            target_node_id,
            transport=spec.transport,
            empty_is_inconclusive=True,
        )
        if direction not in {"downstream", "upstream", "connecting"}:
            raise ValueError("invalid build2 walk direction")
        fallbacks = body.get("branchFallbacks")
        path = spec.path.format(branch=quote(branch, safe=""), direction=direction)
        if not isinstance(fallbacks, Mapping) or not isinstance(
            fallbacks.get("branches"), list
        ):
            self._finish_lineage_gap(
                context,
                record,
                "inconclusive",
                "missing-required-field",
                "ACP-02 requires branchFallbacks as a map with a branches list",
                spec.acp_id,
                path,
            )
            return None
        post_spec = replace(spec, path=path)
        try:
            result = self._invoke_conjure_post(
                context, post_spec, body, raise_token_expired=True
            )
        except TokenExpiredError as error:
            self._record_lineage_token_expiry(
                context, target_node_id, spec.acp_id, path, error
            )
            return None
        if result is None:
            self._finish_lineage_gap(
                context,
                record,
                "inconclusive",
                "internal-response-inconclusive",
                "ACP-02 did not return an authoritative response",
                spec.acp_id,
                path,
            )
            return None
        payload, _operation_id = result
        if not payload:
            self._finish_lineage_gap(
                context,
                record,
                "inconclusive",
                "endpoint-empty-inconclusive",
                "An empty ACP-02 walk cannot prove absence",
                spec.acp_id,
                path,
            )
            return None
        return payload

    @staticmethod
    def _branch_jobspecs(
        payload: Mapping[str, Any],
    ) -> tuple[
        list[tuple[str, int, Mapping[str, Any]]],
        list[str],
    ]:
        jobspecs: list[tuple[str, int, Mapping[str, Any]]] = []
        shape_gaps: list[str] = []
        for branch, branch_value in sorted(
            payload.items(), key=lambda item: str(item[0])
        ):
            branch_locator = f"{branch}.jobSpecs"
            values: Any = branch_value
            if isinstance(branch_value, Mapping) and "jobSpecs" in branch_value:
                values = branch_value["jobSpecs"]
            if isinstance(values, Mapping):
                values = [values]
            if not isinstance(values, list):
                shape_gaps.append(branch_locator)
                continue
            for index, value in enumerate(values):
                if isinstance(value, Mapping):
                    jobspecs.append((str(branch), index, value))
                else:
                    shape_gaps.append(f"{branch_locator}[{index}]")
        return jobspecs, shape_gaps

    @staticmethod
    def _mapping_items(value: Any) -> Iterable[tuple[int, Mapping[str, Any]]]:
        if not isinstance(value, list):
            return ()
        return tuple(
            (index, item)
            for index, item in enumerate(value)
            if isinstance(item, Mapping)
        )

    @staticmethod
    def _first_string(value: Mapping[str, Any], *keys: str) -> Optional[str]:
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        return None

    @staticmethod
    def _dataset_locator_rid(
        spec: Mapping[str, Any], discriminator: str
    ) -> Optional[str]:
        locator = spec.get("datasetLocator")
        nested = spec.get(discriminator)
        if not isinstance(locator, Mapping) and isinstance(nested, Mapping):
            locator = nested.get("datasetLocator")
        if not isinstance(locator, Mapping):
            return None
        rid = locator.get("datasetRid")
        return rid if isinstance(rid, str) and rid else None

    @staticmethod
    def _jobspec_source_path(job_spec: Mapping[str, Any]) -> Optional[str]:
        direct = job_spec.get("sourcePath")
        if isinstance(direct, str) and direct.endswith(".py"):
            return direct
        transform_spec = job_spec.get("transformSpec")
        if isinstance(transform_spec, Mapping):
            nested = transform_spec.get("sourcePath")
            if isinstance(nested, str) and nested.endswith(".py"):
                return nested
        return None

    @staticmethod
    def _parse_transform_decorators(
        source: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            return [], [
                {
                    "line": error.lineno or 1,
                    "message": "Python transform source could not be parsed",
                }
            ]
        canonical = {"transform": False, "Input": False, "Output": False}
        transform_aliases: set[str] = set()
        for imported_node in tree.body:
            if (
                isinstance(imported_node, ast.ImportFrom)
                and imported_node.module == "transforms.api"
            ):
                for imported in imported_node.names:
                    if imported.name in canonical and imported.asname is None:
                        canonical[imported.name] = True
                    elif imported.name == "transform" and imported.asname is not None:
                        transform_aliases.add(imported.asname)
        matches: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        for function_node in ast.walk(tree):
            if not isinstance(function_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            function_unsupported = False
            for decorator in function_node.decorator_list:
                name = None
                if isinstance(decorator, ast.Call) and isinstance(
                    decorator.func, ast.Name
                ):
                    name = decorator.func.id
                if name in {
                    "transform_df",
                    "incremental",
                    "transform",
                    *transform_aliases,
                } and (name != "transform" or not all(canonical.values())):
                    issues.append(
                        {
                            "line": decorator.lineno,
                            "message": "Only canonical transforms.api @transform is supported",
                        }
                    )
                    function_unsupported = True
            if function_unsupported:
                continue
            for decorator in function_node.decorator_list:
                name = None
                if isinstance(decorator, ast.Call) and isinstance(
                    decorator.func, ast.Name
                ):
                    name = decorator.func.id
                if name != "transform" or not isinstance(decorator, ast.Call):
                    continue
                calls = [
                    value
                    for value in [
                        *decorator.args,
                        *(kw.value for kw in decorator.keywords),
                    ]
                    if isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in {"Input", "Output"}
                ]
                inputs: list[tuple[str, int]] = []
                outputs: list[tuple[str, int]] = []
                invalid = False
                for call in calls:
                    if (
                        len(call.args) != 1
                        or call.keywords
                        or not isinstance(call.args[0], ast.Constant)
                        or not isinstance(call.args[0].value, str)
                    ):
                        invalid = True
                        issues.append(
                            {
                                "line": call.lineno,
                                "message": "Input and Output paths must be string literals",
                            }
                        )
                        continue
                    item = (call.args[0].value, call.args[0].lineno)
                    call_name = (
                        call.func.id if isinstance(call.func, ast.Name) else None
                    )
                    if call_name == "Input":
                        inputs.append(item)
                    else:
                        outputs.append(item)
                if (
                    invalid
                    or not outputs
                    or len(outputs) > 1
                    or len(calls) != len(decorator.args) + len(decorator.keywords)
                ):
                    if not invalid:
                        issues.append(
                            {
                                "line": outputs[1][1]
                                if len(outputs) > 1
                                else decorator.lineno,
                                "message": (
                                    "Only one literal Output is supported"
                                    if len(outputs) > 1
                                    else "Transform arguments must be literal Input/Output calls"
                                ),
                            }
                        )
                    continue
                matches.append(
                    {
                        "inputs": inputs,
                        "outputs": outputs,
                        "start_line": decorator.lineno,
                        "end_line": decorator.end_lineno or decorator.lineno,
                    }
                )
        return matches, issues

    @staticmethod
    def _blame_locator(blame_rows: Sequence[Any], output_line: int) -> Optional[str]:
        for index, row in enumerate(blame_rows):
            if not isinstance(row, Mapping):
                continue
            exact = row.get("lineNumber", row.get("rowNumber", row.get("row")))
            start = row.get("startLine")
            end = row.get("endLine")
            if exact == output_line or (
                isinstance(start, int)
                and isinstance(end, int)
                and start <= output_line <= end
            ):
                return f"blameRows[{index}]@{output_line}"
        return None

    def _finish_lineage_gap(
        self,
        context: AnalysisContext,
        record: CoverageRecord,
        status: str,
        reason: str,
        message: str,
        operation: str,
        locator: str,
    ) -> None:
        self._finish_coverage(record, status, reason=reason)
        self._add_gap(
            context,
            record.subject_node_id,
            record.surface,
            status,
            reason,
            message,
            operation=operation,
            locator=locator,
        )

    @staticmethod
    def _remove_operation_gaps(
        context: AnalysisContext,
        subject_node_id: str,
        surface: str,
        operation: str,
    ) -> None:
        for gap_id, gap in list(context.gaps.items()):
            if (
                gap.target == subject_node_id
                and gap.surface == surface
                and gap.operation == operation
            ):
                context.gaps.pop(gap_id, None)

    def _collect_schedule(
        self,
        context: AnalysisContext,
        root: DependencyTarget,
        schedule_node: Node,
        orchestration: OrchestrationService,
        records: Mapping[str, CoverageRecord],
    ) -> None:
        try:
            self._collect_schedule_impl(
                context, root, schedule_node, orchestration, records
            )
        except BudgetExhausted as error:
            record = next(
                (
                    records[surface]
                    for surface in (
                        "schedule-detail-action",
                        "schedule-trigger",
                        "schedule-affected-resources",
                        "schedule-runs",
                    )
                    if not records[surface].complete
                ),
                records["schedule-runs"],
            )
            prefixes = {
                "schedule-detail-action": ("action.", "scope_mode."),
                "schedule-trigger": ("trigger",),
                "schedule-affected-resources": ("affectedResources[",),
                "schedule-runs": ("runs[",),
            }
            subject_evidence = {
                evidence_id
                for edge in context.edges.values()
                if schedule_node.id in {edge.source, edge.target}
                for evidence_id in edge.evidence_ids
            }
            partial_evidence = [
                evidence.id
                for evidence in context.evidence.values()
                if evidence.id in subject_evidence
                and evidence.locator.startswith(prefixes.get(record.surface, ()))
            ]
            self._record_failure(
                context,
                record,
                error,
                "schedule-metadata-walk",
                evidence_ids=[*record.evidence_ids, *partial_evidence],
            )

    def _collect_schedule_impl(
        self,
        context: AnalysisContext,
        root: DependencyTarget,
        schedule_node: Node,
        orchestration: OrchestrationService,
        records: Mapping[str, CoverageRecord],
    ) -> None:
        schedule_rid = schedule_node.identifiers["schedule_rid"]
        detail_evidence: list[str] = []
        try:
            detail, operation_id = self._invoke_sdk(
                context,
                "schedule.get",
                orchestration.get_schedule,
                {"schedule_rid": schedule_rid, "preview": True},
                target=schedule_rid,
            )
        except Exception as error:
            self._record_failure(
                context, records["schedule-detail-action"], error, "schedule.get"
            )
            self._record_failure(
                context, records["schedule-trigger"], error, "schedule.get"
            )
        else:
            action = detail.get("action") or {}
            target_value = action.get("target") or {}
            target_type = target_value.get("type")
            detail_status = "covered"
            detail_reason: Optional[str] = None
            if (
                not action
                or not target_value
                or target_type
                not in {
                    "manual",
                    "upstream",
                    "connecting",
                }
            ):
                detail_status = "unresolved"
                detail_reason = "invalid-schedule-action-target"
                self._add_gap(
                    context,
                    schedule_node.id,
                    "schedule-detail-action",
                    "unresolved",
                    "invalid-schedule-action-target",
                    "Schedule.action.target is missing, malformed, or has an unknown discriminator",
                )
            for field_name, relation, source_is_resource in (
                ("input_rids", "schedule-consumes-resource", True),
                ("target_rids", "schedule-produces-resource", False),
            ):
                for index, resource_rid in enumerate(
                    target_value.get(field_name, []) or []
                ):
                    context.budget.charge("items")
                    locator = f"action.target.{field_name}[{index}]"
                    evidence = self._add_evidence(
                        context,
                        operation_id,
                        locator,
                        locator,
                        resource_rid,
                        target_type,
                    )
                    detail_evidence.append(evidence.id)
                    resource_node = self._add_node(
                        context,
                        self._kind_from_rid(str(resource_rid)),
                        str(resource_rid),
                        {"resource_rid": str(resource_rid)},
                    )
                    source, edge_target = (
                        (resource_node.id, schedule_node.id)
                        if source_is_resource
                        else (schedule_node.id, resource_node.id)
                    )
                    self._add_edge(
                        context, source, edge_target, relation, [evidence.id]
                    )
            if target_type == "upstream":
                if detail_status != "unresolved":
                    detail_status = "partial"
                    detail_reason = "dataset-resolved-upstream-lineage"
                self._add_gap(
                    context,
                    schedule_node.id,
                    "schedule-detail-action",
                    "partial",
                    "dataset-resolved-upstream-lineage",
                    "The configured upstream target does not enumerate its dynamically resolved upstream closure",
                )
            scope = detail.get("scope_mode")
            if scope:
                scope_type = scope.get("type")
                if scope_type == "project":
                    for index, project_rid in enumerate(
                        scope.get("project_rids", []) or []
                    ):
                        context.budget.charge("items")
                        locator = f"scope_mode.project_rids[{index}]"
                        evidence = self._add_evidence(
                            context,
                            operation_id,
                            locator,
                            locator,
                            project_rid,
                            scope_type,
                        )
                        detail_evidence.append(evidence.id)
                        project = self._add_node(
                            context,
                            "project",
                            str(project_rid),
                            {"project_rid": str(project_rid)},
                        )
                        self._add_edge(
                            context,
                            project.id,
                            schedule_node.id,
                            "project-scope",
                            [evidence.id],
                        )
                elif scope_type != "user":
                    detail_status = "unresolved"
                    detail_reason = "unknown-schedule-scope-variant"
                    self._add_gap(
                        context,
                        schedule_node.id,
                        "schedule-detail-action",
                        "unresolved",
                        f"unknown-schedule-scope-variant:{scope_type or 'missing'}",
                        "Schedule scope has an unknown or malformed discriminator",
                    )
            else:
                detail_status = "unresolved"
                detail_reason = "unknown-schedule-scope-variant"
                self._add_gap(
                    context,
                    schedule_node.id,
                    "schedule-detail-action",
                    "unresolved",
                    "unknown-schedule-scope-variant:missing",
                    "Schedule scope is missing or malformed at scope_mode",
                )
            self._finish_coverage(
                records["schedule-detail-action"],
                detail_status
                if detail_status != "covered"
                else ("covered" if detail_evidence else "covered-empty"),
                evidence_ids=detail_evidence,
                reason=detail_reason,
            )
            trigger_evidence, trigger_gap = self._collect_trigger(
                context,
                schedule_node,
                operation_id,
                detail.get("trigger"),
                "trigger",
            )
            if trigger_gap:
                self._finish_coverage(
                    records["schedule-trigger"],
                    trigger_gap.coverage,
                    evidence_ids=trigger_evidence,
                    reason=trigger_gap.reason_code,
                )
            else:
                self._finish_coverage(
                    records["schedule-trigger"],
                    "covered" if trigger_evidence else "covered-empty",
                    evidence_ids=trigger_evidence,
                )
        self._collect_affected_resources(
            context,
            schedule_node,
            orchestration,
            records["schedule-affected-resources"],
        )
        self._collect_runs(
            context, schedule_node, orchestration, records["schedule-runs"]
        )

    def _collect_trigger(
        self,
        context: AnalysisContext,
        schedule_node: Node,
        operation_id: str,
        trigger: Optional[Mapping[str, Any]],
        locator: str,
        depth: int = 0,
    ) -> tuple[list[str], Optional[CoverageGap]]:
        evidence_ids: list[str] = []
        context.budget.check_metadata_depth(depth)
        context.budget.charge("items")
        if trigger is None:
            gap = self._add_gap(
                context,
                schedule_node.id,
                "schedule-trigger",
                "unresolved",
                "schedule-trigger-unobservable",
                f"Schedule trigger at {locator} may be omitted by permissions",
            )
            return evidence_ids, gap
        trigger_type = trigger.get("type")
        if trigger_type in {"and", "or"}:
            children = trigger.get("triggers")
            if not isinstance(children, list):
                gap = self._add_gap(
                    context,
                    schedule_node.id,
                    "schedule-trigger",
                    "unresolved",
                    "invalid-schedule-trigger",
                    f"Known trigger variant {trigger_type} is malformed at {locator}.triggers",
                )
                return evidence_ids, gap
            first_gap: Optional[CoverageGap] = None
            for index, child in enumerate(children):
                child_evidence, child_gap = self._collect_trigger(
                    context,
                    schedule_node,
                    operation_id,
                    child,
                    f"{locator}.triggers[{index}]",
                    depth + 1,
                )
                evidence_ids.extend(child_evidence)
                first_gap = first_gap or child_gap
            return evidence_ids, first_gap
        field_by_type = {
            "datasetUpdated": ("dataset_rid", "dataset"),
            "jobSucceeded": ("dataset_rid", "dataset"),
            "newLogic": ("dataset_rid", "dataset"),
            "tableUpdated": ("table_rid", "table"),
            "scheduleSucceeded": ("schedule_rid", "schedule"),
            "mediaSetUpdated": ("media_set_rid", "media-set"),
        }
        if trigger_type in {"manual", "time"}:
            return evidence_ids, None
        if trigger_type not in field_by_type:
            gap = self._add_gap(
                context,
                schedule_node.id,
                "schedule-trigger",
                "unresolved",
                f"unknown-schedule-trigger-variant:{trigger_type or 'missing'}",
                f"Unknown schedule trigger variant at {locator}",
            )
            return evidence_ids, gap
        field_name, kind = field_by_type[trigger_type]
        resource_rid = trigger.get(field_name)
        if not resource_rid:
            gap = self._add_gap(
                context,
                schedule_node.id,
                "schedule-trigger",
                "unresolved",
                "invalid-schedule-trigger",
                f"Trigger {trigger_type} is missing {field_name} at {locator}.{field_name}",
            )
            return evidence_ids, gap
        field_locator = f"{locator}.{field_name}"
        evidence = self._add_evidence(
            context,
            operation_id,
            field_locator,
            field_locator,
            resource_rid,
            str(trigger_type),
        )
        evidence_ids.append(evidence.id)
        resource = self._add_node(
            context, kind, str(resource_rid), {"resource_rid": str(resource_rid)}
        )
        self._add_edge(
            context,
            resource.id,
            schedule_node.id,
            "schedule-triggered-by-resource",
            [evidence.id],
        )
        return evidence_ids, None

    def _collect_affected_resources(
        self,
        context: AnalysisContext,
        schedule_node: Node,
        orchestration: OrchestrationService,
        record: CoverageRecord,
    ) -> None:
        try:
            response, operation_id = self._invoke_sdk(
                context,
                "schedule.get-affected-resources",
                orchestration.get_schedule_affected_resources,
                {
                    "schedule_rid": schedule_node.identifiers["schedule_rid"],
                    "preview": True,
                },
                target=schedule_node.identifiers["schedule_rid"],
            )
        except Exception as error:
            self._record_failure(
                context, record, error, "schedule.get-affected-resources"
            )
            return
        evidence_ids: list[str] = []
        for index, resource_rid in enumerate(
            response.get("affected_resources", []) or []
        ):
            context.budget.charge("items")
            locator = f"affectedResources[{index}]"
            evidence = self._add_evidence(
                context, operation_id, locator, locator, resource_rid
            )
            evidence_ids.append(evidence.id)
            resource = self._add_node(
                context,
                self._kind_from_rid(str(resource_rid)),
                str(resource_rid),
                {"resource_rid": str(resource_rid)},
            )
            self._add_edge(
                context,
                schedule_node.id,
                resource.id,
                "schedule-produces-resource",
                [evidence.id],
            )
        self._finish_coverage(
            record,
            "covered" if evidence_ids else "covered-empty",
            evidence_ids=evidence_ids,
        )

    def _collect_runs(
        self,
        context: AnalysisContext,
        schedule_node: Node,
        orchestration: OrchestrationService,
        record: CoverageRecord,
    ) -> None:
        page_token: Optional[str] = None
        run_evidence: list[str] = []
        build_work: list[tuple[Node, CoverageRecord]] = []
        try:
            while True:
                page_size = context.budget.reserve_page(100)
                kwargs: dict[str, Any] = {
                    "schedule_rid": schedule_node.identifiers["schedule_rid"],
                    "page_size": page_size,
                }
                if page_token is not None:
                    kwargs["page_token"] = page_token
                response, operation_id = self._invoke_sdk(
                    context,
                    "schedule.runs",
                    orchestration.get_schedule_runs,
                    kwargs,
                    target=schedule_node.identifiers["schedule_rid"],
                )
                runs = list(response.get("runs", []) or [])
                for index, run in enumerate(runs):
                    context.budget.charge("items")
                    result = run.get("result") or {}
                    run_rid = str(
                        run.get("rid")
                        or f"{schedule_node.identifiers['schedule_rid']}#run-{index}"
                    )
                    evidence = self._add_evidence(
                        context,
                        operation_id,
                        f"runs[{index}].result",
                        f"runs[{index}].result",
                        result,
                        result.get("type"),
                    )
                    run_evidence.append(evidence.id)
                    run_node = self._add_node(
                        context, "schedule-run", run_rid, {"run_rid": run_rid}
                    )
                    self._add_edge(
                        context,
                        schedule_node.id,
                        run_node.id,
                        "schedule-run",
                        [evidence.id],
                    )
                    if result.get("type") == "submitted" and result.get("build_rid"):
                        build_rid = str(result["build_rid"])
                        build_evidence = self._add_evidence(
                            context,
                            operation_id,
                            f"runs[{index}].result.buildRid",
                            f"runs[{index}].result.build_rid",
                            build_rid,
                            "submitted",
                        )
                        run_evidence.append(build_evidence.id)
                        build_node = self._add_node(
                            context, "build", build_rid, {"build_rid": build_rid}
                        )
                        self._add_edge(
                            context,
                            run_node.id,
                            build_node.id,
                            "run-submitted-build",
                            [build_evidence.id],
                        )
                        build_record = self._coverage_record(
                            context,
                            "build",
                            "submitted-build",
                            build_node.id,
                            parent_record_id=record.id,
                            applicability_evidence_id=build_evidence.id,
                        )
                        build_work.append((build_node, build_record))
                page_token = response.get("next_page_token")
                if not page_token:
                    break
        except Exception as error:
            self._record_failure(
                context,
                record,
                error,
                "schedule.runs",
                evidence_ids=run_evidence,
            )
            return
        self._finish_coverage(
            record,
            "covered" if run_evidence else "covered-empty",
            evidence_ids=run_evidence,
        )
        for build_node, build_record in build_work:
            self._collect_build(context, build_node, orchestration, build_record)

    def _collect_build(
        self,
        context: AnalysisContext,
        build_node: Node,
        orchestration: OrchestrationService,
        record: CoverageRecord,
    ) -> None:
        build_rid = build_node.identifiers["build_rid"]
        try:
            build, operation_id = self._invoke_sdk(
                context,
                "build.get",
                orchestration.get_build,
                {"build_rid": build_rid},
                target=build_rid,
            )
        except Exception as error:
            self._record_failure(context, record, error, "build.get")
            return
        if "target" in build:
            raise ValueError("Build response wrapper must not expose a target field")
        evidence = self._add_evidence(
            context, operation_id, "build.rid", "rid", build.get("rid", build_rid)
        )
        self._finish_coverage(record, "covered", evidence_ids=[evidence.id])
        jobs_record = self._coverage_record(
            context,
            "build",
            "build-jobs",
            build_node.id,
            parent_record_id=record.id,
            applicability_evidence_id=evidence.id,
        )
        self._collect_jobs(context, build_node, orchestration, jobs_record)

    def _collect_jobs(
        self,
        context: AnalysisContext,
        build_node: Node,
        orchestration: OrchestrationService,
        record: CoverageRecord,
    ) -> None:
        page_token: Optional[str] = None
        job_evidence: list[str] = []
        output_work: list[tuple[Node, Mapping[str, Any], str, int, CoverageRecord]] = []
        try:
            while True:
                page_size = context.budget.reserve_page(100)
                kwargs: dict[str, Any] = {
                    "build_rid": build_node.identifiers["build_rid"],
                    "page_size": page_size,
                }
                if page_token is not None:
                    kwargs["page_token"] = page_token
                response, operation_id = self._invoke_sdk(
                    context,
                    "build.jobs",
                    orchestration.get_build_jobs,
                    kwargs,
                    target=build_node.identifiers["build_rid"],
                )
                jobs = list(response.get("jobs", []) or [])
                for index, job in enumerate(jobs):
                    context.budget.charge("items")
                    job_rid = str(
                        job.get("rid")
                        or f"{build_node.identifiers['build_rid']}#job-{index}"
                    )
                    evidence = self._add_evidence(
                        context,
                        operation_id,
                        f"jobs[{index}].rid",
                        f"jobs[{index}].rid",
                        job_rid,
                    )
                    job_evidence.append(evidence.id)
                    job_node = self._add_node(
                        context, "job", job_rid, {"job_rid": job_rid}
                    )
                    self._add_edge(
                        context,
                        build_node.id,
                        job_node.id,
                        "container-member",
                        [evidence.id],
                    )
                    output_record = self._coverage_record(
                        context,
                        "job",
                        "typed-outputs",
                        job_node.id,
                        parent_record_id=record.id,
                        applicability_evidence_id=evidence.id,
                    )
                    output_work.append(
                        (job_node, job, operation_id, index, output_record)
                    )
                page_token = response.get("next_page_token")
                if not page_token:
                    break
        except Exception as error:
            self._record_failure(
                context,
                record,
                error,
                "build.jobs",
                evidence_ids=job_evidence,
            )
            return
        self._finish_coverage(
            record,
            "covered" if job_evidence else "covered-empty",
            evidence_ids=job_evidence,
        )
        for job_node, job, operation_id, job_index, output_record in output_work:
            self._collect_outputs(
                context,
                build_node,
                job_node,
                job,
                operation_id,
                job_index,
                output_record,
            )

    def _collect_outputs(
        self,
        context: AnalysisContext,
        build_node: Node,
        job_node: Node,
        job: Mapping[str, Any],
        operation_id: str,
        job_index: int,
        record: CoverageRecord,
    ) -> None:
        try:
            self._collect_outputs_impl(
                context,
                build_node,
                job_node,
                job,
                operation_id,
                job_index,
                record,
            )
        except BudgetExhausted as error:
            locator_prefix = f"jobs[{job_index}].outputs["
            partial_evidence = [
                evidence.id
                for evidence in context.evidence.values()
                if evidence.operation_provenance_id == operation_id
                and evidence.locator.startswith(locator_prefix)
            ]
            self._record_failure(
                context,
                record,
                error,
                "job-output-metadata-walk",
                evidence_ids=partial_evidence,
            )

    def _collect_outputs_impl(
        self,
        context: AnalysisContext,
        build_node: Node,
        job_node: Node,
        job: Mapping[str, Any],
        operation_id: str,
        job_index: int,
        record: CoverageRecord,
    ) -> None:
        evidence_ids: list[str] = []
        output_nodes: dict[str, tuple[Node, list[str]]] = {}
        outputs = job.get("outputs", []) or []
        for output_index, output in enumerate(outputs):
            context.budget.charge("items")
            output_type = output.get("type")
            if output_type == "datasetJobOutput":
                field_name, kind = "dataset_rid", "dataset"
            elif output_type == "transactionalMediaSetJobOutput":
                field_name, kind = "media_set_rid", "media-set"
            else:
                self._add_gap(
                    context,
                    job_node.id,
                    "typed-outputs",
                    "unresolved",
                    f"unknown-job-output-variant:{output_type or 'missing'}",
                    f"Unknown job output variant at jobs[{job_index}].outputs[{output_index}]",
                    locator=f"jobs[{job_index}].outputs[{output_index}]",
                )
                continue
            resource_rid = output.get(field_name)
            if not resource_rid:
                self._add_gap(
                    context,
                    job_node.id,
                    "typed-outputs",
                    "unresolved",
                    "invalid-response",
                    f"Typed output is missing {field_name} at jobs[{job_index}].outputs[{output_index}]",
                    locator=f"jobs[{job_index}].outputs[{output_index}].{field_name}",
                )
                continue
            locator = f"jobs[{job_index}].outputs[{output_index}].{field_name}"
            evidence = self._add_evidence(
                context,
                operation_id,
                locator,
                locator,
                resource_rid,
                output_type,
            )
            evidence_ids.append(evidence.id)
            resource = self._add_node(
                context, kind, str(resource_rid), {"resource_rid": str(resource_rid)}
            )
            existing = output_nodes.get(resource.id)
            if existing is None:
                output_nodes[resource.id] = (resource, [evidence.id])
            else:
                existing[1].append(evidence.id)
            self._add_edge(
                context,
                job_node.id,
                resource.id,
                "build-produced-output",
                [evidence.id],
            )
        # A canonical star retains co-output reachability in linear space.  A
        # clique is redundant with the shared job parent and permits one raw
        # response to create quadratic local work and artifact size.
        unique_outputs = [output_nodes[key] for key in sorted(output_nodes)]
        if unique_outputs:
            anchor, anchor_evidence = unique_outputs[0]
            for related, related_evidence in unique_outputs[1:]:
                self._add_edge(
                    context,
                    anchor.id,
                    related.id,
                    "build-co-output",
                    [*anchor_evidence, *related_evidence],
                )
        self._finish_coverage(
            record,
            "partial",
            evidence_ids=evidence_ids,
            reason="unsupported-output-kinds",
        )
        self._add_gap(
            context,
            job_node.id,
            "typed-outputs",
            "partial",
            "unsupported-output-kinds",
            "The API omits unsupported job output kinds, so typed output coverage is partial",
        )

    def _record_failure(
        self,
        context: AnalysisContext,
        record: CoverageRecord,
        error: BaseException,
        operation: str,
        *,
        evidence_ids: Sequence[str] = (),
    ) -> None:
        if not _is_expected_collection_failure(error):
            raise error
        classified = classify_exception(error)
        status = (
            "budget-exhausted"
            if classified.error_class == "budget-exhausted"
            else classified.coverage
        )
        if isinstance(error, BudgetExhausted):
            context.caches[("budget-exhausted",)] = error
        self._finish_coverage(
            record,
            status,
            reason=classified.error_class,
            attempted=True,
            evidence_ids=evidence_ids,
        )
        snapshot = error.snapshot if isinstance(error, BudgetExhausted) else None
        self._add_gap(
            context,
            record.subject_node_id,
            record.surface,
            status,
            classified.error_class,
            str(error),
            retryable=classified.retryable,
            operation=operation,
            budget_snapshot=snapshot,
        )

    def _derive_paths(
        self, context: AnalysisContext, root_node_id: str, direction: str
    ) -> list[dict[str, Any]]:
        adjacency: dict[str, list[tuple[Edge, str]]] = defaultdict(list)
        for edge in context.edges.values():
            adjacency[edge.source].append((edge, edge.target))
            adjacency[edge.target].append((edge, edge.source))
        for node_id in adjacency:
            adjacency[node_id].sort(key=lambda item: (item[0].id, item[1]))
        queue: deque[tuple[str, tuple[PathStep, ...], tuple[str, ...]]] = deque(
            [(root_node_id, (), (root_node_id,))]
        )
        best_depth: dict[str, int] = {root_node_id: 0}
        paths: list[dict[str, Any]] = []
        while queue:
            current, steps, node_ids = queue.popleft()
            depth = len(steps)
            if depth >= context.budget.max_depth:
                continue
            for edge, neighbor in adjacency.get(current, ()):
                step_direction = self._traversal_direction(edge, current)
                if neighbor in node_ids:
                    continue
                new_depth = depth + 1
                if neighbor in best_depth and best_depth[neighbor] < new_depth:
                    continue
                step = PathStep(
                    edge.id,
                    current,
                    neighbor,
                    step_direction,
                    edge.evidence_ids,
                )
                new_steps = steps + (step,)
                path_direction = self._overall_direction(new_steps)
                if direction in {"upstream", "downstream"}:
                    causal_directions = {
                        item.traversal_direction for item in new_steps
                    } - {"adjacent"}
                    opposite = "upstream" if direction == "downstream" else "downstream"
                    if opposite in causal_directions:
                        continue
                best_depth[neighbor] = new_depth
                new_nodes = node_ids + (neighbor,)
                path_id = _stable_id(
                    "path",
                    root_node_id,
                    neighbor,
                    *[item.edge_id for item in new_steps],
                )
                labels = [context.nodes[node_id].display_name for node_id in new_nodes]
                evidence_ids = tuple(
                    sorted(
                        {
                            evidence_id
                            for item in new_steps
                            for evidence_id in item.evidence_ids
                        }
                    )
                )
                path_payload = {
                    "id": path_id,
                    "root_node_id": root_node_id,
                    "related_node_id": neighbor,
                    "hop_count": new_depth,
                    "direction": path_direction,
                    "node_ids": list(new_nodes),
                    "node_labels": labels,
                    "readable_path": " -> ".join(labels),
                    "steps": [self._serialize(item) for item in new_steps],
                    "evidence_ids": list(evidence_ids),
                }
                if direction == "both" or path_direction == direction:
                    paths.append(path_payload)
                queue.append((neighbor, new_steps, new_nodes))
        return sorted(paths, key=lambda item: (item["hop_count"], item["id"]))

    @staticmethod
    def _traversal_direction(edge: Edge, from_node: str) -> str:
        if edge.traversal_class == "adjacent-structural":
            return "adjacent"
        return "downstream" if from_node == edge.source else "upstream"

    @staticmethod
    def _overall_direction(steps: Sequence[PathStep]) -> str:
        return DependencyGraphService._overall_direction_values(
            tuple(step.traversal_direction for step in steps)
        )

    @staticmethod
    def _overall_direction_values(values: Sequence[str]) -> str:
        directions = set(values) - {"adjacent"}
        if not directions or len(directions) != 1:
            return "adjacent"
        return next(iter(directions))

    def _rank_paths(
        self,
        context: AnalysisContext,
        paths: Sequence[dict[str, Any]],
        change: Optional[str],
    ) -> list[dict[str, Any]]:
        change_text = (change or "").lower()
        change_terms = {
            term
            for term in change_text.replace("-", " ").replace("_", " ").split()
            if term
        }
        semantic_relations = {
            "schema": {"property", "object-type", "link-type", "dataset", "query-type"},
            "type": {"property", "object-type", "link-type", "query-type"},
            "permission": {"project", "third-party-application", "generic-resource"},
            "schedule": {"schedule", "schedule-run", "build", "job"},
            "trigger": {"schedule", "dataset", "table", "media-set"},
            "output": {"dataset", "media-set", "build", "job"},
            "build": {"build", "job", "dataset", "media-set"},
            "function": {"function", "query-type", "action-type"},
            "action": {"action-type", "object-type", "property", "link-type"},
            "query": {"query-type", "object-type", "property"},
        }
        confidence_penalty = {
            "verified": 0,
            "partial": 1,
            "inconclusive": 2,
            "unresolved": 2,
            "unsupported": 3,
        }
        ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        for path in paths:
            final_step = path["steps"][-1]
            edge = context.edges[final_step["edge_id"]]
            severity = 0 if edge.traversal_class == "dependency-flow" else 1
            related = context.nodes[path["related_node_id"]]
            relation_terms = set(edge.relation_kind.replace("-", " ").split())
            node_terms = {
                related.kind.lower(),
                *related.display_name.lower().replace("-", " ").split(),
                *(str(value).lower() for value in related.identifiers.values()),
            }
            semantic_kinds = {
                kind
                for term in change_terms
                for kind in semantic_relations.get(term, set())
            }
            if not change_terms:
                change_relevance = 1
            elif change_terms & (relation_terms | node_terms):
                change_relevance = 0
            elif related.kind in semantic_kinds:
                change_relevance = 0
            elif semantic_kinds:
                change_relevance = 2
            else:
                change_relevance = 1
            path_coverages = [
                context.edges[step["edge_id"]].coverage for step in path["steps"]
            ]
            coverage_score = max(
                (confidence_penalty.get(value, 2) for value in path_coverages),
                default=2,
            )
            first_evidence_id = next(iter(path["evidence_ids"]), None)
            evidence_summary: Optional[dict[str, Any]] = None
            if first_evidence_id is not None:
                evidence = context.evidence[first_evidence_id]
                operation = context.operation_provenance[
                    evidence.operation_provenance_id
                ]
                evidence_summary = {
                    "evidence_id": evidence.id,
                    "locator": evidence.locator,
                    "field_path": evidence.field_path,
                    "sdk_namespace": operation.sdk_namespace,
                    "sdk_method": operation.sdk_method,
                    "transport": operation.transport,
                    "acp_id": operation.acp_id,
                }
            item = dict(path)
            item.update(
                {
                    "relation_kind": edge.relation_kind,
                    "traversal_class": edge.traversal_class,
                    "evidence_summary": evidence_summary,
                    "first_evidence_locator": evidence_summary["locator"]
                    if evidence_summary
                    else None,
                    "sdk_namespace": evidence_summary["sdk_namespace"]
                    if evidence_summary
                    else None,
                    "sdk_method": evidence_summary["sdk_method"]
                    if evidence_summary
                    else None,
                    "transport": evidence_summary["transport"]
                    if evidence_summary
                    else None,
                    "acp_id": evidence_summary["acp_id"] if evidence_summary else None,
                    "change_relevance": change_relevance,
                    "coverage_confidence": (
                        "verified"
                        if coverage_score == 0
                        else "unsupported"
                        if coverage_score == 3
                        else "inconclusive"
                        if "inconclusive" in path_coverages
                        else "partial"
                    ),
                }
            )
            ranked.append(
                (
                    (
                        path["hop_count"],
                        change_relevance,
                        coverage_score,
                        severity,
                        path["id"],
                    ),
                    item,
                )
            )
        return [item for _, item in sorted(ranked, key=lambda value: value[0])]

    def _assess_change(
        self,
        change: str,
        ranked: Sequence[dict[str, Any]],
        context: AnalysisContext,
        classification: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        impacts = [
            {
                "path_id": path["id"],
                "related_node_id": path["related_node_id"],
                "direction": path["direction"],
                "relation_kind": path["relation_kind"],
                "readable_path": path["readable_path"],
                "reason": "Direct dependency requires verification"
                if path.get("hop_count", 1) == 1
                else "Transitive dependency may require verification",
            }
            for path in ranked
        ]
        uncertainty = [
            {
                "gap_id": gap.id,
                "surface": gap.surface,
                "reason_code": gap.reason_code,
                "message": gap.message,
            }
            for _, gap in sorted(context.gaps.items())
        ]
        if classification is not None:
            verification_needed = sorted(
                {
                    str(item["subject_display_name"])
                    for bucket in (
                        "must_verify_before_merge",
                        "should_verify_before_deploy",
                    )
                    for item in classification["verification"][bucket]
                    if item.get("reason") == "impact"
                    and item.get("subject_display_name")
                }
            )
        else:
            verification_needed = sorted(
                {context.nodes[path["related_node_id"]].display_name for path in ranked}
            )
        if uncertainty:
            verification_needed.append("Resolve or accept intersecting coverage gaps")
        return {
            "change": change,
            "ranked_impacts": impacts,
            "verification_needed": verification_needed,
            "uncertainty": uncertainty,
            "assessment": "Verified relationships exist, but coverage gaps preserve uncertainty"
            if uncertainty
            else "Assessment is based on verified discovered relationships",
        }

    # --- Agent-native impact model (AU2-AU7) --------------------------------

    @staticmethod
    def _resolve_change_type(
        change: Optional[str], change_type: Optional[str]
    ) -> tuple[Optional[str], str]:
        if change_type is not None:
            if change_type not in CHANGE_TYPES:
                raise ValueError(
                    f"change_type must be one of {', '.join(CHANGE_TYPES)}"
                )
            return change_type, "explicit"
        if change:
            return DependencyGraphService._infer_change_type(change), "inferred"
        return None, "absent"

    @staticmethod
    def _infer_change_type(change: str) -> Optional[str]:
        """Best-effort heuristic from free text. Never treated as authoritative;
        callers tag the result with change_type_source="inferred"."""
        text = change.lower().replace("_", " ").replace("-", " ")
        words = set(text.split())
        if "optional" in words and "required" in words:
            if text.find("optional") < text.find("required"):
                return "optional-to-required"
            return "required-to-optional"
        if "rename" in words or "renamed" in words or "renaming" in words:
            return "rename"
        if "remove" in words or "delete" in words or "drop" in words:
            return "remove-delete"
        if "action" in words and (
            {"input", "inputs", "parameter", "parameters"} & words
        ):
            return "action-input-change"
        if "query" in words and ({"output", "outputs", "return", "returns"} & words):
            return "query-output-change"
        if "type" in words or "datatype" in words:
            return "type-change"
        return None

    @staticmethod
    def _resolve_impact_category(
        relation_kind: str,
        direction_class: str,
        change_type: Optional[str],
    ) -> str:
        if change_type is not None:
            override = IMPACT_CATEGORY_CHANGE_OVERRIDES.get(
                (change_type, relation_kind, direction_class)
            )
            if override is not None:
                return override
        direction_base = IMPACT_CATEGORY_DIRECTION_BASE.get(
            (relation_kind, direction_class)
        )
        if direction_base is not None:
            return direction_base
        return IMPACT_CATEGORY_BASE.get(relation_kind, "unknown")

    def _dedupe_ranked_impacts(
        self,
        context: AnalysisContext,
        ranked: Sequence[dict[str, Any]],
        change_type: Optional[str],
    ) -> list[dict[str, Any]]:
        """Collapse paths that reach the same related node via the same terminal
        relation and direction into one impact record (AU2). `ranked` is already
        sorted ascending by the _rank_paths sort key, so the first member seen
        per group is the representative."""
        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        order: list[tuple[str, str, str]] = []
        for path in ranked:
            direction_class = str(path.get("direction") or "adjacent")
            key = (path["related_node_id"], path["relation_kind"], direction_class)
            if key not in groups:
                related = context.nodes[path["related_node_id"]]
                hop_count = path.get("hop_count")
                if hop_count == 1:
                    severity = "direct"
                elif isinstance(hop_count, int) and hop_count > 1:
                    severity = "transitive"
                else:
                    severity = "unknown"
                category = self._resolve_impact_category(
                    path["relation_kind"], direction_class, change_type
                )
                terminal_edge_id = (
                    path["steps"][-1]["edge_id"] if path.get("steps") else None
                )
                groups[key] = {
                    "impact_id": _stable_id("impact", *key),
                    "related_node_id": path["related_node_id"],
                    "related_kind": related.kind,
                    "related_display_name": related.display_name,
                    "relation_kind": path["relation_kind"],
                    "impact_category": category,
                    "direction_class": direction_class,
                    "severity": severity,
                    "coverage_confidence": path["coverage_confidence"],
                    "hop_count": hop_count,
                    "dedupe_key": ":".join(key),
                    "terminal_edge_id": terminal_edge_id,
                    "representative_path_id": path["id"],
                    "member_path_ids": [path["id"]],
                    "representative_evidence_ids": list(path.get("evidence_ids") or []),
                    "all_member_evidence_ids": list(path.get("evidence_ids") or []),
                    "evidence_locator": path.get("first_evidence_locator"),
                    "readable_path": path.get("readable_path"),
                    "change_relevance": path.get("change_relevance", 1),
                    "why_it_matters": self._why_it_matters(
                        category,
                        path["relation_kind"],
                        related.display_name,
                        direction_class,
                    ),
                }
                order.append(key)
            else:
                record = groups[key]
                record["member_path_ids"].append(path["id"])
                for evidence_id in path.get("evidence_ids") or []:
                    if evidence_id not in record["all_member_evidence_ids"]:
                        record["all_member_evidence_ids"].append(evidence_id)
        return [groups[key] for key in order]

    @staticmethod
    def _why_it_matters(
        category: str, relation_kind: str, display_name: str, direction_class: str
    ) -> str:
        direction_phrase = {
            "downstream": "is consumed downstream by",
            "upstream": "feeds into",
            "adjacent": "is structurally coupled to",
        }.get(direction_class, "relates to")
        category_phrase = {
            "contract-break": "a contract change here can break that consumer's expected inputs or outputs",
            "schema-break": "a schema change here can invalidate that relationship's shape",
            "semantic-break": "a semantic change here can silently alter what that relationship means",
            "runtime-break": "a change here can fail at runtime when that operation executes",
            "workflow-break": "a change here can leave that workflow producing wrong state without an obvious error",
            "governance-risk": "a change here affects a permissions or scope boundary that requires review",
            "unknown": "the impact of a change here cannot be classified from observable evidence",
        }.get(category, "the impact category is unclassified")
        return (
            f"The target {direction_phrase} {display_name} via {relation_kind}; "
            f"{category_phrase}."
        )

    def _classify_agent_results(
        self,
        context: AnalysisContext,
        impacts: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        """One shared classification pass (AU4) feeding both the agent block and
        change_assessment so they can never diverge into two truths."""
        groups: dict[str, list[str]] = {
            "critical_paths": [],
            "structural_dependents": [],
            "indirect_operational_effects": [],
            "unknown_manual_verification": [],
        }
        by_id: dict[str, dict[str, Any]] = {}
        for impact in impacts:
            impact_id = impact["impact_id"]
            by_id[impact_id] = impact
            # Blast radius is structural reach, so its grouping must not move
            # when a caller supplies a different proposed change.  The public
            # impact category remains change-aware for release-risk consumers.
            relation_kind = impact.get("relation_kind")
            category = (
                self._resolve_impact_category(
                    str(relation_kind), impact["direction_class"], None
                )
                if relation_kind is not None
                else impact["impact_category"]
            )
            confidence = impact["coverage_confidence"]
            direction = impact["direction_class"]
            hop_count = impact.get("hop_count")
            if (
                direction != "adjacent"
                and hop_count == 1
                and confidence == "verified"
                and category in {"contract-break", "runtime-break"}
            ):
                groups["critical_paths"].append(impact_id)
            elif direction == "adjacent" or (
                direction != "adjacent"
                and isinstance(hop_count, int)
                and hop_count > 1
                and confidence == "verified"
                and category in {"schema-break", "semantic-break"}
            ):
                groups["structural_dependents"].append(impact_id)
            elif confidence == "unsupported" or category == "unknown":
                groups["unknown_manual_verification"].append(impact_id)
            else:
                groups["indirect_operational_effects"].append(impact_id)

        verification: dict[str, list[dict[str, Any]]] = {
            "must_verify_before_merge": [],
            "should_verify_before_deploy": [],
            "unsupported_manual_surfaces": [],
        }
        bucket_priority = {
            "unsupported_manual_surfaces": 0,
            "should_verify_before_deploy": 1,
            "must_verify_before_merge": 2,
        }
        subject_impact_ids: dict[str, list[str]] = {}
        subject_candidates: dict[str, tuple[str, dict[str, Any]]] = {}

        for impact in impacts:
            subject_impact_ids.setdefault(impact["related_node_id"], []).append(
                impact["impact_id"]
            )

        def place_subject(
            subject_node_id: str,
            bucket: str,
            *,
            subject_display_name: Optional[str],
            reason: str,
            message: str,
            gap_id: Optional[str] = None,
            coverage_record_id: Optional[str] = None,
        ) -> None:
            candidate: dict[str, Any] = {
                "subject_node_id": subject_node_id,
                "subject_display_name": subject_display_name,
                "related_impact_ids": subject_impact_ids.get(subject_node_id, []),
                "related_gap_ids": [gap_id] if gap_id is not None else [],
                "coverage_record_ids": (
                    [coverage_record_id] if coverage_record_id is not None else []
                ),
                "reason": reason,
                "message": message,
            }
            existing = subject_candidates.get(subject_node_id)
            if existing is not None:
                candidate["related_gap_ids"] = sorted(
                    set(existing[1].get("related_gap_ids", ()))
                    | set(candidate["related_gap_ids"])
                )
                candidate["coverage_record_ids"] = sorted(
                    set(existing[1].get("coverage_record_ids", ()))
                    | set(candidate["coverage_record_ids"])
                )
            if (
                existing is None
                or bucket_priority[bucket] > bucket_priority[existing[0]]
            ):
                subject_candidates[subject_node_id] = (bucket, candidate)
            elif (
                bucket == existing[0]
                and reason == "coverage-gap"
                and existing[1]["reason"] != "coverage-gap"
            ):
                # A subject-local coverage gap is the more actionable reason
                # when the subject was already promoted to this same bucket.
                subject_candidates[subject_node_id] = (bucket, candidate)
            elif existing is not None:
                existing[1]["related_gap_ids"] = candidate["related_gap_ids"]
                existing[1]["coverage_record_ids"] = candidate["coverage_record_ids"]

        for group_name, bucket in (
            ("critical_paths", "must_verify_before_merge"),
            ("structural_dependents", "should_verify_before_deploy"),
            ("indirect_operational_effects", "should_verify_before_deploy"),
            ("unknown_manual_verification", "unsupported_manual_surfaces"),
        ):
            for impact_id in groups[group_name]:
                impact = by_id[impact_id]
                effective_bucket = bucket
                if (
                    group_name == "structural_dependents"
                    and impact["coverage_confidence"] == "unsupported"
                ):
                    effective_bucket = "must_verify_before_merge"
                place_subject(
                    impact["related_node_id"],
                    effective_bucket,
                    subject_display_name=impact["related_display_name"],
                    reason="impact",
                    message=impact["why_it_matters"],
                )

        completeness = self._coverage_completeness(context, groups, by_id)

        # Every observed gap is an incomplete analysis surface.  Budget
        # truncation and other genuinely unresolved/incomplete gaps must
        # block merge.  A structurally unsupported/manual surface (a static
        # MATRIX_GAPS limitation for this target kind) is not itself a merge
        # blocker -- it routes to the unsupported-manual bucket instead,
        # unless `_gaps_touching_groups` below finds it touches a critical or
        # structural impact, in which case subject-precedence promotes it to
        # must.  Subject precedence keeps the three buckets disjoint either
        # way.
        for gap in sorted(context.gaps.values(), key=lambda value: value.id):
            node = context.nodes.get(gap.target or "")
            is_budget_truncation = (
                gap.reason_code == "budget-exhausted"
                or gap.coverage == "budget-exhausted"
            )
            if is_budget_truncation:
                bucket = "must_verify_before_merge"
            elif (
                gap.coverage == "unsupported"
                and gap.reason_code in STATIC_UNSUPPORTED_GAP_REASONS
            ):
                bucket = "unsupported_manual_surfaces"
            else:
                bucket = "must_verify_before_merge"
            reason = "budget-truncation" if is_budget_truncation else "coverage-gap"
            place_subject(
                gap.target,
                bucket,
                subject_display_name=node.display_name if node else None,
                reason=reason,
                message=gap.message,
                gap_id=gap.id,
            )

        gapped_record_keys = {
            (gap.target, gap.surface) for gap in context.gaps.values()
        }
        for record_id, record in sorted(context.coverage_records.items()):
            if (
                record.status in {"covered", "covered-empty"}
                or (record.subject_node_id, record.surface) in gapped_record_keys
            ):
                continue
            node = context.nodes.get(record.subject_node_id)
            reason = (
                "budget-truncation"
                if record.status == "budget-exhausted"
                else "coverage-gap"
            )
            place_subject(
                record.subject_node_id,
                "must_verify_before_merge",
                subject_display_name=node.display_name if node else None,
                reason=reason,
                message=(
                    f"Coverage for {record.surface} ended as "
                    f"{record.status or 'non-covered'} and must be verified."
                ),
                coverage_record_id=record_id,
            )

        # Hard invariant (AC6): a truncated or gap-riddled analysis can never
        # report an empty must-verify set.
        if completeness["budget_exhausted"] and not any(
            item[1]["reason"] == "budget-truncation"
            for item in subject_candidates.values()
        ):
            verification["must_verify_before_merge"].append(
                {
                    "subject_node_id": None,
                    "subject_display_name": None,
                    "related_impact_ids": [],
                    "related_gap_ids": [],
                    "coverage_record_ids": [],
                    "reason": "budget-truncation",
                    "message": (
                        "Discovery budget was exhausted "
                        f"({', '.join(completeness['exhausted_dimensions']) or 'unknown dimension'}); "
                        "the impact surface is incomplete and must be re-run with "
                        "higher limits or verified manually before merge."
                    ),
                }
            )
        for gap_touched in self._gaps_touching_groups(context, groups, by_id):
            place_subject(
                gap_touched.target,
                "must_verify_before_merge",
                subject_display_name=(
                    context.nodes[gap_touched.target].display_name
                    if gap_touched.target in context.nodes
                    else None
                ),
                reason="coverage-gap",
                message=(
                    "An unresolved or unsupported coverage gap touches the "
                    "critical or structural impact surface: "
                    f"{gap_touched.message}"
                ),
            )
        for subject_node_id in sorted(subject_candidates):
            bucket, item = subject_candidates[subject_node_id]
            verification[bucket].append(item)
        return {
            "groups": groups,
            "verification": verification,
            "coverage_completeness": completeness,
        }

    def _coverage_completeness(
        self,
        context: AnalysisContext,
        groups: Mapping[str, Sequence[str]],
        by_id: Mapping[str, dict[str, Any]],
    ) -> dict[str, Any]:
        exhausted_dimensions: set[str] = set()
        truncated_surfaces: set[str] = set()
        error = context.caches.get(("budget-exhausted",))
        if isinstance(error, BudgetExhausted):
            exhausted_dimensions.add(str(error.dimension))
        for gap in context.gaps.values():
            if gap.reason_code == "budget-exhausted":
                truncated_surfaces.add(gap.surface)
        for record in context.coverage_records.values():
            if record.status == "budget-exhausted":
                truncated_surfaces.add(record.surface)
        budget_exhausted = bool(exhausted_dimensions or truncated_surfaces)
        incomplete_gap_ids = sorted(context.gaps)
        incomplete_record_ids = sorted(
            record_id
            for record_id, record in context.coverage_records.items()
            if record.status not in {"covered", "covered-empty"}
        )
        return {
            "complete": not (
                budget_exhausted or incomplete_gap_ids or incomplete_record_ids
            ),
            "budget_exhausted": budget_exhausted,
            "exhausted_dimensions": sorted(exhausted_dimensions),
            "truncated_surfaces": sorted(truncated_surfaces),
            "incomplete_gap_ids": incomplete_gap_ids,
            "incomplete_record_ids": incomplete_record_ids,
        }

    @staticmethod
    def _gaps_touching_groups(
        context: AnalysisContext,
        groups: Mapping[str, Sequence[str]],
        by_id: Mapping[str, dict[str, Any]],
    ) -> list[CoverageGap]:
        touched_nodes = {
            by_id[impact_id]["related_node_id"]
            for group_name in ("critical_paths", "structural_dependents")
            for impact_id in groups[group_name]
        }
        return [
            gap
            for gap in sorted(context.gaps.values(), key=lambda value: value.id)
            if gap.coverage in {"unresolved", "unsupported"}
            and gap.target in touched_nodes
        ]

    @staticmethod
    def _budget_fingerprint(context: AnalysisContext) -> str:
        budget = context.budget
        return _stable_id(
            "budget",
            budget.max_requests,
            budget.max_pages,
            budget.max_items,
            budget.max_nodes,
            budget.max_depth,
            budget.time_budget_seconds,
        )

    def _compute_scores(
        self,
        context: AnalysisContext,
        groups: Mapping[str, Sequence[str]],
        change_type: Optional[str],
        change_type_source: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        fingerprint = self._budget_fingerprint(context)
        blast_score = min(
            100,
            sum(
                BLAST_RADIUS_WEIGHTS_V1[name] * len(groups[name])
                for name in BLAST_RADIUS_WEIGHTS_V1
            ),
        )
        blast_radius = {
            "score": blast_score,
            "weight_table_version": BLAST_RADIUS_WEIGHT_TABLE_VERSION,
            "budget_fingerprint": fingerprint,
        }
        if change_type_source == "absent":
            release_score: Optional[int] = None
        else:
            multiplier = RELEASE_RISK_MULTIPLIERS_V1.get(change_type or "", 1.0)
            release_score = min(100, round(blast_score * multiplier))
        release_risk = {
            "score": release_score,
            "weight_table_version": RELEASE_RISK_WEIGHT_TABLE_VERSION,
            "budget_fingerprint": fingerprint,
            "change_type_source": change_type_source,
        }
        return blast_radius, release_risk

    def _project_action_query_contracts(
        self,
        context: AnalysisContext,
        impacts: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """AU5: project action/query contracts from the metadata caches already
        populated during discovery. Zero new SDK operations."""
        branch = context.read_context.requested_branch
        actions: list[dict[str, Any]] = []
        queries: list[dict[str, Any]] = []
        impacted_names = {
            str(value)
            for impact in impacts
            for impacted_node in [
                context.nodes.get(str(impact.get("related_node_id") or ""))
            ]
            if impacted_node is not None
            for value in impacted_node.identifiers.values()
        }
        for node in sorted(context.nodes.values(), key=lambda value: value.id):
            if node.kind == "action-type":
                key = (
                    "action-metadata",
                    node.identifiers.get("ontology_rid"),
                    branch,
                    node.identifiers.get("action_type"),
                )
                cached = context.caches.get(key)
                if cached is None:
                    continue
                metadata = cached[0] if isinstance(cached, tuple) else cached
                actions.append(
                    self._project_action_contract(
                        context, node, metadata, impacted_names
                    )
                )
            elif node.kind == "query-type":
                key = (
                    "query-metadata",
                    node.identifiers.get("ontology_rid"),
                    branch,
                    node.identifiers.get("query_type"),
                )
                cached = context.caches.get(key)
                if cached is None:
                    continue
                metadata = cached[0] if isinstance(cached, tuple) else cached
                queries.append(self._project_query_contract(context, node, metadata))
        return {"actions": actions, "queries": queries}

    def _project_action_contract(
        self,
        context: AnalysisContext,
        node: Node,
        metadata: Any,
        impacted_names: set[str],
    ) -> dict[str, Any]:
        action_model = getattr(metadata, "action_type", None)
        parameters = getattr(action_model, "parameters", None) or {}
        if isinstance(parameters, Mapping):
            parameter_items = list(parameters.items())
        else:
            parameter_items = [
                (getattr(item, "id", None) or getattr(item, "parameter_id", ""), item)
                for item in parameters
            ]
        inputs = [
            {
                "parameter_id": str(parameter_id),
                "data_type": self._data_type_label(
                    getattr(parameter, "data_type", None)
                ),
                "required": getattr(parameter, "required", None),
            }
            for parameter_id, parameter in sorted(
                parameter_items, key=lambda pair: str(pair[0])
            )
        ]
        writes_deletes: list[dict[str, Any]] = []
        affected_fields: set[str] = set()
        for index, rule in enumerate(getattr(metadata, "full_logic_rules", []) or []):
            discriminator = (
                rule.get("type")
                if isinstance(rule, Mapping)
                else getattr(rule, "type", None)
            )
            operation: Optional[str] = None
            if str(discriminator).startswith("delete"):
                operation = "delete"
            elif str(discriminator).startswith(("create", "modify")):
                operation = "write"
            if operation is not None:
                writes_deletes.append(
                    {
                        "operation": operation,
                        "rule_index": index,
                        "type": str(discriminator),
                    }
                )
            affected_fields.update(self._property_argument_keys(rule))
        validation_risks = sorted(
            {
                str(parameter_id)
                for parameter_id, parameter in parameter_items
                if self._parameter_bound_names(parameter) & impacted_names
            }
        )
        runtime_consumers = sorted(
            {
                context.nodes[edge.target].display_name
                for edge in context.edges.values()
                if edge.relation_kind == "action-uses-function"
                and edge.source == node.id
            }
        )
        return {
            "action_type": node.identifiers.get("action_type"),
            "inputs": inputs,
            "writes_deletes": writes_deletes,
            "affected_fields": sorted(affected_fields),
            "validation_risks": validation_risks,
            "runtime_consumers": runtime_consumers,
        }

    def _project_query_contract(
        self, context: AnalysisContext, node: Node, metadata: Any
    ) -> dict[str, Any]:
        parameters = getattr(metadata, "parameters", None) or {}
        if isinstance(parameters, Mapping):
            parameter_items = list(parameters.items())
        else:
            parameter_items = [
                (getattr(item, "id", None) or getattr(item, "parameter_id", ""), item)
                for item in parameters
            ]
        inputs = [
            {
                "parameter_id": str(parameter_id),
                "data_type": self._data_type_label(
                    getattr(parameter, "data_type", None)
                ),
            }
            for parameter_id, parameter in sorted(
                parameter_items, key=lambda pair: str(pair[0])
            )
        ]
        roots = {
            f"parameters.{parameter_id}.dataType": getattr(parameter, "data_type", None)
            for parameter_id, parameter in parameter_items
        }
        roots["output"] = getattr(metadata, "output", None)
        closure = context.caches.get(("query-reference-closure", node.id))
        if not isinstance(closure, Mapping):
            try:
                closure = self._build_query_reference_closure(metadata, roots, context)
                context.caches[("query-reference-closure", node.id)] = closure
            except BudgetExhausted:
                closure = {}
        output_closure = closure.get("output") if isinstance(closure, Mapping) else None
        output_leaves = (
            output_closure.get("leaves")
            if isinstance(output_closure, Mapping)
            else None
        )
        outputs: list[dict[str, Any]]
        if output_leaves:
            outputs = [
                {
                    "data_type": str(leaf["kind"]),
                    "name": str(leaf["name"]),
                    "locator": str(leaf["locator"]),
                }
                for leaf in output_leaves
                if isinstance(leaf, Mapping)
                and leaf.get("kind")
                and leaf.get("name")
                and leaf.get("locator")
            ]
        else:
            outputs = [
                {
                    "data_type": self._data_type_label(
                        getattr(metadata, "output", None)
                    ),
                }
            ]
        accepted = sorted(
            {
                context.nodes[edge.source].display_name
                for edge in context.edges.values()
                if edge.relation_kind == "query-accepts-object"
                and edge.target == node.id
                and context.nodes[edge.source].kind in {"object-type", "interface-type"}
            }
        )
        returned_output_ids = {
            edge.target
            for edge in context.edges.values()
            if edge.relation_kind == "query-returns-object" and edge.source == node.id
        }
        downstream_consumers = sorted(
            {
                context.nodes[edge.target].display_name
                for edge in context.edges.values()
                if edge.source in returned_output_ids
                and edge.traversal_class == "dependency-flow"
                and edge.target in context.nodes
                and edge.target != node.id
                and edge.target not in returned_output_ids
            }
        )
        unresolved = sorted(
            {
                gap.message
                for gap in context.gaps.values()
                if gap.target in {node.id, *returned_output_ids}
                and gap.surface == "query-related-function-metadata"
            }
        )
        return {
            "query_type": node.identifiers.get("query_type"),
            "inputs": inputs,
            "outputs": outputs,
            "input_producers": accepted,
            "likely_downstream_consumers": downstream_consumers,
            "unresolved_consumers": unresolved,
        }

    @staticmethod
    def _data_type_label(data_type: Any) -> Optional[str]:
        if data_type is None:
            return None
        label = (
            data_type.get("type")
            if isinstance(data_type, Mapping)
            else getattr(data_type, "type", None)
        )
        return str(label) if label is not None else None

    def _property_argument_keys(self, value: Any) -> set[str]:
        keys: set[str] = set()
        work: list[Any] = [value]
        seen = 0
        while work and seen < 500:
            seen += 1
            item = work.pop()
            if item is None or isinstance(item, (str, bool, int, float)):
                continue
            if isinstance(item, Mapping):
                for key, child in item.items():
                    if str(key).endswith(
                        ("propertyArguments", "sharedPropertyArguments")
                    ) and isinstance(child, Mapping):
                        keys.update(str(name) for name in child.keys())
                    work.append(child)
                continue
            if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
                work.extend(item)
                continue
            for name, child in self._declared_fields(item):
                if name.endswith(("property_arguments", "shared_property_arguments")):
                    if isinstance(child, Mapping):
                        keys.update(str(entry) for entry in child.keys())
                work.append(child)
        return keys

    def _parameter_bound_names(self, parameter: Any) -> set[str]:
        names: set[str] = set()
        data_type = getattr(parameter, "data_type", None)
        if data_type is None:
            return names
        work: list[Any] = [data_type]
        seen = 0
        while work and seen < 100:
            seen += 1
            item = work.pop()
            if item is None or isinstance(item, (bool, int, float)):
                continue
            if isinstance(item, str):
                continue
            if isinstance(item, Mapping):
                for key, child in item.items():
                    if str(key) in {
                        "objectTypeApiName",
                        "objectApiName",
                        "object_type_api_name",
                        "object_api_name",
                        "propertyTypeApiName",
                        "property_type_api_name",
                        "linkTypeApiName",
                        "link_type_api_name",
                        "sharedPropertyTypeRid",
                        "shared_property_type_rid",
                    } and isinstance(child, str):
                        names.add(child)
                    work.append(child)
                continue
            if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
                work.extend(item)
                continue
            for name, child in self._declared_fields(item):
                if name in {
                    "object_type_api_name",
                    "object_api_name",
                    "property_type_api_name",
                    "link_type_api_name",
                    "shared_property_type_rid",
                } and isinstance(child, str):
                    names.add(child)
                work.append(child)
        return names

    def _diff_graphs(
        self,
        context: AnalysisContext,
        baseline: Mapping[str, Any],
        impacts: Sequence[dict[str, Any]],
        completeness: Mapping[str, Any],
        target: Optional[DependencyTarget] = None,
    ) -> dict[str, Any]:
        """AU6: edge_id-only diff against a prior artifact. Evidence ids are
        timestamp-embedded and never compared."""
        baseline_edges = {
            str(edge["id"]): edge
            for edge in (baseline.get("graph") or {}).get("edges") or []
            if isinstance(edge, Mapping) and edge.get("id")
        }
        current_edges = context.edges
        added = sorted(set(current_edges) - set(baseline_edges))
        removed_ids = sorted(set(baseline_edges) - set(current_edges))

        baseline_nodes = {
            str(node["id"]): node
            for node in (baseline.get("graph") or {}).get("nodes") or []
            if isinstance(node, Mapping) and node.get("id")
        }

        def node_identity(
            node: Mapping[str, Any],
        ) -> Optional[tuple[str, tuple[tuple[str, str], ...]]]:
            identifiers = node.get("identifiers")
            if not isinstance(identifiers, Mapping) or not identifiers:
                return None
            return (
                str(node.get("kind") or ""),
                tuple(
                    sorted((str(key), str(value)) for key, value in identifiers.items())
                ),
            )

        current_by_identity = {
            identity: node.id
            for node in context.nodes.values()
            if (identity := node_identity(self._serialize(node))) is not None
        }
        reached_aliases: dict[str, str] = {
            node_id: node_id for node_id in context.nodes
        }
        for baseline_node_id, baseline_node in baseline_nodes.items():
            identity = node_identity(baseline_node)
            if identity is not None and identity in current_by_identity:
                reached_aliases[baseline_node_id] = current_by_identity[identity]

        locally_truncated_subjects = {
            gap.target
            for gap in context.gaps.values()
            if gap.reason_code == "budget-exhausted"
            or gap.coverage == "budget-exhausted"
        } | {
            record.subject_node_id
            for record in context.coverage_records.values()
            if record.status == "budget-exhausted"
        }

        baseline_ids_by_current = {
            current_id: baseline_id
            for baseline_id, current_id in reached_aliases.items()
        }
        uncertain_nodes = {
            baseline_ids_by_current.get(subject, subject)
            for subject in locally_truncated_subjects
        }
        reached_baseline_nodes = {
            baseline_id
            for baseline_id, current_id in reached_aliases.items()
            if current_id in context.nodes
        }
        baseline_adjacency: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for edge in baseline_edges.values():
            source = str(edge.get("source") or "")
            edge_target = str(edge.get("target") or "")
            baseline_adjacency[source].append(edge)
            baseline_adjacency[edge_target].append(edge)
        requested_direction = str(context.caches.get(("requested-direction",), "both"))

        def can_propagate(edge: Mapping[str, Any], from_node: str) -> bool:
            if str(edge.get("traversal_class") or "") == "adjacent-structural":
                return True
            if requested_direction == "adjacent":
                return False
            if requested_direction == "downstream":
                return from_node == str(edge.get("source") or "")
            if requested_direction == "upstream":
                return from_node == str(edge.get("target") or "")
            return True

        uncertain_edge_ids: set[str] = set()
        frontier = deque(sorted(uncertain_nodes))
        while frontier:
            frontier_node = frontier.popleft()
            for edge in sorted(
                baseline_adjacency.get(frontier_node, ()),
                key=lambda value: str(value.get("id") or ""),
            ):
                edge_id = str(edge.get("id") or "")
                if edge_id not in removed_ids or not can_propagate(edge, frontier_node):
                    continue
                source = str(edge.get("source") or "")
                edge_target = str(edge.get("target") or "")
                other = edge_target if frontier_node == source else source
                # The edge itself is ambiguous the moment it is adjacent to a
                # locally-truncated frontier node -- truncation could have
                # cut this exact edge regardless of whether its far endpoint
                # happens to be independently reached elsewhere.  Only stop
                # *propagating further* past an independently-reached node;
                # never suppress the frontier edge's own uncertainty.
                uncertain_edge_ids.add(edge_id)
                if other in reached_baseline_nodes and other not in uncertain_nodes:
                    continue
                if other not in uncertain_nodes:
                    uncertain_nodes.add(other)
                    frontier.append(other)

        def possibly_budget_truncated(edge: Mapping[str, Any]) -> bool:
            if not completeness.get("budget_exhausted"):
                return False
            return str(edge.get("id") or "") in uncertain_edge_ids

        removed = [
            {
                "edge_id": edge_id,
                "possibly_budget_truncated": possibly_budget_truncated(
                    baseline_edges[edge_id]
                ),
            }
            for edge_id in removed_ids
        ]
        changed = [
            {
                "edge_id": edge_id,
                "from_coverage": baseline_edges[edge_id].get("coverage"),
                "to_coverage": current_edges[edge_id].coverage,
            }
            for edge_id in sorted(set(baseline_edges) & set(current_edges))
            if baseline_edges[edge_id].get("coverage")
            != current_edges[edge_id].coverage
        ]
        baseline_contexts = baseline.get("read_contexts") or []
        baseline_context = baseline_contexts[0] if baseline_contexts else {}
        baseline_target = baseline.get("target") or {}
        current_target = target
        if current_target is None:
            target_nodes = [node for node in context.nodes.values() if node.is_target]
            if len(target_nodes) == 1:
                target_node = target_nodes[0]
                current_target = DependencyTarget(
                    target_node.kind,
                    target_node.identifiers,
                    target_node.display_name,
                    target_node.id,
                )

        def target_identity(value: Any) -> Optional[tuple[str, Any]]:
            if isinstance(value, DependencyTarget):
                kind = value.kind
                identifiers: Any = value.identifiers
                node_id = value.node_id
            elif isinstance(value, Mapping):
                kind = str(value.get("kind") or "")
                identifiers = value.get("identifiers")
                node_id = value.get("node_id")
            else:
                return None
            if isinstance(identifiers, Mapping) and identifiers:
                return (
                    str(kind),
                    tuple(
                        sorted(
                            (str(key), str(identifier))
                            for key, identifier in identifiers.items()
                        )
                    ),
                )
            if node_id:
                return (str(kind), str(node_id))
            return None

        budget_keys = (
            "requests",
            "pages",
            "items",
            "nodes",
            "depth",
            "time_budget_seconds",
        )
        baseline_limits = (baseline.get("budget") or {}).get("limits") or {}
        current_limits = context.budget.snapshot()["limits"]
        comparable = (
            target_identity(baseline_target) == target_identity(current_target)
            and baseline_context.get("ontology_rid")
            == context.read_context.ontology_rid
            and baseline_context.get("requested_branch")
            == context.read_context.requested_branch
            and all(
                baseline_limits.get(key) == current_limits.get(key)
                for key in budget_keys
            )
        )
        added_set = set(added)
        newly_introduced = sorted(
            {
                impact["impact_id"]
                for impact in impacts
                if impact.get("terminal_edge_id") in added_set
            }
        )
        baseline_artifact = baseline.get("artifact") or {}
        return {
            "compared_against": baseline_artifact.get("analysis_id"),
            "comparable": comparable,
            "baseline_budget": baseline.get("budget") or {},
            "current_budget": context.budget.snapshot(),
            "added_edges": added,
            "removed_edges": removed,
            "changed_edges": changed,
            "newly_introduced_impacts": newly_introduced,
        }

    def _build_agent_block(
        self,
        context: AnalysisContext,
        target: DependencyTarget,
        change: Optional[str],
        change_type: Optional[str],
        change_type_source: str,
        impacts: Sequence[dict[str, Any]],
        classification: Mapping[str, Any],
        compare_artifact: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        groups = classification["groups"]
        verification = classification["verification"]
        completeness = classification["coverage_completeness"]
        blast_radius, release_risk = self._compute_scores(
            context, groups, change_type, change_type_source
        )
        contracts = self._project_action_query_contracts(context, impacts)
        diff = (
            self._diff_graphs(context, compare_artifact, impacts, completeness, target)
            if compare_artifact is not None
            else None
        )
        status = (
            "needs-verification"
            if verification["must_verify_before_merge"]
            else "clean"
        )
        summary = (
            f"{len(impacts)} deduped impacts: "
            f"{len(groups['critical_paths'])} critical, "
            f"{len(groups['structural_dependents'])} structural, "
            f"{len(groups['indirect_operational_effects'])} indirect, "
            f"{len(groups['unknown_manual_verification'])} unknown. "
            f"Verification: {len(verification['must_verify_before_merge'])} must / "
            f"{len(verification['should_verify_before_deploy'])} should / "
            f"{len(verification['unsupported_manual_surfaces'])} unsupported. "
            f"Coverage {'complete' if completeness['complete'] else 'truncated'}. "
            f"Status: {status}."
        )
        return {
            "schema_version": AGENT_SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "status": status,
            "summary": summary,
            "target": {
                "node_id": target.node_id,
                "kind": target.kind,
                "display_name": target.display_name,
            },
            "change": {
                "text": change,
                "change_type": change_type,
                "change_type_source": change_type_source,
            },
            "impacts": list(impacts),
            "blast_radius": {
                **blast_radius,
                "groups": {name: list(ids) for name, ids in groups.items()},
            },
            "release_risk": release_risk,
            "verification": verification,
            "coverage_completeness": completeness,
            "action_query_contracts": contracts,
            "diff": diff,
        }

    @staticmethod
    def _declared_fields(value: Any) -> list[tuple[str, Any]]:
        model_fields = getattr(type(value), "model_fields", None)
        if model_fields is not None:
            return [(name, getattr(value, name, None)) for name in sorted(model_fields)]
        if isinstance(value, Mapping):
            return [(str(name), item) for name, item in sorted(value.items())]
        return []

    @staticmethod
    def _field_alias(value: Any, name: str) -> str:
        model_fields = getattr(type(value), "model_fields", None)
        if model_fields is None or name not in model_fields:
            return name
        return str(model_fields[name].alias or name)

    @classmethod
    def _model_dict(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return {str(key): cls._model_value(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return value.model_dump(by_alias=False, mode="json")
        if hasattr(value, "dict"):
            return value.dict(by_alias=False)
        return {
            name: cls._model_value(item) for name, item in cls._declared_fields(value)
        }

    @classmethod
    def _model_value(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): cls._model_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._model_value(item) for item in value]
        if hasattr(value, "model_dump"):
            return value.model_dump(by_alias=False, mode="json")
        return value

    @staticmethod
    def _resource_type(data: Mapping[str, Any]) -> str:
        value = data.get("type") or data.get("resource_type") or ""
        if isinstance(value, Mapping):
            value = value.get("type") or value.get("name") or ""
        return str(value).strip().lower()

    @staticmethod
    def _resource_kind(resource_type: str) -> str:
        normalized = resource_type.replace("_", "-").replace(" ", "-")
        if normalized in {"dataset", "foundry-dataset"}:
            return "dataset"
        if normalized in {
            "third-party-application",
            "thirdpartyapplication",
            "third-party-applications-application",
        }:
            return "third-party-application"
        if normalized in {
            "workshop",
            "workshop-resource",
            "workshop-module",
            "workshop-state",
        }:
            return "workshop-resource"
        return "generic-resource"

    @staticmethod
    def _kind_from_rid(resource_rid: str) -> str:
        parts = resource_rid.lower().split(".")
        if "dataset" in parts:
            return "dataset"
        if "media-set" in parts or "mediaset" in parts:
            return "media-set"
        if "table" in parts:
            return "table"
        return "resource"

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, CoverageRecord):
            return dict(asdict(value), id=value.id)
        if hasattr(value, "__dataclass_fields__"):
            return asdict(value)
        return value
