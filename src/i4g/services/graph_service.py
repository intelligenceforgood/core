"""Graph service for entity co-occurrence network analysis.

Implements the ``GraphService`` protocol (PRD D3) using NetworkX for
in-memory graph computation. Provides ``get_neighbors()``,
``get_subgraph()``, and ``detect_clusters()`` operations.

The existing ``EntityGraphTool`` in ``dossier_tools.py`` computes
entity-to-case adjacency for report generation. This service generalises
that pattern for interactive entity exploration and API use.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Protocol

logger = logging.getLogger(__name__)

try:
    import networkx as nx

    _HAS_NETWORKX = True
except ImportError:  # pragma: no cover
    _HAS_NETWORKX = False


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class GraphServiceProtocol(Protocol):
    """Protocol for graph operations."""

    def get_neighbors(
        self,
        seed_id: str,
        *,
        hops: int = 1,
        entity_types: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return neighbors of a seed node."""
        ...

    def get_subgraph(
        self,
        node_ids: list[str],
        *,
        include_edges: bool = True,
    ) -> dict[str, Any]:
        """Extract a subgraph containing the given nodes."""
        ...

    def detect_clusters(
        self,
        *,
        min_size: int = 3,
    ) -> list[dict[str, Any]]:
        """Detect clusters/communities in the graph."""
        ...


# ---------------------------------------------------------------------------
# Node / Edge types
# ---------------------------------------------------------------------------


