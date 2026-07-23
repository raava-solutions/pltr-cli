"""CLI tests for read-only cross-resource search output and fail-safe exits."""

from __future__ import annotations

import csv
import json
from io import StringIO
from unittest.mock import patch

from typer.testing import CliRunner

from pltr.cli import app
from pltr.services.foundry_internal_client import TokenExpiredError


runner = CliRunner()


def _ok_payload() -> dict:
    return {
        "status": "ok",
        "reason": None,
        "query": "Flight",
        "limit": 25,
        "truncation_note": "search(title:) has no page token; ...",
        "results": [
            {
                "rid": "ri.foundry.main.dataset.1",
                "name": "Flights",
                "path": "/AIP Now Ontology/Data/Flights",
                "type": "Dataset",
                "typename": "ResourceMetadata",
            },
            {
                "rid": "ri.workshop.main.module.2",
                "name": "Flights Map",
                "path": "/Apps/Flights Map",
                "type": "Module",
                "typename": "ResourceMetadata",
            },
        ],
    }


def test_search_renders_results_table_and_notes_truncation():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = _ok_payload()
        result = runner.invoke(
            app,
            ["search", "Flight", "--profile", "qa", "--output-mode", "agent"],
        )

    assert result.exit_code == 0, result.output
    assert "SEARCH [ok]" in result.output
    assert "Flights" in result.output
    assert "ri.workshop.main.module.2" in result.output
    assert "no page token" in result.output
    service.assert_called_once_with(profile="qa")
    service.return_value.search.assert_called_once_with("Flight", limit=25)


def test_search_limit_option_is_passed_through():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = _ok_payload()
        result = runner.invoke(app, ["search", "Flight", "--limit", "5"])

    assert result.exit_code == 0, result.output
    service.return_value.search.assert_called_once_with("Flight", limit=5)


def test_search_json_output_is_machine_readable():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = _ok_payload()
        result = runner.invoke(app, ["search", "Flight", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["results"][0]["rid"] == "ri.foundry.main.dataset.1"


def test_search_csv_output_rows():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = _ok_payload()
        result = runner.invoke(app, ["search", "Flight", "--format", "csv"])

    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(StringIO(result.output)))
    assert len(rows) == 2
    assert rows[0]["name"] == "Flights"
    assert rows[1]["type"] == "Module"


def test_empty_results_is_successful_and_plainly_identified():
    payload = _ok_payload()
    payload["results"] = []
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = payload
        result = runner.invoke(app, ["search", "zzz-nothing"])

    assert result.exit_code == 0, result.output
    assert "No results" in result.output
    assert "INCONCLUSIVE" not in result.output


def test_inconclusive_exits_nonzero_and_warns_not_empty():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = {
            "status": "inconclusive",
            "reason": "search-null",
            "results": None,
        }
        result = runner.invoke(app, ["search", "Flight"])

    assert result.exit_code == 1
    assert "INCONCLUSIVE: search-null" in result.output
    assert "NOT proof there are no matching resources" in result.output


def test_inconclusive_json_and_csv_preserve_machine_format_and_warning():
    payload = {
        "status": "inconclusive",
        "reason": "missing-response-frame",
        "results": None,
    }
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = payload
        json_result = runner.invoke(app, ["search", "Flight", "--format", "json"])
        csv_result = runner.invoke(app, ["search", "Flight", "--format", "csv"])

    assert json_result.exit_code == 1
    assert csv_result.exit_code == 1
    assert json.loads(json_result.output)["warning"].startswith(
        "INCONCLUSIVE: missing-response-frame"
    )
    rows = list(csv.DictReader(StringIO(csv_result.output)))
    assert rows[0]["warning"].startswith("INCONCLUSIVE: missing-response-frame")


def test_token_expired_shows_degraded_banner_and_exits_nonzero():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.side_effect = TokenExpiredError("expired")
        result = runner.invoke(app, ["search", "Flight"])

    assert result.exit_code == 1
    assert "DEGRADED [token-expired]" in result.output
    assert "re-authenticate" in result.output


def test_invalid_format_and_limit_are_rejected():
    with patch("pltr.commands.search.SearchService"):
        bad_format = runner.invoke(app, ["search", "Flight", "--format", "yaml"])
        bad_limit = runner.invoke(app, ["search", "Flight", "--limit", "0"])

    assert bad_format.exit_code != 0
    assert bad_limit.exit_code != 0


def test_empty_or_whitespace_text_is_rejected():
    with patch("pltr.commands.search.SearchService") as service:
        empty = runner.invoke(app, ["search", ""])
        whitespace = runner.invoke(app, ["search", "   "])

    assert empty.exit_code == 2
    assert whitespace.exit_code == 2
    service.return_value.search.assert_not_called()


def test_limit_gateway_cap_is_enforced():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = _ok_payload()
        accepted = runner.invoke(app, ["search", "Flight", "--limit", "500"])
        rejected = runner.invoke(app, ["search", "Flight", "--limit", "501"])

    assert accepted.exit_code == 0, accepted.output
    service.return_value.search.assert_called_once_with("Flight", limit=500)
    assert rejected.exit_code == 2
    assert "500" in rejected.output


def test_ci_mode_ok_exits_zero_with_machine_block():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = _ok_payload()
        result = runner.invoke(app, ["search", "Flight", "--output-mode", "ci"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["results"] == 2


def test_ci_mode_inconclusive_exits_two():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = {
            "status": "inconclusive",
            "reason": "search-null",
            "results": None,
        }
        result = runner.invoke(app, ["search", "Flight", "--output-mode", "ci"])

    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "inconclusive"
    assert payload["reason"] == "search-null"
    assert payload["results"] is None


def test_ci_mode_token_expired_stays_fatal():
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.side_effect = TokenExpiredError("expired")
        result = runner.invoke(app, ["search", "Flight", "--output-mode", "ci"])

    assert result.exit_code == 1
    assert "DEGRADED [token-expired]" in result.output


def test_unwritable_output_path_exits_one_without_traceback(tmp_path):
    unwritable = tmp_path / "missing-dir" / "out.txt"
    with patch("pltr.commands.search.SearchService") as service:
        service.return_value.search.return_value = _ok_payload()
        result = runner.invoke(app, ["search", "Flight", "--output", str(unwritable)])

    assert result.exit_code == 1
    assert "Error writing output file" in result.output
    assert "Traceback" not in result.output
