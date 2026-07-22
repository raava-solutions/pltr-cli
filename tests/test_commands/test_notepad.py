"""CLI tests for read-only notepad output and fail-safe exits."""

from __future__ import annotations

import csv
import json
from io import StringIO
from unittest.mock import patch

from typer.testing import CliRunner

from pltr.cli import app
from pltr.services.foundry_internal_client import TokenExpiredError


runner = CliRunner()


def test_readable_notepad_renders_body_and_reference_identifiers():
    payload = {
        "status": "readable",
        "reason": None,
        "rid": "ri.notepad.1",
        "name": "Agent notes",
        "version": 7,
        "metadata": {"name": "Agent notes"},
        "body": [],
        "body_text": "Important prose",
        "references": [
            {
                "kind": "compass-resource-section-plugin",
                "section_type_id": (
                    "rich-text-editor.section.v1.compass-resource-section-plugin"
                ),
                "config": {"rid": "ri.foundry.main.dataset.example"},
            },
            {
                "kind": "stored-image-custom-section-plugin",
                "section_type_id": (
                    "rich-text-editor.section.v1.stored-image-custom-section-plugin"
                ),
                "config": {"name": "chart.png", "snapshotRid": "ri.snapshot.1"},
            },
        ],
    }
    with patch("pltr.commands.notepad.NotepadService") as service:
        service.return_value.get.return_value = payload
        result = runner.invoke(
            app,
            [
                "notepad",
                "get",
                "ri.notepad.1",
                "--profile",
                "qa",
                "--output-mode",
                "agent",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "NOTEPAD READ [readable]" in result.output
    assert "Agent notes" in result.output
    assert "Important prose" in result.output
    assert "rid=ri.foundry.main.dataset.example" in result.output
    assert "snapshotRid=ri.snapshot.1" in result.output
    service.assert_called_once_with(profile="qa")
    service.return_value.get.assert_called_once_with("ri.notepad.1")


def test_notepad_null_inconclusive_exits_nonzero_and_warns_not_empty():
    with patch("pltr.commands.notepad.NotepadService") as service:
        service.return_value.get.return_value = {
            "status": "inconclusive",
            "reason": "notepad-null",
            "body": None,
            "body_text": None,
            "references": None,
        }
        result = runner.invoke(app, ["notepad", "get", "ri.notepad.missing"])

    assert result.exit_code == 1
    assert "INCONCLUSIVE: notepad-null" in result.output
    assert "NOT proof the notepad is empty" in result.output
    assert "EMPTY DOCUMENT" not in result.output


def test_empty_document_is_successful_and_plainly_identified():
    with patch("pltr.commands.notepad.NotepadService") as service:
        service.return_value.get.return_value = {
            "status": "empty-document",
            "reason": None,
            "rid": "ri.notepad.empty",
            "name": "Empty",
            "version": 1,
            "body": [],
            "body_text": "",
            "references": [],
        }
        result = runner.invoke(app, ["notepad", "get", "ri.notepad.empty"])

    assert result.exit_code == 0, result.output
    assert "EMPTY DOCUMENT" in result.output
    assert "INCONCLUSIVE" not in result.output


def test_token_expired_shows_degraded_banner_and_exits_nonzero():
    with patch("pltr.commands.notepad.NotepadService") as service:
        service.return_value.get.side_effect = TokenExpiredError("expired")
        result = runner.invoke(app, ["notepad", "get", "ri.notepad.1"])

    assert result.exit_code == 1
    assert "DEGRADED [token-expired]" in result.output
    assert "re-authenticate" in result.output


def test_inconclusive_json_and_csv_preserve_machine_format_and_warning():
    payload = {
        "status": "inconclusive",
        "reason": "contents-null",
        "body": None,
        "body_text": None,
        "references": None,
    }
    with patch("pltr.commands.notepad.NotepadService") as service:
        service.return_value.get.return_value = payload
        json_result = runner.invoke(
            app, ["notepad", "get", "ri.notepad.1", "--format", "json"]
        )
        csv_result = runner.invoke(
            app, ["notepad", "get", "ri.notepad.1", "--format", "csv"]
        )

    assert json_result.exit_code == 1
    assert csv_result.exit_code == 1
    assert json.loads(json_result.output)["warning"].startswith(
        "INCONCLUSIVE: contents-null"
    )
    rows = list(csv.DictReader(StringIO(csv_result.output)))
    assert rows[0]["warning"].startswith("INCONCLUSIVE: contents-null")
