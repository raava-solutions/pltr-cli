"""Transport provider seams for dependency discovery operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Optional, Protocol, Sequence, Union

from .dependency import (
    SDK_OPERATION_SPECS,
    AnalysisContext,
    ArgumentObservation,
    DependencyFatalError,
    CoverageGap,
    SDKOperationSpec,
    OperationProvenance,
    _is_expected_collection_failure,
    _stable_id,
    _utc_now,
    classify_exception,
)


class OperationSpec(Protocol):
    """Common supertype implemented by transport-specific operation specs."""

    @property
    def capability_ids(self) -> tuple[str, ...]: ...


class InternalOperationSpec(OperationSpec, Protocol):
    """Pinned response contract required by internal transport semantics."""

    @property
    def transport(self) -> str: ...

    @property
    def empty_is_inconclusive(self) -> bool: ...

    @property
    def shape_descriptor(self) -> Mapping[str, Any]: ...


ResultSemantic = Literal[
    "ok", "empty", "truncated", "shape-drift", "permission-ambiguous"
]


@dataclass(frozen=True)
class ProviderResult:
    """Result and evidence semantics returned by a dependency provider."""

    payload: Any
    operation_provenance_id: str
    result_semantics: Optional[ResultSemantic]
    positive_control_status: str
    coverage_status: str = "covered"
    error_class: Optional[str] = None
    retryable: bool = False
    raw: str = ""


@dataclass(frozen=True)
class InternalResponseClassification:
    """Stable failure taxonomy for inspectable internal HTTP responses."""

    error_class: str
    coverage: str
    retryable: bool = False


def classify_conjure_response(
    status: int, payload: Any
) -> InternalResponseClassification:
    """Classify Conjure response planes without mistaking emptiness for safety."""

    if status == 401:
        return InternalResponseClassification("token-expired", "token-expired")
    error_name = payload.get("errorName") if isinstance(payload, Mapping) else None
    if error_name == "Route:RouteNotMounted":
        return InternalResponseClassification("route-not-mounted", "inconclusive")
    if status == 400 and error_name == "Default:InvalidArgument":
        return InternalResponseClassification(
            "missing-required-field", "inconclusive", True
        )
    if status == 422:
        return InternalResponseClassification("invalid-request", "inconclusive")
    if status == 403:
        return InternalResponseClassification("inaccessible", "inaccessible")
    if status == 200 and payload in ({}, []):
        return InternalResponseClassification("inconclusive", "inconclusive")
    if 200 <= status < 300:
        return InternalResponseClassification("ok", "covered")
    return InternalResponseClassification("internal-http-error", "inconclusive")


def _shape_matches(descriptor: Mapping[str, Any], payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    required = descriptor.get("required", ())
    if not all(key in payload for key in required):
        return False
    for key, child_descriptor in descriptor.get("mapping_fields", {}).items():
        if key in payload and not _shape_matches(child_descriptor, payload[key]):
            return False
    for key, item_descriptor in descriptor.get("list_items", {}).items():
        items = payload.get(key)
        if not isinstance(items, list) or any(
            not _shape_matches(item_descriptor, item) for item in items
        ):
            return False
    for discriminator, cases in descriptor.get("conditional_required", {}).items():
        discriminator_value = payload.get(discriminator)
        if discriminator_value in cases and not all(
            key in payload for key in cases[discriminator_value]
        ):
            return False
    return True


def ResultSemantics(
    spec: InternalOperationSpec, response: tuple[int, Any, str] | Any
) -> ResultSemantic:
    """Return the safety semantics of an internal response.

    Descriptors intentionally validate required discriminator keys only. Extra
    Conjure fields are accepted so additive server changes remain compatible.
    """

    if isinstance(response, tuple) and len(response) == 3:
        status, payload, _raw = response
    else:
        status, payload = 200, response
    if status == 403:
        return "permission-ambiguous"
    if status == 200 and payload in ({}, []):
        return "empty"
    if not 200 <= status < 300:
        return "permission-ambiguous" if status == 403 else "shape-drift"
    if isinstance(payload, Mapping) and any(
        payload.get(field) in ({}, [])
        for field in spec.shape_descriptor.get("empty_fields", ())
    ):
        return "empty"
    if not _shape_matches(spec.shape_descriptor, payload):
        return "shape-drift"
    if isinstance(payload, Mapping) and payload.get("nextPageToken") is not None:
        return "truncated"
    return "ok"


class SdkInvoke(Protocol):
    def __call__(
        self,
        context: AnalysisContext,
        operation: str,
        kwargs: Mapping[str, Any],
        *,
        target: str,
        fatal: bool = False,
        known_limitations: Sequence[dict[str, Any]] = (),
    ) -> ProviderResult: ...


class ConjureInvoke(Protocol):
    def __call__(
        self,
        context: AnalysisContext,
        operation: str,
        verb: str,
        path: str,
        body: Optional[Mapping[str, Any]],
        *,
        target: str,
    ) -> ProviderResult: ...


class GraphQLInvoke(Protocol):
    def __call__(
        self,
        context: AnalysisContext,
        operation: str,
        operation_name: str,
        document: str,
        variables_list: Sequence[Mapping[str, Any]],
        *,
        target: str,
    ) -> ProviderResult: ...


ProviderInvoke = Union[SdkInvoke, ConjureInvoke, GraphQLInvoke]


class Provider(Protocol):
    """Provider with a transport-specific invocation signature."""

    invoke: ProviderInvoke


class SdkProvider(Provider):
    """Invoke one bound Foundry SDK operation with immutable provenance."""

    def __init__(self, call: Callable[..., Any]) -> None:
        self.call = call

    def invoke(
        self,
        context: AnalysisContext,
        operation: str,
        kwargs: Mapping[str, Any],
        *,
        target: str,
        fatal: bool = False,
        known_limitations: Sequence[dict[str, Any]] = (),
    ) -> ProviderResult:
        spec: SDKOperationSpec | None = SDK_OPERATION_SPECS.get(operation)
        if spec is None:
            raise ValueError(f"unregistered SDK operation: {operation}")
        supplied = dict(kwargs)
        if "branch" in supplied and not spec.branch:
            raise ValueError(f"{operation} does not accept branch")
        if "preview" in supplied and not spec.preview:
            raise ValueError(f"{operation} does not accept preview")
        timeout = context.budget.request_timeout(
            context.configured_request_timeout_seconds
        )
        context.budget.charge("requests")
        supplied["request_timeout"] = timeout
        branch = self._argument_observation(spec.branch, supplied, "branch")
        preview = self._argument_observation(spec.preview, supplied, "preview")
        invoked_at = _utc_now()
        operation_id = _stable_id(
            "operation",
            context.read_context.id,
            operation,
            len(context.operation_provenance),
            invoked_at,
        )
        limitations = tuple(dict(value) for value in known_limitations)
        try:
            response = self.call(**supplied)
        except Exception as error:
            observed_at = _utc_now()
            context.operation_provenance[operation_id] = OperationProvenance(
                operation_id,
                context.read_context.id,
                spec.namespace,
                spec.method,
                spec.capability_ids,
                context.read_context.invocation_sdk_version,
                invoked_at,
                observed_at,
                branch,
                preview,
                timeout,
                limitations,
                transport="sdk",
            )
            classified = classify_exception(error)
            if fatal:
                if not _is_expected_collection_failure(error):
                    raise
                raise DependencyFatalError(
                    classified.error_class,
                    target,
                    operation,
                    str(error),
                    classified.retryable,
                    context.read_context.id,
                ) from error
            raise
        context.operation_provenance[operation_id] = OperationProvenance(
            operation_id,
            context.read_context.id,
            spec.namespace,
            spec.method,
            spec.capability_ids,
            context.read_context.invocation_sdk_version,
            invoked_at,
            _utc_now(),
            branch,
            preview,
            timeout,
            limitations,
            transport="sdk",
        )
        return ProviderResult(response, operation_id, "ok", "not-run")

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


class ConjureRestProvider(Provider):
    """Invoke a pinned GET-only internal REST operation fail-closed."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def invoke(
        self,
        context: AnalysisContext,
        operation: str,
        verb: str,
        path: str,
        body: Optional[Mapping[str, Any]],
        *,
        target: str,
    ) -> ProviderResult:
        from .dependency_internal_specs import ACP_OPERATION_SPECS

        spec = ACP_OPERATION_SPECS.get(operation)
        if spec is None:
            raise ValueError(f"unregistered internal operation: {operation}")
        if verb.upper() != spec.verb:
            raise ValueError(f"{operation} requires {spec.verb}")

        timeout = context.internal_budget.request_timeout(
            context.configured_request_timeout_seconds
        )
        context.internal_budget.charge("requests")
        invoked_at = _utc_now()
        operation_id = _stable_id(
            "operation",
            context.read_context.id,
            operation,
            len(context.operation_provenance),
            invoked_at,
        )
        branch = ArgumentObservation("not-applicable")
        preview = ArgumentObservation("not-applicable")
        try:
            response = self.client.conjure(
                verb,
                path,
                json_body=body,
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
                f"{operation} transport failed: {error}",
                context.read_context.id,
                transport_failure.retryable,
                operation,
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
                branch,
                preview,
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
                f"{operation} returned {semantics}; absence could not be proven",
                context.read_context.id,
                classified.retryable,
                operation,
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
