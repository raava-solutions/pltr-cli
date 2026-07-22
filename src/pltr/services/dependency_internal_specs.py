"""Transport-specific registries for pinned internal dependency operations."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Mapping


PositiveControl = Callable[..., str]


def _config_gated_positive_control(
    *args: Any, enabled: bool = False, **kwargs: Any
) -> str:
    """Default-off canary hook; a later CLI unit supplies the enabled runner."""

    if not enabled:
        return "not-run"
    raise NotImplementedError("positive-control execution is not wired in Phase A U2a")


@dataclass(frozen=True)
class InternalOperationSpec:
    acp_id: str
    operation: str
    capability_ids: tuple[str, ...]
    transport: str
    verb: str
    path: str
    coverage_surface: str
    target_kind: str
    contract_pins: Mapping[str, str]
    shape_descriptor: Mapping[str, Any]
    positive_control: PositiveControl
    positive_control_enabled: bool = False
    empty_is_inconclusive: bool = True
    operation_name: str | None = None
    document_sha256: str | None = None
    page_boundary: int | None = None


_PINS = {"mcp": "0.397.0", "verified_on": "2026-07-21"}

ACP_05_DEPENDENTS_PAGE_BOUNDARY = 50

GET_OBJECT_TYPE_DEPENDENTS_QUERY = """query GetObjectTypeDependents($rid: RID!) {
  objectTypeV2(identifier: {rid: $rid}) {
    rid
    dependents {
      values {
        ... on ResourceMetadata {
          rid
          name
          description
          path
          type { name }
          parent { rid name path }
          projectRid
        }
      }
      nextPageToken
    }
  }
}"""


ACP_OPERATION_SPECS: dict[str, InternalOperationSpec] = {
    "ACP-04": InternalOperationSpec(
        acp_id="ACP-04",
        operation="object-type.get-with-datasources",
        capability_ids=("CAP-14",),
        transport="conjure-rest",
        verb="GET",
        path=(
            "/api/v2/ontologies/{ontology}/objectTypes/{object_type}"
            "?includeDatasources=true&preview=true"
        ),
        coverage_surface="property-column-mapping",
        target_kind="property",
        contract_pins=_PINS,
        shape_descriptor={
            "required": ("datasources",),
            "empty_fields": ("datasources",),
            "list_items": {
                "datasources": {
                    "required": ("definition",),
                    "mapping_fields": {
                        "definition": {
                            "required": ("type",),
                            "conditional_required": {
                                "type": {"dataset": ("propertyMapping",)}
                            },
                        }
                    },
                }
            },
        },
        positive_control=_config_gated_positive_control,
    ),
    "ACP-08": InternalOperationSpec(
        acp_id="ACP-08",
        operation="compass.get-resource-name",
        capability_ids=("CAP-16",),
        transport="conjure-rest",
        verb="GET",
        path="/compass/api/resources/{rid}?decoration=path",
        coverage_surface="compass-metadata",
        target_kind="generic-resource",
        contract_pins=_PINS,
        shape_descriptor={"required": ("rid",)},
        positive_control=_config_gated_positive_control,
    ),
}


GRAPHQL_OPERATION_SPECS: dict[str, InternalOperationSpec] = {
    "ACP-05": InternalOperationSpec(
        acp_id="ACP-05",
        operation="object-type.get-dependents",
        capability_ids=("CAP-10",),
        transport="graphql-sse",
        verb="POST",
        path="/graphql-gateway/api/bulk",
        coverage_surface="object-type-consumers",
        target_kind="object-type",
        contract_pins=_PINS,
        shape_descriptor={
            "required": ("objectTypeV2",),
            "mapping_fields": {
                "objectTypeV2": {
                    "required": ("rid", "dependents"),
                    "mapping_fields": {
                        "dependents": {"required": ("values", "nextPageToken")}
                    },
                }
            },
        },
        positive_control=_config_gated_positive_control,
        operation_name="GetObjectTypeDependents",
        document_sha256=sha256(
            GET_OBJECT_TYPE_DEPENDENTS_QUERY.encode("utf-8")
        ).hexdigest(),
        page_boundary=ACP_05_DEPENDENTS_PAGE_BOUNDARY,
    ),
}


CONJURE_POST_OPERATION_SPECS: dict[str, InternalOperationSpec] = {
    "ACP-06": InternalOperationSpec(
        acp_id="ACP-06",
        operation="monocle.graph-v3",
        capability_ids=("CAP-10",),
        transport="conjure-rest",
        verb="POST",
        path="/monocle/api/links/graphV3",
        coverage_surface="object-type-consumers",
        target_kind="object-type",
        contract_pins=_PINS,
        shape_descriptor={
            "required": ("nodes",),
            "list_items": {"nodes": {"required": ("resourceIdentifier", "links")}},
        },
        positive_control=_config_gated_positive_control,
    ),
}
