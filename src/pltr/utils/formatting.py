"""
Output formatting utilities for CLI commands.
"""

import json
import csv
import os
from typing import Any, Dict, List, Optional, Union, Callable
from datetime import datetime
from io import StringIO

from rich.console import Console
from rich.table import Table
from rich import print as rich_print

from .agent_output import (
    agent_mode_enabled,
    render_agent_json,
    render_agent_message,
    resolve_output_format,
)

# Type checking import to avoid circular dependencies
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ProtectedOutputCollisionError(ValueError):
    """Raised before truncation when rendered output aliases a protected artifact."""


class OutputFormatter:
    """Handles different output formats for CLI commands."""

    def __init__(self, console: Optional[Console] = None):
        """
        Initialize formatter.

        Args:
            console: Rich console instance (creates one if not provided)
        """
        self.console = console or Console()

    def format_output(
        self,
        data: Union[Dict[str, Any], List[Dict[str, Any]]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format data according to specified format.

        Args:
            data: Data to format
            format_type: Output format ('table', 'json', 'csv')
            output_file: Optional file path to write output

        Returns:
            Formatted string if no output file specified
        """
        format_type = resolve_output_format(format_type)
        if format_type == "agent":
            return self._format_agent(data, output_file)
        if format_type == "json":
            return self._format_json(data, output_file)
        elif format_type == "csv":
            return self._format_csv(data, output_file)
        elif format_type == "table":
            return self._format_table(data, output_file)
        else:
            raise ValueError(f"Unsupported format type: {format_type}")

    def format_dependency_result(
        self,
        result: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
        full: bool = False,
        protected_output_file: Optional[str] = None,
        output_mode: str = "graph",
    ) -> str:
        """Render one already-complete dependency analysis without rediscovery."""
        format_type = resolve_output_format(format_type)
        if format_type == "agent":
            rendered = render_agent_json(result, meta={"result_type": "dependency"})
        elif format_type == "json":
            rendered = (
                json.dumps(
                    self._make_json_serializable(result), indent=2, sort_keys=True
                )
                + "\n"
            )
        elif format_type == "csv":
            rendered = self._format_dependency_csv(result)
        elif format_type == "table":
            if output_mode == "agent":
                rendered = self._format_dependency_agent_table(result)
            else:
                rendered = self._format_dependency_table(result, full=full)
        else:
            raise ValueError(f"Unsupported format type: {format_type}")

        if output_file:
            self._write_dependency_output(
                rendered,
                output_file=output_file,
                protected_output_file=protected_output_file,
            )
        elif format_type in {"json", "csv"}:
            print(rendered, end="")
        else:
            self.console.print(rendered, markup=False, end="")
        return rendered

    @staticmethod
    def _write_dependency_output(
        rendered: str,
        *,
        output_file: str,
        protected_output_file: Optional[str],
    ) -> None:
        """Open without truncation and reject an artifact inode before writing.

        Comparing the opened descriptors closes the gap left by textual path
        normalization: case-folded paths, hard links, and symlinks are rejected
        even when the rendered destination did not exist during earlier checks.
        """
        protected_descriptor: Optional[int] = None
        output_descriptor: Optional[int] = None
        try:
            if protected_output_file is not None:
                protected_descriptor = os.open(protected_output_file, os.O_RDONLY)
            output_descriptor = os.open(
                output_file,
                os.O_WRONLY | os.O_CREAT,
                0o666,
            )
            if protected_descriptor is not None:
                protected_stat = os.fstat(protected_descriptor)
                output_stat = os.fstat(output_descriptor)
                if (protected_stat.st_dev, protected_stat.st_ino) == (
                    output_stat.st_dev,
                    output_stat.st_ino,
                ):
                    raise ProtectedOutputCollisionError(
                        "rendered output cannot replace the graph artifact"
                    )
            os.ftruncate(output_descriptor, 0)
            with os.fdopen(output_descriptor, "w", encoding="utf-8") as handle:
                output_descriptor = None
                handle.write(rendered)
        finally:
            if output_descriptor is not None:
                os.close(output_descriptor)
            if protected_descriptor is not None:
                os.close(protected_descriptor)

    def _format_dependency_csv(self, result: Dict[str, Any]) -> str:
        """Render the complete result as typed rows instead of a lossy summary."""
        graph = result.get("graph") or {}
        collections = (
            (
                "artifact",
                [result["artifact"]]
                if isinstance(result.get("artifact"), dict)
                else [],
            ),
            (
                "agent",
                [result["agent"]] if isinstance(result.get("agent"), dict) else [],
            ),
            ("read-context", result.get("read_contexts", [])),
            ("node", graph.get("nodes", result.get("nodes", []))),
            ("edge", graph.get("edges", result.get("edges", []))),
            ("path", result.get("paths", [])),
            ("coverage", result.get("coverage_records", result.get("coverage", []))),
            ("gap", result.get("gaps", [])),
            ("error", result.get("errors", [])),
            ("evidence", result.get("evidence", [])),
            (
                "operation-provenance",
                result.get(
                    "operation_provenance",
                    result.get("operation_provenance_records", []),
                ),
            ),
        )
        rows: List[Dict[str, str]] = []
        for row_kind, items in collections:
            if isinstance(items, dict):
                items = list(items.values())
            for item in items or []:
                value = self._make_json_serializable(item)
                identifier = (
                    value.get("id", value.get("analysis_id", ""))
                    if isinstance(value, dict)
                    else ""
                )
                rows.append(
                    {
                        "row_kind": row_kind,
                        "id": str(identifier),
                        "record": json.dumps(
                            value, sort_keys=True, separators=(",", ":")
                        ),
                    }
                )
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=["row_kind", "id", "record"])
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def _format_dependency_table(self, result: Dict[str, Any], full: bool) -> str:
        target = result.get("target") or {}
        target_label = (
            target.get("display_name")
            or target.get("id")
            or target.get("kind")
            or "unknown"
        )
        read_contexts = result.get("read_contexts") or []
        if isinstance(read_contexts, dict):
            read_contexts = list(read_contexts.values())
        requested_branches = sorted(
            {
                str(context.get("requested_branch"))
                for context in read_contexts
                if isinstance(context, dict)
                and context.get("requested_branch") is not None
            }
        )
        summary = result.get("summary") or {}
        assessment = (
            summary.get("assessment")
            or result.get("assessment")
            or "Dependency analysis complete."
        )
        gaps = result.get("gaps") or []
        budget = result.get("budget") or {}
        artifact = result.get("artifact") or {}
        paths = (
            result.get("ranked_relationships")
            or result.get("ranked_paths")
            or result.get("paths")
            or []
        )

        lines = [
            "Dependency analysis",
            f"Target: {target_label}",
            f"Requested branch: {', '.join(requested_branches) if requested_branches else 'server default'}",
            f"Assessment: {assessment}",
        ]
        chosen_paths = paths if full else paths[:1]
        if chosen_paths:
            lines.append("Relationships:")
            for path in chosen_paths:
                if not isinstance(path, dict):
                    lines.append(f"  - {path}")
                    continue
                readable = (
                    path.get("readable_path")
                    or path.get("path")
                    or path.get("node_labels")
                    or path.get("id")
                    or "unknown path"
                )
                if isinstance(readable, list):
                    readable = " -> ".join(str(part) for part in readable)
                direction = (
                    path.get("direction")
                    or path.get("root_relative_direction")
                    or "adjacent"
                )
                evidence_summary = path.get("evidence_summary") or {}
                locator = path.get("evidence_locator") or evidence_summary.get(
                    "locator"
                )
                namespace = path.get("sdk_namespace") or evidence_summary.get(
                    "sdk_namespace"
                )
                method = path.get("sdk_method") or evidence_summary.get("sdk_method")
                suffix = ", ".join(
                    part
                    for part in (
                        f"evidence {locator}" if locator else "",
                        f"{namespace}.{method}"
                        if namespace and method
                        else namespace or method or "",
                    )
                    if part
                )
                lines.append(
                    f"  - [{direction}] {readable}" + (f" ({suffix})" if suffix else "")
                )
        else:
            lines.append("Relationships: none discovered within verified coverage")

        reasons: Dict[str, int] = {}
        for gap in gaps:
            reason = (
                gap.get("reason_code", "unknown")
                if isinstance(gap, dict)
                else "unknown"
            )
            reasons[reason] = reasons.get(reason, 0) + 1
        gap_summary = (
            ", ".join(f"{key}={reasons[key]}" for key in sorted(reasons)) or "none"
        )
        lines.append(f"Coverage gaps ({len(gaps)}): {gap_summary}")
        stale_messages = sorted(
            {
                str(gap.get("message"))
                for gap in gaps
                if isinstance(gap, dict)
                and gap.get("reason_code") == "schedule-index-may-be-stale"
                and gap.get("message")
            }
        )
        for message in stale_messages:
            lines.append(f"Coverage note: {message}")
        if full:
            for gap in gaps:
                if isinstance(gap, dict):
                    lines.append(
                        f"  - {gap.get('surface', 'unknown')}: "
                        f"{gap.get('reason_code', 'unknown')} - {gap.get('message', '')}"
                    )
        used = budget.get("used", {}) if isinstance(budget, dict) else {}
        limits = budget.get("limits", {}) if isinstance(budget, dict) else {}
        dimensions = sorted(set(used) | set(limits))
        budget_summary = (
            ", ".join(
                f"{dimension}={used.get(dimension, 0)}/{limits.get(dimension, '?')}"
                for dimension in dimensions
            )
            or "not reported"
        )
        lines.append(f"Budget: {budget_summary}")
        agent = result.get("agent") or {}
        if agent:
            verification = agent.get("verification") or {}
            groups = (agent.get("blast_radius") or {}).get("groups") or {}
            lines.append(
                "Agent verification: "
                f"must={len(verification.get('must_verify_before_merge', []))} "
                f"should={len(verification.get('should_verify_before_deploy', []))} "
                f"unsupported={len(verification.get('unsupported_manual_surfaces', []))}"
            )
            lines.append(
                "Agent blast radius: "
                f"critical={len(groups.get('critical_paths', []))} "
                f"structural={len(groups.get('structural_dependents', []))} "
                f"indirect={len(groups.get('indirect_operational_effects', []))} "
                f"unknown={len(groups.get('unknown_manual_verification', []))}"
            )
        lines.extend(
            [
                f"Analysis ID: {artifact.get('analysis_id', '')}",
                f"Graph artifact: {artifact.get('path', '')}",
                f"SHA-256: {artifact.get('sha256', '')}",
            ]
        )
        return "\n".join(lines) + "\n"

    def _format_dependency_agent_table(self, result: Dict[str, Any]) -> str:
        """Compact agent-mode rendering built from the agent block (AU7)."""
        agent = result.get("agent") or {}
        artifact = result.get("artifact") or {}
        verification = agent.get("verification") or {}
        completeness = agent.get("coverage_completeness") or {}
        lines = [
            f"Dependency impact assessment [{agent.get('schema_version', 'unknown')}]",
            f"Status: {agent.get('status', 'unknown')}",
            f"Summary: {agent.get('summary', '')}",
            f"Coverage: {'complete' if completeness.get('complete') else 'TRUNCATED'}",
        ]
        change = agent.get("change") or {}
        if change.get("text") or change.get("change_type"):
            lines.append(
                "Change: "
                + ", ".join(
                    part
                    for part in (
                        str(change.get("text")) if change.get("text") else "",
                        f"type={change.get('change_type')}"
                        if change.get("change_type")
                        else "",
                        f"source={change.get('change_type_source')}",
                    )
                    if part
                )
            )
        blast = agent.get("blast_radius") or {}
        release = agent.get("release_risk") or {}
        lines.append(
            f"Blast radius: {blast.get('score')}/100 "
            f"(release risk: {release.get('score') if release.get('score') is not None else 'n/a'})"
        )
        for bucket, label in (
            ("must_verify_before_merge", "MUST verify before merge"),
            ("should_verify_before_deploy", "SHOULD verify before deploy"),
            ("unsupported_manual_surfaces", "Unsupported/manual surfaces"),
        ):
            items = verification.get(bucket) or []
            lines.append(f"{label} ({len(items)}):")
            for item in items[:10]:
                subject = (
                    item.get("subject_display_name")
                    or item.get("subject_node_id")
                    or "(analysis-wide)"
                )
                reason = item.get("reason", "impact")
                lines.append(f"  - [{reason}] {subject}")
            if len(items) > 10:
                lines.append(f"  ... {len(items) - 10} more (see graph artifact)")
        lines.extend(
            [
                f"Analysis ID: {artifact.get('analysis_id', '')}",
                f"Graph artifact: {artifact.get('path', '')}",
            ]
        )
        return "\n".join(lines) + "\n"

    def _format_agent(
        self, data: Any, output_file: Optional[str] = None
    ) -> Optional[str]:
        """Format data using the stable agent envelope."""
        rendered = render_agent_json(data, meta={"result_type": type(data).__name__})
        if output_file:
            with open(output_file, "w", encoding="utf-8") as handle:
                handle.write(rendered)
            return None
        print(rendered, end="")
        return rendered

    def _format_json(
        self, data: Any, output_file: Optional[str] = None
    ) -> Optional[str]:
        """Format data as JSON."""
        # Convert datetime objects to strings for JSON serialization
        data_serializable = self._make_json_serializable(data)
        json_str = json.dumps(data_serializable, indent=2, default=str)

        if output_file:
            with open(output_file, "w") as f:
                f.write(json_str)
            return None
        else:
            # Use plain print to ensure valid JSON output without ANSI codes
            print(json_str)
            return json_str

    def _format_csv(
        self,
        data: Union[Dict[str, Any], List[Dict[str, Any]]],
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """Format data as CSV."""
        if isinstance(data, dict):
            data = [data]

        if not data:
            csv_str = ""
        else:
            # Get all unique keys for the CSV header
            fieldnames_set: set[str] = set()
            for item in data:
                fieldnames_set.update(item.keys())
            fieldnames = sorted(fieldnames_set)

            output = StringIO()
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()

            for item in data:
                # Convert complex objects to strings
                row = {}
                for key in fieldnames:
                    value = item.get(key)
                    if isinstance(value, (dict, list)):
                        row[key] = json.dumps(value)
                    elif value is None:
                        row[key] = ""
                    else:
                        row[key] = str(value)
                writer.writerow(row)

            csv_str = output.getvalue()

        if output_file:
            with open(output_file, "w") as f:
                f.write(csv_str)
            return None
        else:
            print(csv_str, end="")
            return csv_str

    def _format_table(
        self,
        data: Union[Dict[str, Any], List[Dict[str, Any]]],
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """Format data as a rich table."""
        if isinstance(data, dict):
            data = [data]

        if not data:
            if output_file:
                with open(output_file, "w") as f:
                    f.write("No data to display\n")
                return None
            else:
                self.console.print("No data to display")
                return "No data to display"

        # Create table
        table = Table(show_header=True, header_style="bold blue")

        # Get all unique columns
        columns_set: set[str] = set()
        for item in data:
            columns_set.update(item.keys())
        columns = sorted(columns_set)

        # Add columns to table
        for column in columns:
            # Don't truncate RID columns - they need full visibility
            if "rid" in column.lower():
                table.add_column(column, no_wrap=True, overflow="fold")
            else:
                table.add_column(column, overflow="fold")

        # Add rows
        for item in data:
            row = []
            for column in columns:
                value = item.get(column)
                if isinstance(value, (dict, list)):
                    # Format complex objects as JSON
                    row.append(json.dumps(value, indent=2))
                elif value is None:
                    row.append("")
                elif isinstance(value, datetime):
                    row.append(value.isoformat())
                else:
                    row.append(str(value))
            table.add_row(*row)

        if output_file:
            # For file output, convert to plain text
            with open(output_file, "w") as f:
                console = Console(file=f, force_terminal=False)
                console.print(table)
            return None
        else:
            self.console.print(table)
            return str(table)

    def _make_json_serializable(self, data: Any) -> Any:
        """Convert data to JSON-serializable format."""
        if isinstance(data, dict):
            return {k: self._make_json_serializable(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._make_json_serializable(item) for item in data]
        elif isinstance(data, datetime):
            return data.isoformat()
        else:
            return data

    def format_dataset_list(
        self,
        datasets: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format dataset list with specific columns.

        Args:
            datasets: List of dataset dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        # Select and order key columns for dataset display
        formatted_datasets = []
        for dataset in datasets:
            formatted_dataset = {
                "RID": dataset.get("rid", ""),
                "Name": dataset.get("name", ""),
                "Created": self._format_datetime(dataset.get("created_time")),
                "Size": self._format_file_size(dataset.get("size_bytes")),
                "Description": dataset.get("description", "")[:50] + "..."
                if dataset.get("description", "")
                else "",
            }
            formatted_datasets.append(formatted_dataset)

        return self.format_output(formatted_datasets, format_type, output_file)

    def format_dataset_detail(
        self,
        dataset: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format detailed dataset information.

        Args:
            dataset: Dataset dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            # For table format, show key-value pairs (only show fields that exist)
            details = []

            if dataset.get("rid"):
                details.append({"Property": "RID", "Value": dataset["rid"]})
            if dataset.get("name"):
                details.append({"Property": "Name", "Value": dataset["name"]})
            if dataset.get("parent_folder_rid"):
                details.append(
                    {"Property": "Parent Folder", "Value": dataset["parent_folder_rid"]}
                )

            # Add any other fields that might exist
            for key, value in dataset.items():
                if (
                    key not in ["rid", "name", "parent_folder_rid"]
                    and value is not None
                    and value != ""
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(dataset, format_type, output_file)

    def format_file_list(
        self,
        files: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format file list with specific columns.

        Args:
            files: List of file dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        # Format files for display
        formatted_files = []
        for file in files:
            formatted_file = {
                "Path": file.get("path", ""),
                "Size": self._format_file_size(file.get("size_bytes")),
                "Last Modified": self._format_datetime(file.get("last_modified")),
                "Transaction": file.get("transaction_rid", "")[:12] + "..."
                if file.get("transaction_rid")
                else "",
            }
            formatted_files.append(formatted_file)

        return self.format_output(formatted_files, format_type, output_file)

    def _format_datetime(self, dt: Any) -> str:
        """Format datetime for display."""
        if dt is None:
            return ""
        if isinstance(dt, str):
            return dt
        if isinstance(dt, datetime):
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return str(dt)

    def _format_file_size(self, size_bytes: Optional[int]) -> str:
        """Format file size in human-readable format."""
        if size_bytes is None:
            return ""

        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024**2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024**3:
            return f"{size_bytes / (1024**2):.1f} MB"
        else:
            return f"{size_bytes / (1024**3):.1f} GB"

    def print_success(self, message: str):
        """Print success message with formatting."""
        if agent_mode_enabled():
            print(render_agent_message(message, level="success"), end="")
            return
        self.console.print(f"✅ {message}", style="green")

    def print_error(self, message: str):
        """Print error message with formatting."""
        if agent_mode_enabled():
            print(render_agent_message(message, level="error"), end="")
            return
        self.console.print(f"❌ {message}", style="red")

    def print_warning(self, message: str):
        """Print warning message with formatting."""
        if agent_mode_enabled():
            print(render_agent_message(message, level="warning"), end="")
            return
        self.console.print(f"⚠️  {message}", style="yellow")

    def print_info(self, message: str):
        """Print info message with formatting."""
        if agent_mode_enabled():
            print(render_agent_message(message), end="")
            return
        self.console.print(f"ℹ️  {message}", style="blue")

    def format_table(
        self,
        data: List[Dict[str, Any]],
        columns: Optional[List[str]] = None,
        format: str = "table",
        output: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format data as a table with specified columns.

        Args:
            data: List of dictionaries to format
            columns: List of column names to display (uses all if None)
            format: Output format ('table', 'json', 'csv')
            output: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if columns:
            # Filter data to only include specified columns
            filtered_data = []
            for item in data:
                filtered_item = {col: item.get(col) for col in columns}
                filtered_data.append(filtered_item)
            data = filtered_data

        return self.format_output(data, format, output)

    def format_list(
        self,
        data: List[Any],
        format: str = "table",
        output: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format a list of items.

        Args:
            data: List of items to format
            format: Output format ('table', 'json', 'csv')
            output: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        # Convert list items to dicts if needed
        if data and not isinstance(data[0], dict):
            data = [{"value": item} for item in data]

        return self.format_output(data, format, output)

    def format_dict(
        self,
        data: Dict[str, Any],
        format: str = "table",
        output: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format a dictionary for display.

        Args:
            data: Dictionary to format
            format: Output format ('table', 'json', 'csv')
            output: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        format = resolve_output_format(format)
        if format == "table":
            # Convert to key-value pairs for table display
            table_data = [{"Property": k, "Value": str(v)} for k, v in data.items()]
            return self.format_output(table_data, format, output)
        else:
            return self.format_output(data, format, output)

    def display(self, data: Any, format_type: str = "table") -> None:
        """
        Display data using the appropriate formatter.

        Args:
            data: Data to display
            format_type: Display format ('table', 'json', 'csv')
        """
        format_type = resolve_output_format(format_type)
        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                self.format_output(data, format_type)
            else:
                self.format_list(data, format_type)
        elif isinstance(data, dict):
            self.format_dict(data, format_type)
        else:
            # For simple values, just print them
            if format_type == "agent":
                print(render_agent_json(data, meta={"result_type": "scalar"}), end="")
            elif format_type == "json":
                # Use plain print to ensure valid JSON output without ANSI codes
                print(json.dumps(data, indent=2, default=str))
            else:
                rich_print(str(data))

    def save_to_file(self, data: Any, file_path: Any, format_type: str) -> None:
        """
        Save data to a file in the specified format.

        Args:
            data: Data to save
            file_path: Path object or string for output file
            format_type: File format ('table', 'json', 'csv')
        """
        format_type = resolve_output_format(format_type)
        file_path_str = str(file_path)

        if isinstance(data, list):
            if data and isinstance(data[0], dict):
                self.format_output(data, format_type, file_path_str)
            else:
                self.format_list(data, format_type, file_path_str)
        elif isinstance(data, dict):
            self.format_dict(data, format_type, file_path_str)
        else:
            # For simple values, save as text
            with open(file_path_str, "w") as f:
                if format_type == "json":
                    json.dump(data, f, indent=2, default=str)
                else:
                    f.write(str(data))

    def format_paginated_output(
        self,
        result: Any,  # PaginationResult
        format_type: str = "table",
        output_file: Optional[str] = None,
        formatter_fn: Optional[Callable] = None,
    ) -> Optional[str]:
        """
        Format paginated results with metadata.

        This method handles display of paginated data and automatically
        includes pagination information based on the output format.

        Args:
            result: PaginationResult object with .data and .metadata attributes
            format_type: Output format ('table', 'json', 'csv')
            output_file: Optional output file path
            formatter_fn: Optional custom formatter function for the data

        Returns:
            Formatted string if no output file specified

        Example:
            >>> result = PaginationResult(data=[...], metadata=metadata)
            >>> formatter.format_paginated_output(result, "json")
        """
        format_type = resolve_output_format(format_type)

        # Extract data and metadata
        data = result.data if hasattr(result, "data") else result
        metadata = result.metadata if hasattr(result, "metadata") else None

        # Agent/JSON formats include pagination metadata in output
        if format_type in {"agent", "json"}:
            if metadata:
                output_data = {
                    "data": data,
                    "pagination": {
                        "page": metadata.current_page,
                        "items_count": metadata.items_fetched,
                        "has_more": metadata.has_more,
                        "total_pages_fetched": metadata.total_pages_fetched,
                    },
                }
                # Include next_page_token if available
                if metadata.next_page_token:
                    output_data["pagination"]["next_page_token"] = (
                        metadata.next_page_token
                    )

                if format_type == "agent":
                    rendered = render_agent_json(
                        data,
                        meta={"result_type": "paginated"},
                        pagination=output_data["pagination"],
                    )
                    if output_file:
                        with open(output_file, "w", encoding="utf-8") as handle:
                            handle.write(rendered)
                        return None
                    print(rendered, end="")
                    return rendered
                return self._format_json(output_data, output_file)
            else:
                # No metadata, format data directly
                if format_type == "agent":
                    rendered = render_agent_json(
                        data, meta={"result_type": "paginated"}
                    )
                    if output_file:
                        with open(output_file, "w", encoding="utf-8") as handle:
                            handle.write(rendered)
                        return None
                    print(rendered, end="")
                    return rendered
                return self._format_json(data, output_file)

        # Table/CSV format: format data normally, then print pagination info
        else:
            # Format the data using custom formatter or default
            if formatter_fn:
                formatted_result = formatter_fn(data, format_type, output_file)
            else:
                formatted_result = self.format_output(data, format_type, output_file)

            # Print pagination info to console (even when saving to file)
            # For CSV/table formats, pagination metadata is shown on console
            # while data is written to file
            if metadata:
                self.print_pagination_info(metadata)

            return formatted_result

    def print_pagination_info(self, metadata: Any) -> None:  # PaginationMetadata
        """
        Print pagination information to the console.

        This provides users with helpful information about the current
        pagination state and how to fetch more data.

        Args:
            metadata: PaginationMetadata object

        Example output:
            Fetched 20 items (page 1)
            Next page: --page-token abc123
            Fetch all: Add --all flag
        """
        if not metadata:
            return

        # Build info message
        info_lines = []

        # Current state
        info_lines.append(
            f"Fetched {metadata.items_fetched} items (page {metadata.current_page})"
        )

        # Next steps if more data available
        if metadata.has_more:
            if metadata.next_page_token:
                info_lines.append(f"Next page: --page-token {metadata.next_page_token}")
            else:
                # Iterator pattern without explicit token
                info_lines.append(
                    f"Next page: Use --max-pages {metadata.current_page + 1}"
                )

            info_lines.append("Fetch all: Add --all flag")
        else:
            info_lines.append("No more pages available")

        # Print as info message
        self.print_info("\n".join(info_lines))

    def format_sql_results(
        self,
        results: Any,
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format SQL query results for display.

        Args:
            results: Query results (could be dict, list, or other types)
            format_type: Output format ('table', 'json', 'csv')
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        # Handle different types of SQL results
        if isinstance(results, dict):
            # Check for special result types
            if "text" in results:
                # Text result - display as-is
                text_data = results["text"]
                if output_file:
                    with open(output_file, "w") as f:
                        f.write(text_data)
                    return None
                else:
                    rich_print(text_data)
                    return text_data
            elif "type" in results and results["type"] == "binary":
                # Binary result - show metadata
                return self.format_output(results, format_type, output_file)
            elif "results" in results:
                # Results array
                return self.format_output(results["results"], format_type, output_file)
            elif "result" in results:
                # Single result
                single_result = results["result"]
                if isinstance(single_result, (dict, list)):
                    return self.format_output(single_result, format_type, output_file)
                else:
                    # Simple value
                    display_data = [{"Result": single_result}]
                    return self.format_output(display_data, format_type, output_file)
            else:
                # Regular dictionary
                return self.format_dict(results, format_type, output_file)
        elif isinstance(results, list):
            # List of results
            return self.format_output(results, format_type, output_file)
        else:
            # Simple value
            display_data = [{"Result": results}]
            return self.format_output(display_data, format_type, output_file)

    def format_query_status(
        self,
        status_info: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format query status information.

        Args:
            status_info: Query status dictionary
            format_type: Output format ('table', 'json', 'csv')
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            # Convert to key-value display for better readability
            display_data = []
            for key, value in status_info.items():
                display_data.append(
                    {"Property": key.replace("_", " ").title(), "Value": str(value)}
                )
            return self.format_output(display_data, format_type, output_file)
        else:
            return self.format_output(status_info, format_type, output_file)

    # ============================================================================
    # Orchestration Formatting Methods
    # ============================================================================

    def format_build_detail(
        self,
        build: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format detailed build information.

        Args:
            build: Build dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            # For table format, show key-value pairs
            details = []

            # Define the order of properties to display
            property_order = [
                "rid",
                "status",
                "created_by",
                "created_time",
                "started_time",
                "finished_time",
                "branch_name",
                "commit_hash",
            ]

            for prop in property_order:
                if build.get(prop) is not None:
                    value = build[prop]
                    # Format timestamps
                    if "time" in prop:
                        value = self._format_datetime(value)
                    details.append(
                        {
                            "Property": prop.replace("_", " ").title(),
                            "Value": str(value),
                        }
                    )

            # Add any remaining properties
            for key, value in build.items():
                if key not in property_order and value is not None:
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(build, format_type, output_file)

    def format_builds_list(
        self,
        builds: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format list of builds.

        Args:
            builds: List of build dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_builds = []
        for build in builds:
            formatted_build = {
                "RID": build.get("rid", ""),
                "Status": build.get("status", ""),
                "Created By": build.get("created_by", ""),
                "Created": self._format_datetime(build.get("created_time")),
                "Branch": build.get("branch_name", ""),
            }
            formatted_builds.append(formatted_build)

        return self.format_output(formatted_builds, format_type, output_file)

    def format_job_detail(
        self,
        job: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format detailed job information.

        Args:
            job: Job dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            # For table format, show key-value pairs
            details = []

            # Define the order of properties to display
            property_order = [
                "rid",
                "status",
                "job_type",
                "build_rid",
                "created_time",
                "started_time",
                "finished_time",
            ]

            for prop in property_order:
                if job.get(prop) is not None:
                    value = job[prop]
                    # Format timestamps
                    if "time" in prop:
                        value = self._format_datetime(value)
                    details.append(
                        {
                            "Property": prop.replace("_", " ").title(),
                            "Value": str(value),
                        }
                    )

            # Add any remaining properties
            for key, value in job.items():
                if key not in property_order and value is not None:
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(job, format_type, output_file)

    def format_jobs_list(
        self,
        jobs: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format list of jobs.

        Args:
            jobs: List of job dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_jobs = []
        for job in jobs:
            formatted_job = {
                "RID": job.get("rid", ""),
                "Status": job.get("status", ""),
                "Type": job.get("job_type", ""),
                "Build": job.get("build_rid", "")[:12] + "..."
                if job.get("build_rid")
                else "",
                "Started": self._format_datetime(job.get("started_time")),
            }
            formatted_jobs.append(formatted_job)

        return self.format_output(formatted_jobs, format_type, output_file)

    def format_schedule_detail(
        self,
        schedule: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format detailed schedule information.

        Args:
            schedule: Schedule dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            # For table format, show key-value pairs
            details = []

            # Define the order of properties to display
            property_order = [
                "rid",
                "display_name",
                "description",
                "paused",
                "created_by",
                "created_time",
                "modified_by",
                "modified_time",
            ]

            for prop in property_order:
                if schedule.get(prop) is not None:
                    value = schedule[prop]
                    # Format timestamps
                    if "time" in prop:
                        value = self._format_datetime(value)
                    # Format boolean values
                    elif prop == "paused":
                        value = "Yes" if value else "No"
                    details.append(
                        {
                            "Property": prop.replace("_", " ").title(),
                            "Value": str(value),
                        }
                    )

            # Handle special nested properties
            if schedule.get("trigger"):
                details.append(
                    {"Property": "Trigger", "Value": str(schedule["trigger"])}
                )
            if schedule.get("action"):
                details.append({"Property": "Action", "Value": str(schedule["action"])})

            # Add any remaining properties
            for key, value in schedule.items():
                if (
                    key not in property_order + ["trigger", "action"]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(schedule, format_type, output_file)

    def format_schedules_list(
        self,
        schedules: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format list of schedules.

        Args:
            schedules: List of schedule dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_schedules = []
        for schedule in schedules:
            formatted_schedule = {
                "RID": schedule.get("rid", ""),
                "Name": schedule.get("display_name", ""),
                "Description": schedule.get("description", "")[:50] + "..."
                if schedule.get("description")
                else "",
                "Paused": "Yes" if schedule.get("paused") else "No",
                "Created": self._format_datetime(schedule.get("created_time")),
            }
            formatted_schedules.append(formatted_schedule)

        return self.format_output(formatted_schedules, format_type, output_file)

    def format_schedule_runs_list(
        self,
        runs: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format list of schedule runs.

        Args:
            runs: List of schedule run dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_runs = []
        for run in runs:
            build_rid = run.get("build_rid", "")
            formatted_run = {
                "RID": run.get("rid", ""),
                "Status": run.get("status", ""),
                "Started": self._format_datetime(run.get("started_time")),
                "Finished": self._format_datetime(run.get("finished_time")),
                "Build": build_rid[:40] + "..." if len(build_rid) > 40 else build_rid,
                "Result": run.get("result", ""),
            }
            formatted_runs.append(formatted_run)

        return self.format_output(formatted_runs, format_type, output_file)

    # MediaSets formatting methods

    def format_media_item_info(
        self,
        media_item: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format media item information for display.

        Args:
            media_item: Media item information dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = []

            property_order = [
                ("media_item_rid", "Media Item RID"),
                ("filename", "Filename"),
                ("size", "Size"),
                ("content_type", "Content Type"),
                ("created_time", "Created"),
                ("updated_time", "Updated"),
            ]

            for key, label in property_order:
                if media_item.get(key) is not None:
                    value = media_item[key]
                    if key in ["created_time", "updated_time"]:
                        value = self._format_datetime(value)
                    elif key == "size":
                        value = self._format_file_size(value)
                    details.append({"Property": label, "Value": str(value)})

            # Add any remaining properties
            for key, value in media_item.items():
                if (
                    key not in [prop[0] for prop in property_order]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(media_item, format_type, output_file)

    def format_media_path_lookup(
        self,
        lookup_result: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format media path lookup result for display.

        Args:
            lookup_result: Path lookup result dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = [
                {"Property": "Path", "Value": lookup_result.get("path", "")},
                {"Property": "Media Item RID", "Value": lookup_result.get("rid", "")},
            ]
            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(lookup_result, format_type, output_file)

    def format_media_reference(
        self,
        reference: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format media reference information for display.

        Args:
            reference: Media reference dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = []

            property_order = [
                ("reference_id", "Reference ID"),
                ("url", "URL"),
                ("expires_at", "Expires At"),
            ]

            for key, label in property_order:
                if reference.get(key) is not None:
                    value = reference[key]
                    if key == "expires_at":
                        value = self._format_datetime(value)
                    details.append({"Property": label, "Value": str(value)})

            # Add any remaining properties
            for key, value in reference.items():
                if (
                    key not in [prop[0] for prop in property_order]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(reference, format_type, output_file)

    def format_thumbnail_status(
        self,
        status: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format thumbnail calculation status for display.

        Args:
            status: Thumbnail status dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = []

            property_order = [
                ("status", "Status"),
                ("transformation_id", "Transformation ID"),
                ("media_item_rid", "Media Item RID"),
            ]

            for key, label in property_order:
                if status.get(key) is not None:
                    details.append({"Property": label, "Value": str(status[key])})

            # Add any remaining properties
            for key, value in status.items():
                if (
                    key not in [prop[0] for prop in property_order]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(status, format_type, output_file)

    # Dataset formatting methods

    def format_branches(
        self,
        branches: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format dataset branches for display.

        Args:
            branches: List of branch dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_branches = []
        for branch in branches:
            formatted_branch = {
                "Name": branch.get("name", ""),
                "Transaction": branch.get("transaction_rid", "")[:12] + "..."
                if branch.get("transaction_rid")
                else "",
                "Created": self._format_datetime(branch.get("created_time")),
                "Created By": branch.get("created_by", ""),
            }
            formatted_branches.append(formatted_branch)

        return self.format_output(formatted_branches, format_type, output_file)

    def format_branch_detail(
        self,
        branch: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format detailed branch information.

        Args:
            branch: Branch dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = []

            property_order = [
                ("name", "Branch Name"),
                ("dataset_rid", "Dataset RID"),
                ("parent_branch", "Parent Branch"),
                ("transaction_rid", "Transaction RID"),
                ("created_time", "Created"),
                ("created_by", "Created By"),
            ]

            for key, label in property_order:
                if branch.get(key) is not None:
                    value = branch[key]
                    if key == "created_time":
                        value = self._format_datetime(value)
                    details.append({"Property": label, "Value": str(value)})

            # Add any remaining properties
            for key, value in branch.items():
                if (
                    key not in [prop[0] for prop in property_order]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(branch, format_type, output_file)

    def format_files(
        self,
        files: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format dataset files for display.

        Args:
            files: List of file dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_files = []
        for file in files:
            formatted_file = {
                "Path": file.get("path", ""),
                "Size": self._format_file_size(file.get("size_bytes")),
                "Last Modified": self._format_datetime(file.get("last_modified")),
                "Transaction": file.get("transaction_rid", "")[:12] + "..."
                if file.get("transaction_rid")
                else "",
            }
            formatted_files.append(formatted_file)

        return self.format_output(formatted_files, format_type, output_file)

    def format_transactions(
        self,
        transactions: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format dataset transactions for display.

        Args:
            transactions: List of transaction dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_transactions = []
        for transaction in transactions:
            formatted_transaction = {
                "Transaction RID": transaction.get("transaction_rid", "")[:12] + "..."
                if transaction.get("transaction_rid")
                else "",
                "Status": transaction.get("status", ""),
                "Type": transaction.get("transaction_type", ""),
                "Branch": transaction.get("branch", ""),
                "Created": self._format_datetime(transaction.get("created_time")),
                "Created By": transaction.get("created_by", ""),
            }
            formatted_transactions.append(formatted_transaction)

        return self.format_output(formatted_transactions, format_type, output_file)

    def format_transaction_detail(
        self,
        transaction: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format detailed transaction information.

        Args:
            transaction: Transaction dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = []

            property_order = [
                ("transaction_rid", "Transaction RID"),
                ("dataset_rid", "Dataset RID"),
                ("status", "Status"),
                ("transaction_type", "Type"),
                ("branch", "Branch"),
                ("created_time", "Created"),
                ("created_by", "Created By"),
                ("committed_time", "Committed"),
                ("aborted_time", "Aborted"),
            ]

            for key, label in property_order:
                if transaction.get(key) is not None:
                    value = transaction[key]
                    if "time" in key:
                        value = self._format_datetime(value)
                    details.append({"Property": label, "Value": str(value)})

            # Add any remaining properties
            for key, value in transaction.items():
                if (
                    key not in [prop[0] for prop in property_order]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(transaction, format_type, output_file)

    def format_transaction_result(
        self,
        result: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format transaction operation result.

        Args:
            result: Transaction operation result dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = []

            property_order = [
                ("transaction_rid", "Transaction RID"),
                ("dataset_rid", "Dataset RID"),
                ("status", "Status"),
                ("success", "Success"),
                ("committed_time", "Committed Time"),
                ("aborted_time", "Aborted Time"),
            ]

            for key, label in property_order:
                if result.get(key) is not None:
                    value = result[key]
                    if "time" in key:
                        value = self._format_datetime(value)
                    elif key == "success":
                        value = "Yes" if value else "No"
                    details.append({"Property": label, "Value": str(value)})

            # Add any remaining properties
            for key, value in result.items():
                if (
                    key not in [prop[0] for prop in property_order]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(result, format_type, output_file)

    def format_views(
        self,
        views: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format dataset views for display.

        Args:
            views: List of view dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_views = []
        for view in views:
            formatted_view = {
                "View RID": view.get("view_rid", "")[:12] + "..."
                if view.get("view_rid")
                else "",
                "Name": view.get("name", ""),
                "Description": view.get("description", "")[:50] + "..."
                if view.get("description", "")
                else "",
                "Created": self._format_datetime(view.get("created_time")),
                "Created By": view.get("created_by", ""),
            }
            formatted_views.append(formatted_view)

        return self.format_output(formatted_views, format_type, output_file)

    def format_view_detail(
        self,
        view: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format detailed view information.

        Args:
            view: View dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = []

            property_order = [
                ("view_rid", "View RID"),
                ("name", "Name"),
                ("description", "Description"),
                ("dataset_rid", "Dataset RID"),
                ("created_time", "Created"),
                ("created_by", "Created By"),
            ]

            for key, label in property_order:
                if view.get(key) is not None:
                    value = view[key]
                    if key == "created_time":
                        value = self._format_datetime(value)
                    details.append({"Property": label, "Value": str(value)})

            # Add any remaining properties
            for key, value in view.items():
                if (
                    key not in [prop[0] for prop in property_order]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(view, format_type, output_file)

    def format_file_info(
        self,
        file_info: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format file metadata information.

        Args:
            file_info: File info dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = []

            property_order = [
                ("path", "File Path"),
                ("dataset_rid", "Dataset RID"),
                ("branch", "Branch"),
                ("size_bytes", "Size (bytes)"),
                ("content_type", "Content Type"),
                ("last_modified", "Last Modified"),
                ("created_time", "Created"),
                ("transaction_rid", "Transaction RID"),
            ]

            for key, label in property_order:
                if file_info.get(key) is not None:
                    value = file_info[key]
                    if key in ["last_modified", "created_time"]:
                        value = self._format_datetime(value)
                    details.append({"Property": label, "Value": str(value)})

            # Add any remaining properties
            for key, value in file_info.items():
                if (
                    key not in [prop[0] for prop in property_order]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(file_info, format_type, output_file)

    def format_schedules(
        self,
        schedules: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format dataset schedules for display.

        Args:
            schedules: List of schedule dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_schedules = []
        for schedule in schedules:
            formatted_schedule = {
                "Schedule RID": schedule.get("schedule_rid", "")[:12] + "..."
                if schedule.get("schedule_rid")
                else "",
                "Name": schedule.get("name", ""),
                "Description": schedule.get("description", "")[:50] + "..."
                if schedule.get("description", "")
                else "",
                "Enabled": schedule.get("enabled", ""),
                "Created": self._format_datetime(schedule.get("created_time")),
            }
            formatted_schedules.append(formatted_schedule)

        return self.format_output(formatted_schedules, format_type, output_file)

    def format_jobs(
        self,
        jobs: List[Dict[str, Any]],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format dataset jobs for display.

        Args:
            jobs: List of job dictionaries
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        formatted_jobs = []
        for job in jobs:
            formatted_job = {
                "Job RID": job.get("job_rid", "")[:12] + "..."
                if job.get("job_rid")
                else "",
                "Name": job.get("name", ""),
                "Status": job.get("status", ""),
                "Created": self._format_datetime(job.get("created_time")),
                "Started": self._format_datetime(job.get("started_time")),
                "Completed": self._format_datetime(job.get("completed_time")),
            }
            formatted_jobs.append(formatted_job)

        return self.format_output(formatted_jobs, format_type, output_file)

    def format_transaction_build(
        self,
        build_info: Dict[str, Any],
        format_type: str = "table",
        output_file: Optional[str] = None,
    ) -> Optional[str]:
        """
        Format transaction build information.

        Args:
            build_info: Build info dictionary
            format_type: Output format
            output_file: Optional output file path

        Returns:
            Formatted string if no output file specified
        """
        if format_type == "table":
            details = []

            property_order = [
                ("transaction_rid", "Transaction RID"),
                ("dataset_rid", "Dataset RID"),
                ("build_rid", "Build RID"),
                ("status", "Status"),
                ("started_time", "Started"),
                ("completed_time", "Completed"),
                ("duration_ms", "Duration (ms)"),
            ]

            for key, label in property_order:
                if build_info.get(key) is not None:
                    value = build_info[key]
                    if key in ["started_time", "completed_time"]:
                        value = self._format_datetime(value)
                    details.append({"Property": label, "Value": str(value)})

            # Add any remaining properties
            for key, value in build_info.items():
                if (
                    key not in [prop[0] for prop in property_order]
                    and value is not None
                ):
                    details.append(
                        {"Property": key.replace("_", " ").title(), "Value": str(value)}
                    )

            return self.format_output(details, format_type, output_file)
        else:
            return self.format_output(build_info, format_type, output_file)
