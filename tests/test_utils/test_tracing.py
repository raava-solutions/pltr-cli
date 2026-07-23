"""Tests for optional CLI tracing and argument redaction."""

from __future__ import annotations

import pytest

from pltr.utils import tracing


class FakeObservation:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []
        self.exited = False

    def __enter__(self) -> "FakeObservation":
        return self

    def __exit__(self, *args: object) -> None:
        self.exited = True

    def update(self, **kwargs: object) -> None:
        self.updates.append(kwargs)


class FakeClient:
    def __init__(self) -> None:
        self.observation = FakeObservation()
        self.start_kwargs: dict[str, object] | None = None
        self.flush_count = 0

    def start_as_current_observation(self, **kwargs: object) -> FakeObservation:
        self.start_kwargs = kwargs
        return self.observation

    def flush(self) -> None:
        self.flush_count += 1


def test_tracing_is_noop_without_complete_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(
        tracing,
        "_create_langfuse_client",
        lambda **_: pytest.fail("Langfuse must not be imported when disabled"),
    )

    assert tracing.run_with_tracing(["hello"], lambda: "result") == "result"


def test_tracing_emits_redacted_input_and_exit_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-key")
    monkeypatch.setenv("FOUNDRY_TOKEN", "environment-token")
    monkeypatch.setattr(tracing, "_create_langfuse_client", lambda **_: client)

    result = tracing.run_with_tracing(
        [
            "resource",
            "list",
            "--token",
            "command-token",
            "--profile",
            "environment-token",
            "--api-key=api-key-value",
        ],
        lambda: "result",
        command_paths=(("resource", "list"),),
    )

    assert result == "result"
    assert client.start_kwargs == {
        "as_type": "span",
        "name": "pltr.command",
        "input": {
            "command_path": "pltr resource list",
            "args": [
                "resource",
                "list",
                "--token",
                tracing.REDACTED,
                "--profile",
                tracing.REDACTED,
                f"--api-key={tracing.REDACTED}",
            ],
        },
    }
    assert len(client.observation.updates) == 1
    output = client.observation.updates[0]["output"]
    assert isinstance(output, dict)
    assert output["duration_ms"] >= 0
    assert output["exit_code"] == 0
    assert client.observation.exited
    assert client.flush_count == 1


def test_redact_args_scrubs_known_flags_and_configured_values() -> None:
    assert tracing.redact_args(
        [
            "search",
            "--token",
            "cli-token",
            "--api-key=api-key-value",
            "--title",
            "contains-cli-token",
        ],
        secret_values=("cli-token", "api-key-value"),
    ) == [
        "search",
        "--token",
        tracing.REDACTED,
        f"--api-key={tracing.REDACTED}",
        "--title",
        f"contains-{tracing.REDACTED}",
    ]


def test_tracing_failures_do_not_change_command_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-key")

    class BrokenClient:
        def start_as_current_observation(self, **_: object) -> object:
            raise RuntimeError("tracing unavailable")

    monkeypatch.setattr(tracing, "_create_langfuse_client", lambda **_: BrokenClient())

    assert tracing.run_with_tracing(["hello"], lambda: "still works") == "still works"


def test_tracing_records_nonzero_system_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-key")
    monkeypatch.setattr(tracing, "_create_langfuse_client", lambda **_: client)

    def fail() -> None:
        raise SystemExit(7)

    with pytest.raises(SystemExit):
        tracing.run_with_tracing(["hello"], fail)

    output = client.observation.updates[0]["output"]
    assert isinstance(output, dict)
    assert output["exit_code"] == 7
