"""Graph service for entity co-occurrence network analysis.

Implements the ``GraphService`` protocol (PRD D3) using NetworkX for
in-memory graph computation. Provides ``get_neighbors()``,
``get_subgraph()``, and ``detect_clusters()`` operations.

The existing ``EntityGraphTool`` in ``dossier_tools.py`` computes
entity-to-case adjacency for report generation. This service generalises
that pattern for interactive entity exploration and API use.
"""

from __future__ import annotations

import contextlib
import logging
from collections import defaultdict
from datetime import datetime
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
        cluster_id: Optional community/cluster identifier.
        first_seen: Optional ISO-8601 date when the node was first observed.
        data: Additional metadata.
    """

    __slots__ = ("id", "label", "entity_type", "case_count", "risk_score", "cluster_id", "first_seen", "data")

    def __init__(
        self,
        *,
        id: str,
        label: str,
        entity_type: str,
        case_count: int = 0,
        risk_score: float = 0.0,
        cluster_id: str | None = None,
        first_seen: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.label = label
        self.entity_type = entity_type
        self.case_count = case_count
        self.risk_score = risk_score
        self.cluster_id = cluster_id
        self.first_seen = first_seen
        self.data = data or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict.

        Returns:
            Dict representation of the node.
        """
        result: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "entity_type": self.entity_type,
            "case_count": self.case_count,
            "risk_score": self.risk_score,
            "data": self.data,
        }
        if self.cluster_id is not None:
            result["cluster_id"] = self.cluster_id
        if self.first_seen is not None:
            result["first_seen"] = self.first_seen
        return result


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
        resolution: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Detect entity clusters using Louvain community detection (F-42).

        Uses ``networkx.community.louvain_communities`` with configurable
        resolution, falls back to connected components.

        Args:
            min_size: Minimum cluster size to include in results.
            resolution: Louvain resolution parameter (higher = more clusters).

        Returns:
            List of cluster dicts with ``id``, ``size``, ``members``,
            ``density``, ``avg_risk_score``, and ``entity_types``.
        """
        if self._graph is None:
            return []

        try:
            communities = nx.community.louvain_communities(self._graph, resolution=resolution, seed=42)
        except (AttributeError, Exception):
            communities = list(nx.connected_components(self._graph))

        clusters = []
        for i, community in enumerate(communities):
            if len(community) < min_size:
                continue

            subg = self._graph.subgraph(community)
            max_edges = len(community) * (len(community) - 1) / 2
            density = subg.number_of_edges() / max_edges if max_edges > 0 else 0.0

            risk_scores = [self._graph.nodes[n].get("risk_score", 0.0) for n in community]
            avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0.0

            entity_types: dict[str, int] = defaultdict(int)
            for n in community:
                etype = self._graph.nodes[n].get("entity_type", "unknown")
                entity_types[etype] += 1

            clusters.append(
                {
                    "id": f"cluster-{i}",
                    "size": len(community),
                    "members": sorted(community),
                    "density": round(density, 4),
                    "avg_risk_score": round(avg_risk, 2),
                    "entity_types": dict(entity_types),
                }
            )

        clusters.sort(key=lambda c: c["size"], reverse=True)
        return clusters

    def enrich_with_clusters(self) -> None:
        """Assign ``cluster_id`` to each node in the graph based on Louvain communities.

        Mutates the internal graph node attributes in-place so that subsequent
        ``serialize()`` calls include cluster membership.
        """
        if self._graph is None:
            return

        clusters = self.detect_clusters(min_size=1)
        for cluster in clusters:
            for member in cluster["members"]:
                if member in self._graph:
                    self._graph.nodes[member]["cluster_id"] = cluster["id"]

    def get_temporal_snapshots(
        self,
        timestamps: dict[str, str],
        *,
        intervals: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate timestamped graph snapshots for animation (F-41).

        Produces a series of cumulative graph states by filtering nodes/edges
        that existed on or before each interval boundary. The frontend can
        animate through these snapshots with a date slider.

        Args:
            timestamps: Mapping of ``node_id`` → ISO-8601 first-seen date.
            intervals: Ordered list of ISO-8601 date boundaries. If ``None``,
                automatically derived from the earliest and latest dates
                using monthly intervals.

        Returns:
            List of snapshot dicts, each with ``date``, ``nodes``, ``edges``,
            ``node_count``, and ``edge_count``.
        """
        if self._graph is None:
            return []

        # Parse timestamps
        node_dates: dict[str, datetime] = {}
        for nid, ts in timestamps.items():
            if nid in self._graph:
                with contextlib.suppress(ValueError, TypeError):
                    node_dates[nid] = datetime.fromisoformat(ts)

        if not node_dates:
            return []

        # Auto-generate monthly intervals if not provided
        if intervals is None:
            sorted_dates = sorted(node_dates.values())
            start = sorted_dates[0].replace(day=1)
            end = sorted_dates[-1]
            intervals = []
            current = start
            while current <= end:
                intervals.append(current.isoformat())
                month = current.month + 1
                year = current.year
                if month > 12:
                    month = 1
                    year += 1
                current = current.replace(year=year, month=month)
            # Always include the final date
            if intervals and intervals[-1] < end.isoformat():
                intervals.append(end.isoformat())

        snapshots: list[dict[str, Any]] = []
        for boundary_str in intervals:
            boundary = datetime.fromisoformat(boundary_str)
            visible_nodes = {nid for nid, dt in node_dates.items() if dt <= boundary}

            nodes = []
            for n in visible_nodes:
                data = self._graph.nodes[n]
                nodes.append(
                    GraphNode(
                        id=n,
                        label=data.get("label", n),
                        entity_type=data.get("entity_type", "unknown"),
                        case_count=data.get("case_count", 0),
                        risk_score=data.get("risk_score", 0.0),
                        cluster_id=data.get("cluster_id"),
                        first_seen=timestamps.get(n),
                    ).to_dict()
                )

            edges = []
            for u, v, edata in self._graph.edges(data=True):
                if u in visible_nodes and v in visible_nodes:
                    edges.append(
                        GraphEdge(
                            source=u,
                            target=v,
                            weight=edata.get("weight", 1),
                            edge_type=edata.get("edge_type", "co-occurrence"),
                        ).to_dict()
                    )

            snapshots.append(
                {
                    "date": boundary_str,
                    "nodes": nodes,
                    "edges": edges,
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                }
            )

        return snapshots

    def add_infrastructure_edges(
        self,
        infra_edges: list[dict[str, Any]],
    ) -> None:
        """Add infrastructure-derived edges to the graph (F-44 / S5-09).

        These edges represent relationships discovered by the infrastructure
        clustering job (shared IP, shared registrar, shared hosting).

        Args:
            infra_edges: List of dicts with ``source``, ``target``,
                ``edge_type`` (e.g. ``shared_ip``, ``shared_registrar``),
                and optional ``weight``.
        """
        if self._graph is None:
            return

        for edge in infra_edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if not src or not tgt:
                continue
            if src not in self._graph or tgt not in self._graph:
                continue
            etype = edge.get("edge_type", "infrastructure")
            weight = edge.get("weight", 1)
            if self._graph.has_edge(src, tgt):
                # Keep existing edge but add infra edge type if different
                existing_type = self._graph[src][tgt].get("edge_type", "co-occurrence")
                if existing_type != etype:
                    self._graph[src][tgt]["edge_type"] = f"{existing_type},{etype}"
                    self._graph[src][tgt]["weight"] = max(self._graph[src][tgt]["weight"], weight)
            else:
                self._graph.add_edge(src, tgt, weight=weight, edge_type=etype)

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

    def serialize(self, *, include_layout: bool = False, include_clusters: bool = False) -> dict[str, Any]:
        """Serialize the full graph payload for API responses (S2-13).

        Args:
            include_layout: Include pre-computed layout coordinates
                for graphs exceeding the layout threshold.
            include_clusters: Run cluster detection and annotate nodes
                with their community membership.

        Returns:
            Dict with ``nodes``, ``edges``, ``node_count``, ``edge_count``,
            optional ``layout``, and optional ``clusters``.
        """
        if self._graph is None:
            return {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0}

        if include_clusters:
            self.enrich_with_clusters()

        nodes = []
        for n, data in self._graph.nodes(data=True):
            nodes.append(
                GraphNode(
                    id=n,
                    label=data.get("label", n),
                    entity_type=data.get("entity_type", "unknown"),
                    case_count=data.get("case_count", 0),
                    risk_score=data.get("risk_score", 0.0),
                    cluster_id=data.get("cluster_id"),
                    first_seen=data.get("first_seen"),
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

        if include_clusters:
            result["clusters"] = self.detect_clusters()

        return result