class GraphNode:
    """Representation of a graph node.

    Attributes:
        id: Unique node identifier (``entity_type:canonical_value``).
        label: Display label.
        entity_type: The entity type.
        case_count: Number of linked cases.
        risk_score: Maximum risk score across linked cases.
        data: Additional metadata.
    """

    __slots__ = ("id", "label", "entity_type", "case_count", "risk_score", "data")

    def __init__(
        self,
        *,
        id: str,
        label: str,
        entity_type: str,
        case_count: int = 0,
        risk_score: float = 0.0,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.label = label
        self.entity_type = entity_type
        self.case_count = case_count
        self.risk_score = risk_score
        self.data = data or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict.

        Returns:
            Dict representation of the node.
        """
        return {
            "id": self.id,
            "label": self.label,
            "entity_type": self.entity_type,
            "case_count": self.case_count,
            "risk_score": self.risk_score,
            "data": self.data,
        }


class GraphEdge:
    """Representation of a graph edge.

    Attributes:
        source: Source node ID.
        target: Target node ID.
        weight: Edge weight (number of shared cases).
        edge_type: Type of relationship.
    """

    __slots__ = ("source", "target", "weight", "edge_type")

    def __init__(
        self,
        *,
        source: str,
        target: str,
        weight: int = 1,
        edge_type: str = "co-occurrence",
    ) -> None:
        self.source = source
        self.target = target
        self.weight = weight
        self.edge_type = edge_type

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict.

        Returns:
            Dict representation of the edge.
        """
        return {
            "source": self.source,
            "target": self.target,
            "weight": self.weight,
            "edge_type": self.edge_type,
        }


# ---------------------------------------------------------------------------
# GraphService implementation
# ---------------------------------------------------------------------------

# Threshold above which server-side layout pre-computation is triggered (D13).
_LAYOUT_THRESHOLD = 500


class GraphService:
    """In-memory graph service using NetworkX.

    Builds a co-occurrence graph from entity-case adjacency data,
    then provides neighbor lookup, subgraph extraction, and community
    detection.

    Args:
        adjacency: Mapping of ``entity_id`` → list of ``case_id``.
        entity_meta: Optional mapping of ``entity_id`` → metadata dict
            (entity_type, label, case_count, risk_score).
    """

    def __init__(
        self,
        adjacency: dict[str, list[str]],
        entity_meta: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._adjacency = adjacency
        self._entity_meta = entity_meta or {}
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        """Build a NetworkX graph from entity-case adjacency.

        Returns:
            NetworkX Graph instance.
        """
        if not _HAS_NETWORKX:
            logger.warning("NetworkX not installed — graph operations disabled")
            return None

        g = nx.Graph()

        # Add entity nodes
        for entity_id, case_ids in self._adjacency.items():
            meta = self._entity_meta.get(entity_id, {})
            g.add_node(
                entity_id,
                entity_type=meta.get("entity_type", "unknown"),
                label=meta.get("label", entity_id),
                case_count=len(set(case_ids)),
                risk_score=meta.get("risk_score", 0.0),
            )

        # Build co-occurrence edges
        case_to_entities: dict[str, list[str]] = defaultdict(list)
        for entity_id, case_ids in self._adjacency.items():
            for cid in case_ids:
                case_to_entities[cid].append(entity_id)

        for _case_id, entity_ids in case_to_entities.items():
            for i, e1 in enumerate(entity_ids):
                for e2 in entity_ids[i + 1 :]:
                    if g.has_edge(e1, e2):
                        g[e1][e2]["weight"] += 1
                    else:
                        g.add_edge(e1, e2, weight=1, edge_type="co-occurrence")

        return g

    def get_neighbors(
        self,
        seed_id: str,
        *,
        hops: int = 1,
        entity_types: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return nodes within N hops of the seed node.

        Args:
            seed_id: ID of the seed node.
            hops: Number of hops to traverse (1 or 2).
            entity_types: Filter neighbors by entity type.
            limit: Max neighbors to return.

        Returns:
            Dict with ``nodes``, ``edges``, and ``seed``.
        """
        if self._graph is None or seed_id not in self._graph:
            return {"seed": seed_id, "nodes": [], "edges": []}

        # BFS up to N hops
        visited = {seed_id}
        frontier = {seed_id}
        for _hop in range(hops):
            next_frontier: set[str] = set()
            for node in frontier:
                for neighbor in self._graph.neighbors(node):
                    if neighbor not in visited:
                        next_frontier.add(neighbor)
                        visited.add(neighbor)
            frontier = next_frontier

        # Filter by entity type
        if entity_types:
            type_set = set(entity_types)
            visited = {n for n in visited if self._graph.nodes[n].get("entity_type") in type_set or n == seed_id}

        # Build nodes and edges
        nodes = []
        for n in visited:
            node_data = self._graph.nodes[n]
            nodes.append(
                GraphNode(
                    id=n,
                    label=node_data.get("label", n),
                    entity_type=node_data.get("entity_type", "unknown"),
                    case_count=node_data.get("case_count", 0),
                    risk_score=node_data.get("risk_score", 0.0),
                ).to_dict()
            )

        # Sort by case_count descending and limit
        nodes.sort(key=lambda x: x["case_count"], reverse=True)
        if len(nodes) > limit + 1:  # +1 for seed
            top_ids = {n["id"] for n in nodes[: limit + 1]}
            top_ids.add(seed_id)
            nodes = [n for n in nodes if n["id"] in top_ids]

        node_ids = {n["id"] for n in nodes}
        edges = []
        for u, v, data in self._graph.edges(data=True):
            if u in node_ids and v in node_ids:
                edges.append(
                    GraphEdge(
                        source=u,
                        target=v,
                        weight=data.get("weight", 1),
                        edge_type=data.get("edge_type", "co-occurrence"),
                    ).to_dict()
                )

        return {"seed": seed_id, "nodes": nodes, "edges": edges}

    def get_subgraph(
        self,
        node_ids: list[str],
        *,
        include_edges: bool = True,
    ) -> dict[str, Any]:
        """Extract a subgraph containing the specified nodes.

        Args:
            node_ids: List of node IDs to include.
            include_edges: Whether to include edges between included nodes.

        Returns:
            Dict with ``nodes`` and optional ``edges``.
        """
        if self._graph is None:
            return {"nodes": [], "edges": []}

        valid_ids = {n for n in node_ids if n in self._graph}
        nodes = []
        for n in valid_ids:
            node_data = self._graph.nodes[n]
            nodes.append(
                GraphNode(
                    id=n,
                    label=node_data.get("label", n),
                    entity_type=node_data.get("entity_type", "unknown"),
                    case_count=node_data.get("case_count", 0),
                    risk_score=node_data.get("risk_score", 0.0),
                ).to_dict()
            )

        edges = []
        if include_edges:
            for u, v, data in self._graph.edges(data=True):
                if u in valid_ids and v in valid_ids:
                    edges.append(
                        GraphEdge(
                            source=u,
                            target=v,
                            weight=data.get("weight", 1),
                            edge_type=data.get("edge_type", "co-occurrence"),
                        ).to_dict()
                    )

        return {"nodes": nodes, "edges": edges}

    def detect_clusters(
        self,
        *,
        min_size: int = 3,
    ) -> list[dict[str, Any]]:
        """Detect entity clusters using connected components and community detection.

        Uses Louvain community detection when available, falls back to
        connected components.

        Args:
            min_size: Minimum cluster size to include in results.

        Returns:
            List of cluster dicts with ``id``, ``size``, ``members``.
        """
        if self._graph is None:
            return []

        try:
            communities = nx.community.louvain_communities(self._graph)
        except (AttributeError, Exception):
            # Fall back to connected components
            communities = list(nx.connected_components(self._graph))

        clusters = []
        for i, community in enumerate(communities):
            if len(community) >= min_size:
                clusters.append(
                    {
                        "id": f"cluster-{i}",
                        "size": len(community),
                        "members": sorted(community),
                    }
                )

        clusters.sort(key=lambda c: c["size"], reverse=True)
        return clusters

    def compute_layout(self) -> dict[str, dict[str, float]]:
        """Compute server-side layout positions for large graphs (D13).

        Uses spring_layout for graphs exceeding the threshold of
        500 nodes, providing pre-computed x/y coordinates.

        Returns:
            Mapping of node_id → {x, y} coordinates.
        """
        if self._graph is None:
            return {}

        if len(self._graph) < _LAYOUT_THRESHOLD:
            return {}

        pos = nx.spring_layout(self._graph, seed=42, iterations=50)
        return {node: {"x": float(coords[0]), "y": float(coords[1])} for node, coords in pos.items()}

    def serialize(self, *, include_layout: bool = False) -> dict[str, Any]:
        """Serialize the full graph payload for API responses (S2-13).

        Args:
            include_layout: Include pre-computed layout coordinates
                for graphs exceeding the layout threshold.

        Returns:
            Dict with ``nodes``, ``edges``, ``node_count``, ``edge_count``,
            and optional ``layout``.
        """
        if self._graph is None:
            return {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0}

        nodes = []
        for n, data in self._graph.nodes(data=True):
            nodes.append(
                GraphNode(
                    id=n,
                    label=data.get("label", n),
                    entity_type=data.get("entity_type", "unknown"),
                    case_count=data.get("case_count", 0),
                    risk_score=data.get("risk_score", 0.0),
                ).to_dict()
            )

        edges = []
        for u, v, data in self._graph.edges(data=True):
            edges.append(
                GraphEdge(
                    source=u,
                    target=v,
                    weight=data.get("weight", 1),
                    edge_type=data.get("edge_type", "co-occurrence"),
                ).to_dict()
            )

        result: dict[str, Any] = {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

        if include_layout:
            layout = self.compute_layout()
            if layout:
                result["layout"] = layout

        return result
