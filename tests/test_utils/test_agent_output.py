"""Tests for the stable agent output and execution policy helpers."""

import json

import pytest

from pltr.utils.agent_output import (
    AgentPolicyError,
    configure_agent_settings,
    redact_value,
    render_agent_json,
    require_confirmation,
)
from pltr.utils.formatting import OutputFormatter


def test_agent_json_has_stable_envelope_and_redacts_credentials() -> None:
    rendered = render_agent_json(
        {"name": "example", "token": "secret-value"},
        meta={"operation": "test"},
        pagination={"has_more": False},
    )

    payload = json.loads(rendered)
    assert payload["schema_version"] == "pltr-agent-v1"
    assert payload["data"] == {"name": "example", "token": "[REDACTED]"}
    assert payload["meta"] == {"operation": "test"}
    assert payload["warnings"] == []
    assert payload["errors"] == []
    assert payload["pagination"] == {"has_more": False}
    assert payload["artifacts"] == []


def test_agent_json_preserves_pagination_cursors_but_redacts_credentials() -> None:
    payload = json.loads(
        render_agent_json(
            {"token": "secret", "page_token": "cursor"},
            pagination={"next_page_token": "cursor-2"},
        )
    )

    assert payload["data"] == {
        "token": "[REDACTED]",
        "page_token": "cursor",
    }
    assert payload["pagination"]["next_page_token"] == "cursor-2"


def test_formatter_uses_agent_envelope_when_enabled(capsys) -> None:
    configure_agent_settings(enabled=True)
    try:
        OutputFormatter().format_output({"value": 3}, "table")
    finally:
        configure_agent_settings()

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "pltr-agent-v1"
    assert payload["data"] == {"value": 3}
    assert payload["meta"]["result_type"] == "dict"


def test_non_interactive_confirmation_requires_explicit_flag() -> None:
    configure_agent_settings(non_interactive=True)
    try:
        with pytest.raises(AgentPolicyError, match="explicit --force"):
            require_confirmation("Delete resource?")
        assert require_confirmation("Delete resource?", confirmed=True)
    finally:
        configure_agent_settings()


def test_redact_value_handles_nested_sensitive_keys() -> None:
    assert redact_value({"nested": {"client_secret": "secret"}}) == {
        "nested": {"client_secret": "[REDACTED]"}
    }
