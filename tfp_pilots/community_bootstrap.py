# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Community Pilot Kit - Ghost Node System
Solves the "empty room problem" by simulating network density for new users.
Addresses: "The real fix is finding one community that already has internal distribution needs"
"""

import json
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class GhostNode:
    """
    Simulated node that appears in the network to provide instant content availability.
    Provides realistic latency and behavior patterns.
    """

    def __init__(self, node_id: str, region: str, content_hashes: List[str]):
        self.node_id = node_id
        self.region = region
        self.content_hashes = content_hashes
        self.online = True
        # Use cryptographically secure random for latency simulation
        self.latency_ms = 20 + secrets.randbelow(
            181
        )  # Realistic latency variation (20-200ms)
        self.last_seen = datetime.utcnow()

    def has_content(self, content_hash: str) -> bool:
        """Check if this ghost node has the requested content."""
        return content_hash in self.content_hashes

    def get_latency(self) -> int:
        """Get current simulated latency with secure random variation."""
        # Secure random variation: -10 to +10 ms
        variation = secrets.randbelow(21) - 10
        return self.latency_ms + variation


class CommunityBootstrap:
    """
    Bootstrap system for new community deployments.
    Creates ghost nodes pre-seeded with relevant local content.
    """

    def __init__(self, community_id: str):
        self.community_id = community_id
        self.ghost_nodes: List[GhostNode] = []
        self.config_file = Path(f"/workspace/tfp_pilots/{community_id}_config.json")

    def create_ghost_network(
        self, region: str, content_library: List[Dict], node_count: int = 10
    ) -> None:
        """
        Create a network of ghost nodes pre-seeded with community content.

        Args:
            region: Geographic region (e.g., "Nairobi, Kenya")
            content_library: List of content items with hashes and categories
            node_count: Number of ghost nodes to create
        """
        print(f"\n🌍 Creating ghost network for {region}...")

        # Distribute content across ghost nodes (realistic caching pattern)
        # Popular content on more nodes, rare content on fewer
        content_popularity = {}
        for item in content_library:
            # Assign popularity score (0-1) based on category
            category = item.get("category", "general")
            if category == "emergency":
                popularity = 0.9  # Emergency content on 90% of nodes
            elif category == "education":
                popularity = 0.7
            elif category == "entertainment":
                popularity = 0.5
            else:
                popularity = 0.3

            content_popularity[item["hash"]] = popularity

        # Create ghost nodes
        for i in range(node_count):
            node_id = f"ghost_{self.community_id}_{i}"

            # Each node gets a subset of content based on popularity
            node_content = []
            for content_hash, popularity in content_popularity.items():
                if secrets.randbelow(100) < (popularity * 100):  # Secure random
                    node_content.append(content_hash)

            ghost_node = GhostNode(
                node_id=node_id, region=region, content_hashes=node_content
            )
            self.ghost_nodes.append(ghost_node)

        print(f"✓ Created {node_count} ghost nodes")
        print(f"  Total content items: {len(content_library)}")
        print(
            f"  Average content per node: {sum(len(n.content_hashes) for n in self.ghost_nodes) / node_count:.0f}"
        )

    def simulate_content_request(
        self, content_hash: str, user_region: str
    ) -> Dict[str, Any]:
        """
        Simulate a content request from a real user.
        Returns which ghost node would serve it and estimated latency.
        """
        start_time = time.time()

        # Find ghost nodes with this content
        available_nodes = [n for n in self.ghost_nodes if n.has_content(content_hash)]

        if not available_nodes:
            return {
                "success": False,
                "error": "Content not available in ghost network",
                "fallback_to_mesh": True,
            }

        # Select best node (lowest latency)
        best_node = min(available_nodes, key=lambda n: n.get_latency())
        latency = best_node.get_latency()

        elapsed = (time.time() - start_time) * 1000  # Convert to ms

        return {
            "success": True,
            "serving_node": best_node.node_id,
            "latency_ms": latency + elapsed,
            "region": best_node.region,
            "content_available": True,
            "perceived_network_density": len(self.ghost_nodes),
        }

    def load_community_content(self, content_file: str) -> List[Dict]:
        """Load community-specific content library from file."""
        if Path(content_file).exists():
            with open(content_file) as f:
                return json.load(f)

        # Default fallback content
        return [
            {"hash": "emergency_weather_001", "category": "emergency", "size_kb": 50},
            {"hash": "health_malaria_guide", "category": "education", "size_kb": 200},
            {"hash": "math_basics_video", "category": "education", "size_kb": 500},
            {
                "hash": "local_music_track_01",
                "category": "entertainment",
                "size_kb": 3000,
            },
            {"hash": "community_news_latest", "category": "general", "size_kb": 100},
        ]

    def generate_pilot_report(self) -> Dict[str, Any]:
        """Generate report on pilot deployment readiness."""
        if not self.ghost_nodes:
            return {"error": "No ghost network created"}

        total_content = set()
        for node in self.ghost_nodes:
            total_content.update(node.content_hashes)

        # Calculate content availability
        availability_stats = {}
        for content_hash in total_content:
            nodes_with_content = sum(
                1 for n in self.ghost_nodes if n.has_content(content_hash)
            )
            availability_percent = (nodes_with_content / len(self.ghost_nodes)) * 100

            # Categorize by availability
            if availability_percent >= 80:
                category = "highly_available"
            elif availability_percent >= 50:
                category = "moderately_available"
            else:
                category = "rare"

            if category not in availability_stats:
                availability_stats[category] = 0
            availability_stats[category] += 1

        return {
            "community_id": self.community_id,
            "ghost_node_count": len(self.ghost_nodes),
            "total_unique_content": len(total_content),
            "availability_distribution": availability_stats,
            "average_latency_ms": sum(n.latency_ms for n in self.ghost_nodes)
            / len(self.ghost_nodes),
            "pilot_ready": len(self.ghost_nodes) >= 5 and len(total_content) >= 10,
            "recommendations": self._generate_recommendations(availability_stats),
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

    def _generate_recommendations(self, availability_stats: Dict) -> List[str]:
        """Generate recommendations for improving pilot deployment."""
        recommendations = []

        highly_available = availability_stats.get("highly_available", 0)
        rare = availability_stats.get("rare", 0)

        if highly_available < 5:
            recommendations.append(
                "Increase ghost node count to improve content redundancy"
            )

        if rare > len(availability_stats) * 0.3:
            recommendations.append(
                "Focus content library on high-demand items; reduce long-tail content"
            )

        if len(self.ghost_nodes) >= 10:
            recommendations.append(
                "Ghost network sufficient for pilot; proceed to real-user testing"
            )

        return recommendations

    def save_pilot_config(self) -> None:
        """Save pilot configuration and ghost network state."""
        config = {
            "community_id": self.community_id,
            "ghost_nodes": [
                {
                    "node_id": n.node_id,
                    "region": n.region,
                    "content_count": len(n.content_hashes),
                    "latency_ms": n.latency_ms,
                }
                for n in self.ghost_nodes
            ],
            "report": self.generate_pilot_report(),
        }

        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

        print(f"\n✓ Pilot configuration saved to {self.config_file}")


def main():
    """Demo: Create a community pilot with ghost nodes."""
    print("=" * 60)
    print("TFP COMMUNITY PILOT KIT - GHOST NODE SYSTEM")
    print("=" * 60)

    # Initialize pilot for a sample community
    bootstrap = CommunityBootstrap(community_id="nairobi_schools_pilot")

    # Load or create content library
    content_library = bootstrap.load_community_content(
        "/workspace/tfp_pilots/nairobi_content.json"
    )

    # Create ghost network
    bootstrap.create_ghost_network(
        region="Nairobi, Kenya", content_library=content_library, node_count=15
    )

    # Simulate some user requests
    print("\n📱 Simulating user content requests...")
    test_hashes = [
        "emergency_weather_001",
        "health_malaria_guide",
        "local_music_track_01",
    ]

    for content_hash in test_hashes:
        result = bootstrap.simulate_content_request(content_hash, "Nairobi, Kenya")
        if result["success"]:
            print(
                f"  ✓ {content_hash}: served by {result['serving_node']} in {result['latency_ms']:.0f}ms"
            )
        else:
            print(f"  ✗ {content_hash}: not available (fallback to mesh)")

    # Generate and save pilot report
    report = bootstrap.generate_pilot_report()
    bootstrap.save_pilot_config()

    print("\n📊 PILOT READINESS REPORT:")
    print(f"  • Ghost nodes: {report['ghost_node_count']}")
    print(f"  • Unique content: {report['total_unique_content']}")
    print(
        f"  • Highly available: {report['availability_distribution'].get('highly_available', 0)} items"
    )
    print(f"  • Pilot ready: {'✓ YES' if report['pilot_ready'] else '✗ NEEDS WORK'}")

    if report["recommendations"]:
        print("\n💡 RECOMMENDATIONS:")
        for rec in report["recommendations"]:
            print(f"  • {rec}")

    print(
        "\n✅ Ghost network created. New users will perceive full network density immediately."
    )


if __name__ == "__main__":
    main()
