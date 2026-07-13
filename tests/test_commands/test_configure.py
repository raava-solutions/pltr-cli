"""Focused tests for configure command MCP synchronization."""

from unittest.mock import patch

from typer.testing import CliRunner

from pltr.commands import configure
from pltr.commands.mcp import ClaudeMcpSyncError, OmpMcpSyncError


runner = CliRunner()


def test_set_default_synchronizes_claude_and_omp_mcp():
    """Changing the default profile should update both user-level MCP entries."""
    with (
        patch.object(configure, "ProfileManager") as manager_class,
        patch.object(configure, "sync_omp_mcp") as sync_omp_mcp,
        patch.object(configure, "sync_claude_mcp") as sync_claude_mcp,
    ):
        manager_class.return_value.list_profiles.return_value = ["production"]

        result = runner.invoke(configure.app, ["set-default", "production"])

    assert result.exit_code == 0
    manager_class.return_value.set_default.assert_called_once_with("production")
    sync_omp_mcp.assert_called_once_with("production")
    sync_claude_mcp.assert_called_once_with("production")
    assert "set as default" in result.output
    assert "OMP MCP config synchronized" in result.output
    assert "Claude Code MCP registration synchronized" in result.output


def test_set_default_warns_when_claude_is_unavailable():
    """Claude availability must not prevent the default profile from changing."""
    with (
        patch.object(configure, "ProfileManager") as manager_class,
        patch.object(configure, "sync_omp_mcp") as sync_omp_mcp,
        patch.object(
            configure,
            "sync_claude_mcp",
            side_effect=ClaudeMcpSyncError("Claude Code CLI not found in PATH."),
        ),
    ):
        manager_class.return_value.list_profiles.return_value = ["production"]

        result = runner.invoke(configure.app, ["set-default", "production"])

    assert result.exit_code == 0
    manager_class.return_value.set_default.assert_called_once_with("production")
    sync_omp_mcp.assert_called_once_with("production")
    assert "set as default" in result.output
    assert "OMP MCP config synchronized" in result.output
    assert "Warning" in result.output
    assert "Claude Code CLI not found in PATH" in result.output


def test_set_default_warns_when_claude_sync_fails():
    """A Claude command failure must remain best-effort for profile switching."""
    with (
        patch.object(configure, "ProfileManager") as manager_class,
        patch.object(configure, "sync_omp_mcp"),
        patch.object(
            configure,
            "sync_claude_mcp",
            side_effect=ClaudeMcpSyncError("Claude MCP synchronization failed."),
        ),
    ):
        manager_class.return_value.list_profiles.return_value = ["production"]

        result = runner.invoke(configure.app, ["set-default", "production"])

    assert result.exit_code == 0
    manager_class.return_value.set_default.assert_called_once_with("production")
    assert "Warning" in result.output
    assert "Claude MCP synchronization failed" in result.output


def test_set_default_warns_for_omp_failure_and_still_syncs_claude():
    """OMP write failures should not block either the default change or Claude sync."""
    with (
        patch.object(configure, "ProfileManager") as manager_class,
        patch.object(
            configure,
            "sync_omp_mcp",
            side_effect=OmpMcpSyncError("OMP config is not writable."),
        ),
        patch.object(configure, "sync_claude_mcp") as sync_claude_mcp,
    ):
        manager_class.return_value.list_profiles.return_value = ["production"]

        result = runner.invoke(configure.app, ["set-default", "production"])

    assert result.exit_code == 0
    manager_class.return_value.set_default.assert_called_once_with("production")
    sync_claude_mcp.assert_called_once_with("production")
    assert "Warning" in result.output
    assert "OMP config is not writable" in result.output
    assert "Claude Code MCP registration synchronized" in result.output
