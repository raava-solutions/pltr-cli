"""Optional, failure-safe Langfuse tracing for CLI invocations."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar


T = TypeVar("T")

REDACTED = "[REDACTED]"

_LANGFUSE_HOST_ENV_NAMES = ("LANGFUSE_BASE_URL", "LANGFUSE_HOST")
_LANGFUSE_CREDENTIAL_ENV_NAMES = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)
_SENSITIVE_ENV_NAME_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL|AUTH)",
    re.IGNORECASE,
)
_SENSITIVE_ENV_NAMES = {
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
}
_SENSITIVE_FLAG_NAMES = {
    "--access-key",
    "--access-token",
    "--api-key",
    "--api_key",
    "--api-token",
    "--auth-token",
    "--bearer-token",
    "--client-secret",
    "--client_secret",
    "--credential",
    "--credentials",
    "--foundry-token",
    "--langfuse-public-key",
    "--langfuse-secret-key",
    "--password",
    "--passwd",
    "--private-key",
    "--secret",
    "--secret-key",
    "--token",
}


def _is_sensitive_env_name(name: str) -> bool:
    normalized = name.upper()
    return normalized in _SENSITIVE_ENV_NAMES or bool(
        _SENSITIVE_ENV_NAME_RE.search(normalized)
    )


def _configured_secret_values(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return non-empty values from credential-like environment variables."""
    values = (os.environ if environ is None else environ).items()
    return tuple(
        sorted(
            {value for name, value in values if value and _is_sensitive_env_name(name)},
            key=len,
            reverse=True,
        )
    )


def _replace_secrets(value: str, secret_values: Iterable[str]) -> str:
    for secret in secret_values:
        value = value.replace(secret, REDACTED)
    return value


def redact_args(
    args: Sequence[str],
    *,
    secret_values: Iterable[str] | None = None,
) -> list[str]:
    """Redact known secret options and configured secret values from argv."""
    secrets = tuple(
        secret_values if secret_values is not None else _configured_secret_values()
    )
    redacted: list[str] = []
    redact_next = False

    for arg in args:
        if redact_next:
            redacted.append(REDACTED)
            redact_next = False
            continue

        flag, separator, _ = arg.partition("=")
        if flag.lower() in _SENSITIVE_FLAG_NAMES:
            redacted.append(f"{flag}={REDACTED}" if separator else flag)
            redact_next = not separator
            continue

        redacted.append(_replace_secrets(arg, secrets))

    return redacted


def command_paths_for_app(typer_app: Any) -> tuple[tuple[str, ...], ...]:
    """Collect leaf command paths from a Typer app without invoking it."""
    paths: list[tuple[str, ...]] = []

    for group in typer_app.registered_groups:
        name = group.name
        if not name:
            continue
        child_paths = command_paths_for_app(group.typer_instance)
        if child_paths:
            paths.extend((name, *child_path) for child_path in child_paths)
        else:
            paths.append((name,))

    for command in typer_app.registered_commands:
        name = command.name or command.callback.__name__.replace("_", "-")
        paths.append((name,))

    return tuple(paths)


def command_path_from_argv(
    args: Sequence[str],
    command_paths: Iterable[Sequence[str]],
) -> str:
    """Resolve the user-facing ``pltr ...`` command path from argv."""
    remaining = list(args)
    while remaining and remaining[0].startswith("-"):
        remaining.pop(0)

    for path in sorted(command_paths, key=len, reverse=True):
        normalized_path = tuple(path)
        if tuple(remaining[: len(normalized_path)]) == normalized_path:
            return "pltr " + " ".join(normalized_path)

    return "pltr"


def _create_langfuse_client(
    *,
    host: str,
    public_key: str,
    secret_key: str,
) -> Any:
    """Create a client while keeping the optional import lazy."""
    Langfuse = import_module("langfuse").Langfuse

    return Langfuse(host=host, public_key=public_key, secret_key=secret_key)


def _exit_code(error: BaseException) -> int:
    if isinstance(error, SystemExit):
        if error.code is None:
            return 0
        return error.code if isinstance(error.code, int) else 1
    if isinstance(error, KeyboardInterrupt):
        return 130
    return 1


@dataclass
class LangfuseTracer:
    """A small adapter around the optional Langfuse client."""

    client: Any
    secret_values: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> LangfuseTracer | None:
        host = next(
            (
                os.environ.get(name)
                for name in _LANGFUSE_HOST_ENV_NAMES
                if os.environ.get(name)
            ),
            None,
        )
        public_key, secret_key = (
            os.environ.get(name) for name in _LANGFUSE_CREDENTIAL_ENV_NAMES
        )
        if not host or not public_key or not secret_key:
            return None

        try:
            client = _create_langfuse_client(
                host=host,
                public_key=public_key,
                secret_key=secret_key,
            )
        except Exception:
            return None

        return cls(client=client, secret_values=_configured_secret_values())

    def run(
        self,
        args: Sequence[str],
        command: Callable[[], T],
        *,
        command_paths: Iterable[Sequence[str]],
    ) -> T:
        command_path = command_path_from_argv(args, command_paths)
        try:
            observation_context = self.client.start_as_current_observation(
                as_type="span",
                name="pltr.command",
                input={
                    "command_path": command_path,
                    "args": redact_args(args, secret_values=self.secret_values),
                },
            )
            observation = observation_context.__enter__()
        except Exception:
            return command()

        started_at = time.perf_counter()
        error: BaseException | None = None
        exit_code = 0
        try:
            return command()
        except BaseException as caught:
            error = caught
            exit_code = _exit_code(caught)
            raise
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
            try:
                observation.update(
                    output={
                        "duration_ms": duration_ms,
                        "exit_code": exit_code,
                    }
                )
            except Exception:
                pass

            try:
                observation_context.__exit__(
                    type(error),
                    error,
                    error.__traceback__ if error else None,
                )
            except Exception:
                pass

            try:
                self.client.flush()
            except Exception:
                pass


def run_with_tracing(
    args: Sequence[str],
    command: Callable[[], T],
    *,
    command_paths: Iterable[Sequence[str]] = (),
) -> T:
    """Run a CLI callable with optional Langfuse tracing."""
    tracer = LangfuseTracer.from_environment()
    if tracer is None:
        return command()
    return tracer.run(args, command, command_paths=command_paths)
