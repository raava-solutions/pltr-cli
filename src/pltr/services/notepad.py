"""Read-only access to Foundry notepad contents."""

from __future__ import annotations

import json
from typing import Any, Iterator, Mapping, Optional

from ..auth.base import ProfileNotFoundError
from ..auth.manager import AuthManager
from .foundry_internal_client import FoundryInternalClient, GraphQLResult


# Select ONLY scalar metadata fields. `metadata.tags` and `notepad.permissions`
# are composites that REQUIRE a subselection; leaf-selecting either makes the
# gateway return HTTP 200 + a SubselectionRequired ValidationError with no data
# (a silent false-"unreadable"). Do not re-add `tags` here.
GET_NOTEPAD_CONTENTS_QUERY = """query GetNotepadContentsQuery($notepadRid: RID!) {
  notepad(rid: $notepadRid) {
    rid
    metadata { name lastModifiedAt description }
    latestVersion { name contents version }
  }
}"""

SECTION_TYPE_PREFIX = "rich-text-editor.section.v1."


class NotepadService:
    """Read and classify notepad contents without treating absence as empty."""

    def __init__(
        self,
        profile: Optional[str] = None,
        *,
        client: Optional[FoundryInternalClient] = None,
    ) -> None:
        if client is not None:
            self.client = client
            return
        effective_profile = profile or AuthManager().get_current_profile()
        if not effective_profile:
            raise ProfileNotFoundError(
                "No profile specified and no default profile configured. "
                "Run 'pltr configure configure' to set up authentication."
            )
        self.client = FoundryInternalClient(effective_profile)

    def get(self, notepad_rid: str) -> dict[str, Any]:
        """Return a fail-safe classification of one notepad read."""

        response = self.client.graphql(
            "GetNotepadContentsQuery",
            GET_NOTEPAD_CONTENTS_QUERY,
            {"notepadRid": notepad_rid},
        )
        if response.errors:
            return self._inconclusive(self._error_reason(response))
        if response.status == "inconclusive":
            return self._inconclusive(
                response.reason or "graphql-response-inconclusive"
            )

        data = response.data
        notepad = data.get("notepad") if isinstance(data, Mapping) else None
        if not isinstance(notepad, Mapping):
            return self._inconclusive("notepad-null")

        metadata = notepad.get("metadata")
        metadata_dict = dict(metadata) if isinstance(metadata, Mapping) else {}
        latest_version = notepad.get("latestVersion")
        version_dict = (
            dict(latest_version) if isinstance(latest_version, Mapping) else {}
        )
        base = {
            "rid": notepad.get("rid", notepad_rid),
            "name": metadata_dict.get("name"),
            "version": version_dict.get("version"),
            "version_name": version_dict.get("name"),
            "metadata": metadata_dict,
        }
        contents = version_dict.get("contents")
        if contents is None:
            return {**base, **self._inconclusive("contents-null")}
        if contents == "":
            return {
                **base,
                "status": "empty-document",
                "reason": None,
                "body": [],
                "body_text": "",
                "references": [],
            }
        if not isinstance(contents, str):
            return {**base, **self._inconclusive("contents-not-string")}
        try:
            body = json.loads(contents)
        except json.JSONDecodeError as exc:
            return {
                **base,
                **self._inconclusive(f"invalid-contents-json: {exc.msg}"),
            }
        if not isinstance(body, list):
            return {**base, **self._inconclusive("contents-not-list")}

        return {
            **base,
            "status": "readable",
            "reason": None,
            "body": body,
            "body_text": self._render_plain_text(body),
            "references": self._extract_references(body),
        }

    @staticmethod
    def _inconclusive(reason: str) -> dict[str, Any]:
        return {
            "status": "inconclusive",
            "reason": reason,
            "body": None,
            "body_text": None,
            "references": None,
        }

    @staticmethod
    def _error_reason(response: GraphQLResult) -> str:
        messages = [
            str(error.get("message"))
            for error in response.errors
            if error.get("message")
        ]
        return "; ".join(messages) or response.reason or "graphql-error"

    @classmethod
    def _extract_references(cls, body: list[Any]) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        for node in cls._walk_nodes(body):
            if node.get("type") != "custom-section":
                continue
            outer_config = node.get("config")
            if not isinstance(outer_config, Mapping):
                continue
            section_type_id = outer_config.get("sectionTypeId")
            section_config = outer_config.get("sectionConfig")
            config = (
                section_config.get("config")
                if isinstance(section_config, Mapping)
                else None
            )
            if not isinstance(section_type_id, str) or not isinstance(config, Mapping):
                continue
            references.append(
                {
                    "section_type_id": section_type_id,
                    "kind": section_type_id.removeprefix(SECTION_TYPE_PREFIX),
                    "config": dict(config),
                }
            )
        return references

    @classmethod
    def _walk_nodes(cls, nodes: list[Any]) -> Iterator[Mapping[str, Any]]:
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            yield node
            children = node.get("children")
            if isinstance(children, list):
                yield from cls._walk_nodes(children)

    @classmethod
    def _render_plain_text(cls, body: list[Any]) -> str:
        blocks: list[str] = []
        for node in body:
            text = "".join(cls._text_leaves(node))
            if text:
                blocks.append(text)
        return "\n".join(blocks)

    @classmethod
    def _text_leaves(cls, node: Any) -> Iterator[str]:
        if not isinstance(node, Mapping):
            return
        text = node.get("text")
        if isinstance(text, str):
            yield text
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                yield from cls._text_leaves(child)
