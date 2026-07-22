"""Phase A registry for pinned internal dependency-provider operations."""

from __future__ import annotations

from dataclasses import dataclass
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


_PINS = {"mcp": "0.397.0", "verified_on": "2026-07-21"}


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
