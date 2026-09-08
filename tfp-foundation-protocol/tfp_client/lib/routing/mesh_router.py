# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Mesh routing with Dijkstra's algorithm for optimal path finding.

Computes optimal routes through the peer mesh based on latency,
hop count, and route quality.
"""

import heapq
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime

from ..peer.peer_repository import PeerRepository
from ..peer.peer_models import MeshRoute

log = logging.getLogger(__name__)


@dataclass
class Route:
    """
    A route through the mesh network.

    Represents a path from source to destination with metrics.
    """
    destination_peer_id: str
    next_hop_peer_id: str
    hop_count: int
    latency_ms: Optional[int]
    route_quality: float
    last_updated: Optional[datetime]

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "destination_peer_id": self.destination_peer_id,
            "next_hop_peer_id": self.next_hop_peer_id,
            "hop_count": self.hop_count,
            "latency_ms": self.latency_ms,
            "route_quality": self.route_quality,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


@dataclass
class RoutingTable:
    """
    Complete routing table for the local peer.

    Maps destination peer IDs to optimal routes.
    """
    routes: Dict[str, Route] = field(default_factory=dict)
    last_rebuild: float = field(default_factory=time.time)

    def get_route(self, destination_peer_id: str) -> Optional[Route]:
        """Get route to destination."""
        return self.routes.get(destination_peer_id)

    def set_route(self, destination_peer_id: str, route: Route):
        """Set route to destination."""
        self.routes[destination_peer_id] = route

    def remove_route(self, destination_peer_id: str):
        """Remove route to destination."""
        if destination_peer_id in self.routes:
            del self.routes[destination_peer_id]

    def get_all_destinations(self) -> Set[str]:
        """Get all reachable destinations."""
        return set(self.routes.keys())


@dataclass
class RoutingConfig:
    """Configuration for routing behavior."""
    max_hops: int = 10
    max_latency_ms: int = 5000  # 5 seconds
    min_route_quality: float = 0.3
    route_cache_ttl_seconds: float = 60.0
    prefer_low_latency: bool = True
    prefer_few_hops: bool = True


class MeshRouter:
    """
    Mesh router using Dijkstra's algorithm for optimal path finding.

    Computes routes based on a weighted combination of:
    - Latency (ms)
    - Hop count
    - Route quality (0.0 - 1.0)
    """

    def __init__(
        self,
        peer_repo: PeerRepository,
        local_peer_id: str,
        config: Optional[RoutingConfig] = None,
    ):
        self._peer_repo = peer_repo
        self._local_peer_id = local_peer_id
        self._config = config or RoutingConfig()

        # Routing table cache
        self._routing_table: Optional[RoutingTable] = None

        # Graph representation: peer_id -> [(neighbor_id, weight), ...]
        self._graph: Dict[str, List[Tuple[str, float]]] = {}

    async def find_route(self, destination_peer_id: str) -> Optional[Route]:
        """
        Find optimal route to destination peer.

        Args:
            destination_peer_id: Target peer ID

        Returns:
            Optimal route or None if no route exists
        """
        # Check cache
        if self._routing_table and time.time() - self._routing_table.last_rebuild < self._config.route_cache_ttl_seconds:
            cached_route = self._routing_table.get_route(destination_peer_id)
            if cached_route:
                return cached_route

        # Rebuild routing table
        await self.rebuild_routing_table()

        return self._routing_table.get_route(destination_peer_id) if self._routing_table else None

    async def rebuild_routing_table(self) -> RoutingTable:
        """
        Rebuild the complete routing table using Dijkstra's algorithm.

        Returns:
            Updated routing table
        """
        # Build graph from mesh_routes table
        await self._build_graph()

        # Run Dijkstra from local peer
        distances, predecessors = self._dijkstra(self._local_peer_id)

        # Build routing table from shortest paths
        routing_table = RoutingTable()

        for destination, distance in distances.items():
            if destination == self._local_peer_id:
                continue

            # Reconstruct path
            path = self._reconstruct_path(predecessors, destination)
            if len(path) < 2:
                continue  # No valid path

            next_hop = path[1]  # First hop after local peer
            hop_count = len(path) - 1

            # Get route quality from database
            existing_routes = await self._peer_repo.get_routes_to_peer(destination)
            route_quality = 1.0
            latency_ms = None

            for route in existing_routes:
                if route.next_hop_peer_id == next_hop:
                    route_quality = route.route_quality
                    latency_ms = route.latency_ms
                    break

            # Create route
            route = Route(
                destination_peer_id=destination,
                next_hop_peer_id=next_hop,
                hop_count=hop_count,
                latency_ms=latency_ms,
                route_quality=route_quality,
                last_updated=datetime.now(),
            )

            routing_table.set_route(destination, route)

        self._routing_table = routing_table
        log.info(
            "Rebuilt routing table: %d reachable destinations",
            len(routing_table.routes),
        )

        return routing_table

    async def update_route_quality(
        self,
        destination_peer_id: str,
        next_hop_peer_id: str,
        success: bool,
    ) -> bool:
        """
        Update route quality based on success/failure.

        Args:
            destination_peer_id: Destination peer ID
            next_hop_peer_id: Next hop peer ID
            success: Whether the route attempt succeeded

        Returns:
            True if update succeeded
        """
        try:
            # Get existing routes
            existing_routes = await self._peer_repo.get_routes_to_peer(destination_peer_id)

            route_quality = 1.0
            for route in existing_routes:
                if route.next_hop_peer_id == next_hop_peer_id:
                    # Apply exponential moving average
                    if success:
                        route_quality = min(1.0, route.route_quality * 0.9 + 0.1)
                    else:
                        route_quality = max(0.0, route.route_quality * 0.9 - 0.1)
                    break

            # Update in database
            await self._peer_repo.upsert_route(
                destination_peer_id=destination_peer_id,
                next_hop_peer_id=next_hop_peer_id,
                hop_count=1,  # Will be updated by rebuild
                latency_ms=None,
                route_quality=route_quality,
            )

            # Invalidate cache
            self._routing_table = None

            log.debug(
                "Updated route quality: %s -> %s via %s = %.2f",
                self._local_peer_id,
                destination_peer_id,
                next_hop_peer_id,
                route_quality,
            )

            return True
        except Exception as exc:
            log.error("Failed to update route quality: %s", exc)
            return False

    async def get_routing_table(self) -> Dict[str, dict]:
        """
        Get current routing table as dictionary.

        Returns:
            Dictionary mapping destination peer IDs to route dicts
        """
        if not self._routing_table:
            await self.rebuild_routing_table()

        if not self._routing_table:
            return {}

        return {
            dest: route.to_dict()
            for dest, route in self._routing_table.routes.items()
        }

    async def _build_graph(self):
        """Build graph representation from mesh_routes table."""
        self._graph = {}

        # Get all peers
        all_peers = await self._peer_repo.list_peers(filters=None)
        peer_ids = {peer.peer_id for peer in all_peers}

        # Initialize graph
        for peer_id in peer_ids:
            self._graph[peer_id] = []

        # Add edges from peer connections
        # In a real implementation, this would query mesh_routes for learned routes
        # For now, we use direct peer connections as edges
        for peer_id in peer_ids:
            connections = await self._peer_repo.get_peer_connections(peer_id)
            for conn in connections:
                if conn.remote_peer_id in self._graph:
                    # Calculate edge weight
                    weight = self._calculate_edge_weight(conn)
                    self._graph[peer_id].append((conn.remote_peer_id, weight))
                    # Undirected graph: add reverse edge
                    self._graph[conn.remote_peer_id].append((peer_id, weight))

    def _calculate_edge_weight(self, connection) -> float:
        """
        Calculate edge weight for Dijkstra.

        Lower weight = better route.
        Weight = (latency_ms / 1000) * (1.0 - route_quality) + hop_count
        """
        latency = connection.latency_ms or 1000  # Default 1s
        quality = 1.0  # Connection quality not tracked yet
        hops = 1  # Direct connection

        # Normalize latency (0-5s range)
        latency_norm = min(latency / 5000.0, 1.0)

        # Combine factors
        if self._config.prefer_low_latency:
            weight = latency_norm * 0.7 + hops * 0.3
        else:
            weight = hops * 0.7 + latency_norm * 0.3

        return max(0.1, weight)  # Minimum weight to avoid zero

    def _dijkstra(self, source: str) -> Tuple[Dict[str, float], Dict[str, Optional[str]]]:
        """
        Run Dijkstra's algorithm from source peer.

        Args:
            source: Source peer ID

        Returns:
            Tuple of (distances dict, predecessors dict)
        """
        distances: Dict[str, float] = {source: 0.0}
        predecessors: Dict[str, Optional[str]] = {source: None}
        visited: Set[str] = set()

        # Priority queue: (distance, peer_id)
        pq = [(0.0, source)]

        while pq:
            current_dist, current = heapq.heappop(pq)

            if current in visited:
                continue

            visited.add(current)

            # Explore neighbors
            for neighbor, weight in self._graph.get(current, []):
                if neighbor in visited:
                    continue

                new_dist = current_dist + weight

                if neighbor not in distances or new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    predecessors[neighbor] = current
                    heapq.heappush(pq, (new_dist, neighbor))

        return distances, predecessors

    def _reconstruct_path(self, predecessors: Dict[str, Optional[str]], destination: str) -> List[str]:
        """
        Reconstruct path from predecessors.

        Args:
            predecessors: Predecessor dict from Dijkstra
            destination: Destination peer ID

        Returns:
            List of peer IDs from source to destination
        """
        path = []
        current = destination

        while current is not None:
            path.append(current)
            current = predecessors.get(current)

        path.reverse()
        return path

    async def invalidate_cache(self):
        """Invalidate routing table cache."""
        self._routing_table = None
        log.debug("Routing table cache invalidated")

    async def get_network_stats(self) -> dict:
        """
        Get network topology statistics.

        Returns:
            Dictionary with network stats
        """
        if not self._routing_table:
            await self.rebuild_routing_table()

        if not self._routing_table:
            return {"reachable_peers": 0, "avg_hops": 0, "avg_latency": 0}

        total_hops = sum(route.hop_count for route in self._routing_table.routes.values())
        avg_hops = total_hops / len(self._routing_table.routes) if self._routing_table.routes else 0

        total_latency = sum(
            route.latency_ms or 0 for route in self._routing_table.routes.values()
        )
        avg_latency = total_latency / len(self._routing_table.routes) if self._routing_table.routes else 0

        return {
            "reachable_peers": len(self._routing_table.routes),
            "avg_hops": round(avg_hops, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "total_nodes": len(self._graph),
            "last_rebuild": self._routing_table.last_rebuild,
        }

    async def handle_peer_failure(self, failed_peer_id: str) -> bool:
        """
        Handle peer failure by recalculating routes.

        Args:
            failed_peer_id: Peer ID that failed

        Returns:
            True if handling succeeded
        """
        try:
            log.warning("Handling peer failure: %s", failed_peer_id)

            # Remove routes that go through failed peer
            if self._routing_table:
                routes_to_remove = []
                for dest, route in self._routing_table.routes.items():
                    if route.next_hop_peer_id == failed_peer_id:
                        routes_to_remove.append(dest)

                for dest in routes_to_remove:
                    self._routing_table.remove_route(dest)
                    log.info("Removed route to %s via failed peer %s", dest, failed_peer_id)

            # Invalidate cache and rebuild
            await self.invalidate_cache()
            await self.rebuild_routing_table()

            log.info("Network self-healing complete after peer failure: %s", failed_peer_id)
            return True

        except Exception as exc:
            log.error("Failed to handle peer failure: %s", exc)
            return False
