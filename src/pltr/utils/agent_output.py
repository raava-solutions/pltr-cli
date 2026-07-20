"""Shared machine-readable output and agent execution policy helpers."""

from contextvars import ContextVar
from dataclasses import dataclass, is_dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import typer

AGENT_SCHEMA_VERSION = "pltr-agent-v1"
SENSITIVE_KEY_PARTS = (
    "authorization",
    "client_secret",
    "password",
    "private_key",
    "secret",
    "token",
)


@dataclass(frozen=True)
class AgentSettings:
    """Execution settings for one CLI invocation."""

    enabled: bool = False
    non_interactive: bool = False


_settings: ContextVar[AgentSettings] = ContextVar(
    "pltr_agent_settings", default=AgentSettings()
)


class AgentPolicyError(RuntimeError):
    """Raised when an agent invocation violates an execution policy."""


def configure_agent_settings(
    *, enabled: bool = False, non_interactive: bool = False
) -> None:
    """Set agent execution settings for the current CLI invocation."""
    _settings.set(AgentSettings(enabled=enabled, non_interactive=non_interactive))


def agent_mode_enabled() -> bool:
    """Return whether the current invocation requests agent output."""
    return _settings.get().enabled


def non_interactive_enabled() -> bool:
    """Return whether prompts are forbidden for the current invocation."""
    return _settings.get().non_interactive or agent_mode_enabled()


def resolve_output_format(format_type: str) -> str:
    """Use agent output when the invocation globally requested it."""
    if agent_mode_enabled():
        return "agent"
    return format_type


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    # Cursor continuation tokens are control-plane pagination values, not
    # credentials. They must remain visible in the agent contract so callers
    # can resume a bounded operation.
    if normalized.endswith("_page_token") or normalized == "page_token":
        return False
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def redact_value(value: Any, key: Optional[str] = None) -> Any:
    """Convert a value to JSON data while redacting credential-like fields."""
    if key and _is_sensitive_key(key):
        return "[REDACTED]"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return redact_value(vars(value))
    if isinstance(value, Mapping):
        return {
            str(item_key): redact_value(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return [redact_value(item) for item in value]
    if hasattr(value, "__dict__"):
        return redact_value(
            {
                item_key: item_value
                for item_key, item_value in vars(value).items()
                if not item_key.startswith("_")
            }
        )
    return str(value)


def agent_envelope(
    data: Any = None,
    *,
    meta: Optional[Mapping[str, Any]] = None,
    warnings: Optional[Iterable[str]] = None,
    errors: Optional[Iterable[Mapping[str, Any]]] = None,
    pagination: Optional[Mapping[str, Any]] = None,
    artifacts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the stable agent result envelope."""
    return {
        "schema_version": AGENT_SCHEMA_VERSION,
        "data": redact_value(data),
        "meta": redact_value(dict(meta or {})),
        "warnings": redact_value(list(warnings or [])),
        "errors": redact_value(list(errors or [])),
        "pagination": redact_value(dict(pagination)) if pagination else None,
        "artifacts": redact_value(list(artifacts or [])),
    }


def render_agent_json(
    data: Any = None,
    *,
    meta: Optional[Mapping[str, Any]] = None,
    warnings: Optional[Iterable[str]] = None,
    errors: Optional[Iterable[Mapping[str, Any]]] = None,
    pagination: Optional[Mapping[str, Any]] = None,
    artifacts: Optional[Iterable[Mapping[str, Any]]] = None,
) -> str:
    """Serialize an agent envelope as newline-terminated JSON."""
    return (
        json.dumps(
            agent_envelope(
                data,
                meta=meta,
                warnings=warnings,
                errors=errors,
                pagination=pagination,
                artifacts=artifacts,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def require_confirmation(
    message: str,
    *,
    confirmed: bool = False,
    option_name: str = "--force",
) -> bool:
    """Require explicit confirmation without prompting agent invocations."""
    if confirmed:
        return True
    if non_interactive_enabled():
        raise AgentPolicyError(
            f"{message} Non-interactive mode requires explicit {option_name}."
        )
    return typer.confirm(message)


def render_agent_message(
    message: str,
    *,
    level: str = "info",
) -> str:
    """Serialize a status message without Rich markup or ANSI codes."""
    warnings = [message] if level == "warning" else []
    errors = [{"type": level, "message": message}] if level == "error" else []
    return render_agent_json(
        meta={"message": message}, warnings=warnings, errors=errors
    )
