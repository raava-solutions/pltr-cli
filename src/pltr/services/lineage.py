"""Bounded native resource graph construction.

The public SDK does not expose a transformation-lineage endpoint.  This
service therefore builds a graph from verified filesystem relationships:
parent/child resources and project references.  The response always carries
an incomplete-coverage record so it cannot be mistaken for full data lineage.
"""

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from ..utils.pagination import PaginationMetadata
from .base import BaseService


class LineageService(BaseService):
    """Build bounded graphs from native Compass resource relationships."""

    DEFAULT_MAX_DEPTH = 2
    DEFAULT_MAX_NODES = 100
    DEFAULT_MAX_EDGES = 200

    def _get_service(self) -> Any:
        return self.client.filesystem

    def get_resource_graph(
        self,
        resource_rid: str,
        *,
        direction: str = "both",
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_edges: int = DEFAULT_MAX_EDGES,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return a bounded graph with stable node and edge identities."""
        if not resource_rid.strip():
            raise ValueError("resource_rid must not be empty")
        if direction not in {"upstream", "downstream", "both"}:
            raise ValueError("direction must be upstream, downstream, or both")
        if max_depth < 0:
            raise ValueError("max_depth must be greater than or equal to zero")
        if max_nodes <= 0 or max_edges <= 0:
            raise ValueError("max_nodes and max_edges must be greater than zero")
        if page_size is not None and page_size <= 0:
            raise ValueError("page_size must be greater than zero")

        after_edge_id = self._parse_page_token(page_token)
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: Dict[str, Dict[str, Any]] = {}
        queued: Set[str] = set()
        visited: Set[Tuple[str, int]] = set()
        queue: Deque[Tuple[str, int, Optional[Any]]] = deque()
        gaps: Set[str] = {
            "The SDK exposes no transformation or dataset-lineage endpoint; "
            "only filesystem hierarchy and project-reference edges are included."
        }

        try:
            root_resource = self.service.Resource.get(resource_rid)
        except Exception as e:
            raise RuntimeError(
                f"Failed to get graph root {resource_rid}: {self._format_error_detail(e)}"
            )

        self._add_node(nodes, root_resource, resource_rid, max_nodes, gaps)
        queue.append((resource_rid, 0, root_resource))
        queued.add(resource_rid)

        while queue:
            current_rid, depth, current_resource = queue.popleft()
            visit_key = (current_rid, depth)
            if visit_key in visited:
                continue
            visited.add(visit_key)
            if depth >= max_depth:
                continue

            current_type = str(self._value(current_resource, "type") or "").lower()

            if direction in {"upstream", "both"}:
                parent_rid = self._value(current_resource, "parent_folder_rid")
                if parent_rid:
                    self._add_relationship(
                        nodes,
                        edges,
                        source_rid=current_rid,
                        target_rid=str(parent_rid),
                        relation="parent",
                        target_resource=self._safe_get_resource(str(parent_rid), gaps),
                        max_nodes=max_nodes,
                        max_edges=max_edges,
                        gaps=gaps,
                    )
                    if str(parent_rid) not in queued and len(nodes) < max_nodes:
                        queued.add(str(parent_rid))
                        queue.append(
                            (
                                str(parent_rid),
                                depth + 1,
                                nodes.get(self._node_id(str(parent_rid))),
                            )
                        )

            if direction in {"downstream", "both"} and current_type in {
                "folder",
                "project",
                "compass_folder",
            }:
                try:
                    children_iterator = self.service.Folder.children(current_rid)
                    children, child_next_token = self._read_sdk_page(children_iterator)
                    if child_next_token is not None:
                        gaps.add(
                            f"Children of {current_rid} were truncated at one "
                            "SDK page; use a narrower traversal bound."
                        )
                    for child in children:
                        child_rid = self._value(child, "rid")
                        if not child_rid:
                            gaps.add(
                                f"A child of {current_rid} had no RID and was skipped."
                            )
                            continue
                        child_rid = str(child_rid)
                        self._add_relationship(
                            nodes,
                            edges,
                            source_rid=current_rid,
                            target_rid=child_rid,
                            relation="child",
                            target_resource=child,
                            max_nodes=max_nodes,
                            max_edges=max_edges,
                            gaps=gaps,
                        )
                        if child_rid not in queued and len(nodes) < max_nodes:
                            queued.add(child_rid)
                            queue.append((child_rid, depth + 1, child))
                except Exception as e:
                    gaps.add(
                        f"Children of {current_rid} were inaccessible: "
                        f"{self._format_error_detail(e)}"
                    )

            if current_type == "project" and direction in {"upstream", "both"}:
                try:
                    reference_iterator = self.service.Project.Reference.list(
                        current_rid
                    )
                    references, reference_next_token = self._read_sdk_page(
                        reference_iterator
                    )
                    if reference_next_token is not None:
                        gaps.add(
                            f"References of {current_rid} were truncated at one "
                            "SDK page."
                        )
                    for item in references:
                        reference = self._value(item, "reference") or item
                        target_rid = self._value(reference, "resource_rid")
                        if not target_rid:
                            gaps.add(
                                f"A reference of {current_rid} had no resource RID and was skipped."
                            )
                            continue
                        target_rid = str(target_rid)
                        self._add_relationship(
                            nodes,
                            edges,
                            source_rid=current_rid,
                            target_rid=target_rid,
                            relation="reference",
                            target_resource=self._safe_get_resource(target_rid, gaps),
                            max_nodes=max_nodes,
                            max_edges=max_edges,
                            gaps=gaps,
                        )
                        if target_rid not in queued and len(nodes) < max_nodes:
                            queued.add(target_rid)
                            queue.append((target_rid, depth + 1, None))
                except Exception as e:
                    gaps.add(
                        f"References of {current_rid} were inaccessible: "
                        f"{self._format_error_detail(e)}"
                    )

        all_edges = sorted(edges.values(), key=lambda edge: edge["id"])
        remaining_edges = [edge for edge in all_edges if edge["id"] > after_edge_id]
        page = remaining_edges if page_size is None else remaining_edges[:page_size]
        last_edge_id = page[-1]["id"] if page else ""
        next_token = (
            f"resource-graph-after:{last_edge_id}"
            if page_size is not None
            and last_edge_id
            and len(page) == page_size
            and any(edge["id"] > last_edge_id for edge in remaining_edges)
            else None
        )

        coverage = {
            "status": "incomplete",
            "complete": False,
            "edge_types": sorted({edge["relation"] for edge in all_edges}),
            "gaps": sorted(gaps),
        }
        return {
            "root_rid": resource_rid,
            "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
            "edges": page,
            "coverage": coverage,
            "pagination": PaginationMetadata(
                current_page=1,
                items_fetched=len(page),
                next_page_token=next_token,
                has_more=next_token is not None,
                total_pages_fetched=1,
            ).to_dict(),
        }

    def _add_relationship(
        self,
        nodes: Dict[str, Dict[str, Any]],
        edges: Dict[str, Dict[str, Any]],
        *,
        source_rid: str,
        target_rid: str,
        relation: str,
        target_resource: Optional[Any],
        max_nodes: int,
        max_edges: int,
        gaps: Set[str],
    ) -> None:
        self._add_node(nodes, target_resource, target_rid, max_nodes, gaps)
        if self._node_id(target_rid) not in nodes:
            return
        edge_id = self._edge_id(source_rid, target_rid, relation)
        if edge_id in edges:
            return
        if len(edges) >= max_edges:
            gaps.add(f"Graph edge limit ({max_edges}) was reached.")
            return
        edges[edge_id] = {
            "id": edge_id,
            "source": self._node_id(source_rid),
            "target": self._node_id(target_rid),
            "source_rid": source_rid,
            "target_rid": target_rid,
            "relation": relation,
        }

    def _add_node(
        self,
        nodes: Dict[str, Dict[str, Any]],
        resource: Optional[Any],
        rid: str,
        max_nodes: int,
        gaps: Set[str],
    ) -> None:
        node_id = self._node_id(rid)
        if node_id in nodes:
            return
        if len(nodes) >= max_nodes:
            gaps.add(f"Graph node limit ({max_nodes}) was reached.")
            return
        nodes[node_id] = {
            "id": node_id,
            "rid": rid,
            "display_name": self._value(resource, "display_name"),
            "path": self._value(resource, "path"),
            "type": self._value(resource, "type"),
            "available": resource is not None,
        }

    def _safe_get_resource(self, rid: str, gaps: Set[str]) -> Optional[Any]:
        if (
            rid.startswith("ri.compass.main.space.")
            or rid == "ri.compass.main.folder.0"
        ):
            return None
        try:
            return self.service.Resource.get(rid)
        except Exception as e:
            gaps.add(f"Resource {rid} was inaccessible: {self._format_error_detail(e)}")
            return None

    @staticmethod
    def _read_sdk_page(iterator: Any) -> Tuple[List[Any], Optional[str]]:
        page_data = getattr(iterator, "data", None)
        if page_data is not None and not isinstance(page_data, (list, tuple)):
            raise TypeError("SDK page data must be a list")
        if isinstance(page_data, (list, tuple)):
            raw_items = list(page_data)
        else:
            if isinstance(iterator, (str, bytes, dict)):
                raise TypeError("SDK page response must be an iterator")
            raw_items = list(iterator)
        next_token = getattr(iterator, "next_page_token", None)
        if not isinstance(next_token, str) or not next_token:
            next_token = None
        return raw_items, next_token

    @staticmethod
    def _value(value: Any, field: str) -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get(field)
        return getattr(value, field, None)

    @staticmethod
    def _node_id(rid: str) -> str:
        return f"foundry:rid:{rid}"

    @classmethod
    def _edge_id(cls, source_rid: str, target_rid: str, relation: str) -> str:
        return f"foundry:edge:{relation}:{source_rid}:{target_rid}"

    @staticmethod
    def _parse_page_token(page_token: Optional[str]) -> str:
        if page_token is None:
            return ""
        prefix = "resource-graph-after:"
        if not page_token.startswith(prefix):
            raise ValueError("invalid resource graph page_token")
        after_edge_id = page_token[len(prefix) :]
        if not after_edge_id:
            raise ValueError("invalid resource graph page_token")
        return after_edge_id

    @staticmethod
    def _format_error_detail(error: Exception) -> str:
        message = str(error).strip()
        if message:
            return message
        return error.__class__.__name__
