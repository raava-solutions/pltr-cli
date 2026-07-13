"""Focused tests for MCP command integration."""

import json
import stat
import subprocess
from unittest.mock import call, patch

import pytest
from typer.testing import CliRunner

from pltr.cli import app as cli_app
from pltr.commands import mcp


runner = CliRunner()


def test_mcp_help_exposes_pair_and_project_local_commands():
    """MCP help should advertise global pairing without hiding local config flows."""
    result = runner.invoke(cli_app, ["mcp", "--help"])

    assert result.exit_code == 0
    assert "Manage MCP server integration" in result.output
    assert "pair" in result.output
    assert "init" in result.output
    assert "switch" in result.output
    assert "status" in result.output


def test_pair_help_describes_claude_and_omp_user_level_pairing():
    """Pair help should make both user-level integrations explicit."""
    result = runner.invoke(cli_app, ["mcp", "pair", "--help"])
    normalized_output = " ".join(result.output.split())

    assert result.exit_code == 0
    assert "Claude Code and OMP" in normalized_output
    assert "user-level MCP" in normalized_output
    assert "pairing" in normalized_output


def test_sync_omp_mcp_preserves_unrelated_servers_and_uses_only_profile(tmp_path):
    """OMP sync should merge a token-free local wrapper into the user config."""
    config_path = tmp_path / ".omp" / "agent" / "mcp.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "$schema": "https://example.test/mcp-schema.json",
                "disabledServers": ["disabled-server"],
                "mcpServers": {
                    "unrelated": {
                        "command": "other-command",
                        "args": ["--token", "unrelated-secret"],
                    }
                },
            }
        )
    )
    config_path.chmod(0o640)

    with (
        patch.object(mcp, "_validate_profile") as validate_profile,
        patch.object(mcp, "_omp_mcp_config_path", return_value=config_path),
        patch.object(mcp, "_resolve_pltr_path", return_value="/venv/bin/pltr"),
        patch.object(mcp, "CredentialStorage") as storage_class,
    ):
        result_path = mcp.sync_omp_mcp("production")

    config = json.loads(config_path.read_text())
    assert result_path == config_path
    validate_profile.assert_called_once_with("production")
    storage_class.assert_not_called()
    assert config["$schema"] == "https://example.test/mcp-schema.json"
    assert config["disabledServers"] == ["disabled-server"]
    assert config["mcpServers"]["unrelated"] == {
        "command": "other-command",
        "args": ["--token", "unrelated-secret"],
    }
    assert config["mcpServers"]["palantir-foundry"] == {
        "type": "stdio",
        "command": "/venv/bin/pltr",
        "args": ["mcp", "serve", "--profile", "production"],
    }
    assert "foundry.example" not in repr(config["mcpServers"]["palantir-foundry"])
    assert "secret-token" not in repr(config["mcpServers"]["palantir-foundry"])
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o640
    assert list(config_path.parent.glob(".mcp.json.*")) == []


def test_sync_omp_mcp_creates_private_user_config(tmp_path):
    """A new OMP config should be created atomically with user-only permissions."""
    config_path = tmp_path / ".omp" / "agent" / "mcp.json"

    with (
        patch.object(mcp, "_validate_profile"),
        patch.object(mcp, "_omp_mcp_config_path", return_value=config_path),
        patch.object(mcp, "_resolve_pltr_path", return_value="pltr"),
    ):
        mcp.sync_omp_mcp("default")

    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert json.loads(config_path.read_text()) == {
        "mcpServers": {
            "palantir-foundry": {
                "type": "stdio",
                "command": "pltr",
                "args": ["mcp", "serve", "--profile", "default"],
            }
        }
    }


def test_sync_omp_mcp_rejects_invalid_servers_shape_without_overwriting(tmp_path):
    """Malformed OMP structure should fail closed and preserve the original file."""
    config_path = tmp_path / "mcp.json"
    original = '{"mcpServers": ["not", "an", "object"]}\n'
    config_path.write_text(original)

    with (
        patch.object(mcp, "_validate_profile"),
        patch.object(mcp, "_omp_mcp_config_path", return_value=config_path),
    ):
        with pytest.raises(mcp.OmpMcpSyncError, match="could not be synchronized"):
            mcp.sync_omp_mcp("production")

    assert config_path.read_text() == original


