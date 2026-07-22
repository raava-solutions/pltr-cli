"""Durable, same-invocation artifacts for dependency analysis."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Optional


SERIALIZED_COVERAGE_STATUSES = frozenset(
    {
        "covered",
        "covered-empty",
        "partial",
        "inconclusive",
        "token-expired",
        "inaccessible",
        "unsupported",
        "unresolved",
        "budget-exhausted",
    }
)


class ArtifactWriteError(RuntimeError):
    """Raised when the mandatory dependency artifact cannot be retained."""

    error_class = "artifact-write-failed"
    retryable = True


def _json_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if hasattr(value, "model_dump"):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_value(item) for item in value), key=_canonical_bytes)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def serialize_dependency_result(result: Any) -> dict[str, Any]:
    """Convert the service result to the complete JSON-compatible document."""
    value = _json_value(result)
    if not isinstance(value, dict):
        raise TypeError("dependency analysis result must serialize to an object")
    coverage = value.get("coverage", value.get("coverage_records", ()))
    if isinstance(coverage, list):
        for record in coverage:
            status = record.get("status") if isinstance(record, Mapping) else None
            if status is not None and status not in SERIALIZED_COVERAGE_STATUSES:
                raise ValueError(f"invalid dependency coverage status: {status}")
    gaps = value.get("gaps", ())
    if isinstance(gaps, list):
        for gap in gaps:
            status = gap.get("coverage") if isinstance(gap, Mapping) else None
            if status is not None and status not in SERIALIZED_COVERAGE_STATUSES:
                raise ValueError(f"invalid dependency gap coverage: {status}")
    return value


def _identity_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return payload content with self-referential artifact metadata removed."""
    payload = dict(_json_value(result))
    payload.pop("artifact", None)
    agent = payload.get("agent")
    if isinstance(agent, Mapping) and "artifact_reference" in agent:
        payload["agent"] = dict(agent)
        payload["agent"].pop("artifact_reference", None)
    return payload


def artifact_identity(result: Mapping[str, Any]) -> tuple[str, str]:
    """Return ``(analysis_id, sha256)`` for the non-self-referential payload.

    Top-level artifact metadata and ``agent.artifact_reference`` are deliberately
    excluded. All graph, coverage, failure, budget, evidence, and
    operation-provenance content remains inside the hash.
    """

    payload = _identity_payload(result)
    digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return f"dep-{digest[:20]}", digest


def default_artifact_path(analysis_id: str) -> Path:
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local/state"
    return (root / "pltr" / "dependency" / f"{analysis_id}.json").resolve()


def write_dependency_artifact(
    result: Mapping[str, Any], graph_output: Optional[Path | str] = None
) -> dict[str, Any]:
    """Atomically write a complete dependency result and return artifact metadata."""

    payload = _identity_payload(result)
    analysis_id, digest = artifact_identity(payload)
    destination = (
        Path(graph_output).expanduser().resolve()
        if graph_output is not None
        else default_artifact_path(analysis_id)
    )
    created_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "analysis_id": analysis_id,
        "path": str(destination),
        "sha256": digest,
        "created_at": created_at,
    }
    agent = payload.get("agent")
    if isinstance(agent, Mapping):
        payload["agent"] = {
            **agent,
            "artifact_reference": {
                "artifact_id": analysis_id,
                "path": str(destination),
                "sha256": digest,
            },
        }
    document = {**payload, "artifact": metadata}

    temporary_name: Optional[str] = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
        os.chmod(destination, 0o600)
        if os.name != "nt":
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except (OSError, TypeError, ValueError) as exc:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
        raise ArtifactWriteError(
            f"Could not write dependency graph artifact {destination}: {exc}"
        ) from exc

    return metadata