def test_sync_claude_mcp_constructs_token_free_stdio_commands():
    """Claude registration should delegate credentials to the local pltr wrapper."""
    token = "secret-token-that-must-not-be-forwarded"

    with (
        patch.object(mcp, "_validate_profile") as validate_profile,
        patch.object(mcp, "CredentialStorage") as storage_class,
        patch.object(
            mcp.shutil,
            "which",
            side_effect=lambda command: {
                "claude": "/usr/local/bin/claude",
                "pltr": "/repo/.venv/bin/pltr",
            }.get(command),
        ),
        patch.object(mcp.subprocess, "run") as run,
    ):
        storage_class.return_value.get_profile.return_value = {
            "host": "https://example.palantirfoundry.com",
            "token": token,
        }

        mcp.sync_claude_mcp("production")

    validate_profile.assert_called_once_with("production")
    storage_class.return_value.get_profile.assert_called_once_with("production")
    assert run.call_args_list == [
        call(
            [
                "/usr/local/bin/claude",
                "mcp",
                "remove",
                "palantir-foundry",
                "-s",
                "user",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ),
        call(
            [
                "/usr/local/bin/claude",
                "mcp",
                "add",
                "--transport",
                "stdio",
                "-s",
                "user",
                "palantir-foundry",
                "--",
                "/repo/.venv/bin/pltr",
                "mcp",
                "serve",
                "--profile",
                "production",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ),
    ]
    assert token not in repr(run.call_args_list)
    assert "palantirfoundry.com" not in repr(run.call_args_list)


def test_sync_claude_mcp_reports_missing_claude_without_subprocess():
    """A missing Claude executable should be a controlled synchronization error."""
    with (
        patch.object(mcp, "_validate_profile"),
        patch.object(mcp, "CredentialStorage") as storage_class,
        patch.object(mcp.shutil, "which", return_value=None),
        patch.object(mcp.subprocess, "run") as run,
    ):
        storage_class.return_value.get_profile.return_value = {
            "host": "https://example.palantirfoundry.com",
            "token": "secret-token",
        }

        with pytest.raises(mcp.ClaudeMcpSyncError, match="Claude Code CLI"):
            mcp.sync_claude_mcp("production")

    run.assert_not_called()


def test_sync_claude_mcp_reports_missing_token():
    """Profiles without bearer tokens cannot back the local MCP wrapper."""
    with (
        patch.object(mcp, "_validate_profile"),
        patch.object(mcp, "CredentialStorage") as storage_class,
    ):
        storage_class.return_value.get_profile.return_value = {
            "host": "https://example.palantirfoundry.com"
        }

        with pytest.raises(mcp.ClaudeMcpSyncError, match="bearer token"):
            mcp.sync_claude_mcp("production")


def test_pair_synchronizes_omp_and_claude(tmp_path):
    """Explicit pairing should report both integrations without credential output."""
    omp_path = tmp_path / "mcp.json"
    with (
        patch.object(mcp, "sync_omp_mcp", return_value=omp_path) as sync_omp,
        patch.object(mcp, "sync_claude_mcp") as sync_claude,
    ):
        result = runner.invoke(mcp.app, ["pair", "production"])

    assert result.exit_code == 0
    sync_omp.assert_called_once_with("production")
    sync_claude.assert_called_once_with("production")
    assert "OMP MCP config synchronized" in result.output
    assert "Claude Code MCP registration synchronized" in result.output
    assert "production" in result.output
    assert "token" not in result.output.lower()
    assert "foundry URL" not in result.output


def test_pair_handles_missing_claude_gracefully():
    """The pair command should explain an unavailable Claude CLI without a traceback."""
    with (
        patch.object(mcp, "sync_omp_mcp", return_value=mcp.Path("/tmp/mcp.json")),
        patch.object(
            mcp,
            "sync_claude_mcp",
            side_effect=mcp.ClaudeMcpSyncError("Claude Code CLI not found in PATH."),
        ),
    ):
        result = runner.invoke(mcp.app, ["pair", "production"])

    assert result.exit_code == 1
    assert "OMP MCP config synchronized" in result.output
    assert "Claude Code CLI not found in PATH" in result.output
    assert result.exception is not None


def test_pair_still_synchronizes_claude_when_omp_write_fails():
    """An OMP filesystem failure should not prevent the Claude sync attempt."""
    with (
        patch.object(
            mcp,
            "sync_omp_mcp",
            side_effect=mcp.OmpMcpSyncError("OMP config is not writable."),
        ),
        patch.object(mcp, "sync_claude_mcp") as sync_claude,
    ):
        result = runner.invoke(mcp.app, ["pair", "production"])

    assert result.exit_code == 1
    sync_claude.assert_called_once_with("production")
    assert "OMP config is not writable" in result.output
    assert "Claude Code MCP registration synchronized" in result.output
