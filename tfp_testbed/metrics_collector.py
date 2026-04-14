# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Testbed Metrics Collector
Collects real-world performance data from deployed testbed nodes.
Addresses: "Metrics for the testbed" - provides empirical proof over simulations.
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class PerformanceMetric:
    """Single performance measurement."""

    timestamp: str
    metric_type: str  # bandwidth, latency, reconstruction_time, etc.
    value: float
    unit: str
    node_id: str
    region: str
    network_conditions: str  # wifi, mesh, broadcast, offline


@dataclass
class TestbedConfig:
    """Configuration for a testbed deployment."""

    testbed_id: str
    region: str
    node_count: int
    deployment_date: str
    duration_days: int
    target_metrics: List[str]
    success_criteria: Dict[str, float]


class MetricsCollector:
    """
    Collects, aggregates, and reports real-world testbed metrics.
    Designed for NGO/enterprise validation of protocol performance.
    """

    def __init__(self, testbed_id: str = "testbed_001"):
        self.testbed_id = testbed_id
        self.metrics_file = Path(f"/workspace/tfp_testbed/{testbed_id}_metrics.jsonl")
        self.config_file = Path(f"/workspace/tfp_testbed/{testbed_id}_config.json")
        self.metrics: List[PerformanceMetric] = []

    def initialize_testbed(self, config: TestbedConfig) -> None:
        """Initialize a new testbed with configuration."""
        with open(self.config_file, "w") as f:
            json.dump(asdict(config), f, indent=2)
        print(f"✓ Testbed {config.testbed_id} initialized in {config.region}")

    def record_metric(self, metric: PerformanceMetric) -> None:
        """Record a single metric to the metrics log."""
        self.metrics.append(metric)

        # Append to JSONL file
        with open(self.metrics_file, "a") as f:
            f.write(json.dumps(asdict(metric)) + "\n")

    def record_bandwidth_savings(
        self, original_size: float, compressed_size: float, node_id: str, region: str
    ) -> None:
        """
        Record bandwidth savings from RaptorQ + chunk caching.
        Key metric for NGO/humanitarian use cases.
        """
        savings_percent = (
            ((original_size - compressed_size) / original_size) * 100
            if original_size > 0
            else 0
        )

        metric = PerformanceMetric(
            timestamp=datetime.utcnow().isoformat() + "Z",
            metric_type="bandwidth_savings",
            value=savings_percent,
            unit="percent",
            node_id=node_id,
            region=region,
            network_conditions="mesh",
        )
        self.record_metric(metric)
        return savings_percent

    def record_reconstruction_time(
        self,
        content_hash: str,
        reconstruction_ms: float,
        node_id: str,
        region: str,
        network_type: str,
    ) -> None:
        """Record content reconstruction time (hash → playable content)."""
        metric = PerformanceMetric(
            timestamp=datetime.utcnow().isoformat() + "Z",
            metric_type="reconstruction_time",
            value=reconstruction_ms,
            unit="milliseconds",
            node_id=node_id,
            region=region,
            network_conditions=network_type,
        )
        self.record_metric(metric)

    def record_node_churn(
        self,
        active_nodes: int,
        total_nodes: int,
        churn_rate: float,
        node_id: str,
        region: str,
    ) -> None:
        """
        Record node churn tolerance.
        Measures network resilience to nodes joining/leaving.
        """
        availability = (active_nodes / total_nodes) * 100 if total_nodes > 0 else 0

        metric = PerformanceMetric(
            timestamp=datetime.utcnow().isoformat() + "Z",
            metric_type="node_availability",
            value=availability,
            unit="percent",
            node_id=node_id,
            region=region,
            network_conditions=f"churn_rate:{churn_rate}",
        )
        self.record_metric(metric)

    def aggregate_metrics(self, time_window_hours: int = 24) -> Dict[str, Any]:
        """
        Aggregate metrics over a time window.
        Returns statistics useful for reports and evaluations.
        """
        cutoff_time = time.time() - (time_window_hours * 3600)

        # Load recent metrics
        recent_metrics = []
        if self.metrics_file.exists():
            with open(self.metrics_file) as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        metric_time = datetime.fromisoformat(
                            data["timestamp"].replace("Z", "+00:00")
                        )
                        if metric_time.timestamp() > cutoff_time:
                            recent_metrics.append(PerformanceMetric(**data))
                    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                        # Skip malformed or incomplete metric entries
                        continue

        # Group by metric type
        grouped = {}
        for metric in recent_metrics:
            if metric.metric_type not in grouped:
                grouped[metric.metric_type] = []
            grouped[metric.metric_type].append(metric.value)

        # Calculate statistics
        stats = {}
        for metric_type, values in grouped.items():
            if not values:
                continue

            stats[metric_type] = {
                "count": len(values),
                "mean": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "median": sorted(values)[len(values) // 2],
                "unit": recent_metrics[0].unit if recent_metrics else "unknown",
            }

        return {
            "testbed_id": self.testbed_id,
            "time_window_hours": time_window_hours,
            "total_metrics": len(recent_metrics),
            "statistics": stats,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

    def generate_testbed_report(self) -> Dict[str, Any]:
        """Generate comprehensive testbed report for stakeholders."""
        aggregated = self.aggregate_metrics(time_window_hours=720)  # 30 days

        # Load config
        config = {}
        if self.config_file.exists():
            with open(self.config_file) as f:
                config = json.load(f)

        # Success assessment
        success_criteria = config.get("success_criteria", {})
        achievements = {}

        for criterion, target in success_criteria.items():
            if criterion in aggregated["statistics"]:
                actual = aggregated["statistics"][criterion]["mean"]
                achieved = (
                    actual >= target
                    if "savings" in criterion or "availability" in criterion
                    else actual <= target
                )
                achievements[criterion] = {
                    "target": target,
                    "actual": actual,
                    "achieved": achieved,
                }

        report = {
            "testbed_id": self.testbed_id,
            "region": config.get("region", "unknown"),
            "deployment_date": config.get("deployment_date", "unknown"),
            "duration_days": config.get("duration_days", 0),
            "metrics_summary": aggregated,
            "success_achievements": achievements,
            "overall_success_rate": sum(
                1 for a in achievements.values() if a["achieved"]
            )
            / len(achievements)
            * 100
            if achievements
            else 0,
            "recommendations": self._generate_recommendations(aggregated, achievements),
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

        return report

    def _generate_recommendations(
        self, aggregated: Dict, achievements: Dict
    ) -> List[str]:
        """Generate actionable recommendations based on metrics."""
        recommendations = []

        # Check bandwidth savings
        if "bandwidth_savings" in aggregated["statistics"]:
            savings = aggregated["statistics"]["bandwidth_savings"]["mean"]
            if savings < 50:
                recommendations.append(
                    "Consider increasing chunk cache size to improve bandwidth savings"
                )
            elif savings > 80:
                recommendations.append(
                    "Excellent bandwidth efficiency; document case study for NGOs"
                )

        # Check reconstruction time
        if "reconstruction_time" in aggregated["statistics"]:
            recon_time = aggregated["statistics"]["reconstruction_time"]["mean"]
            if recon_time > 5000:  # >5 seconds
                recommendations.append(
                    "Optimize RaptorQ shard decoding or increase parallelization"
                )
            elif recon_time < 1000:  # <1 second
                recommendations.append(
                    "Fast reconstruction achieved; suitable for real-time applications"
                )

        # Check availability
        if "node_availability" in aggregated["statistics"]:
            availability = aggregated["statistics"]["node_availability"]["mean"]
            if availability < 70:
                recommendations.append(
                    "Increase node redundancy or implement better churn handling"
                )
            elif availability > 90:
                recommendations.append(
                    "High availability achieved; ready for production deployment"
                )

        return recommendations

    def save_report(self, filepath: str = "TESTBED_REPORT.json") -> None:
        """Generate and save testbed report."""
        report = self.generate_testbed_report()

        # Add signature
        report_json = json.dumps(report, sort_keys=True)
        report["signature"] = hashlib.sha3_256(report_json.encode()).hexdigest()
        report["signature_algorithm"] = "SHA3-256"

        with open(filepath, "w") as f:
            json.dump(report, f, indent=2)

        print(f"✓ Testbed report saved to {filepath}")
        print(f"\n📊 OVERALL SUCCESS RATE: {report['overall_success_rate']:.0f}%")

        if report["success_achievements"]:
            print("\n✅ ACHIEVEMENTS:")
            for criterion, achievement in report["success_achievements"].items():
                status = "✓" if achievement["achieved"] else "✗"
                print(
                    f"  {status} {criterion}: {achievement['actual']:.1f} (target: {achievement['target']})"
                )

        if report["recommendations"]:
            print("\n💡 RECOMMENDATIONS:")
            for rec in report["recommendations"]:
                print(f"  • {rec}")


def main():
    """Demo: Create sample testbed metrics and generate report."""
    collector = MetricsCollector(testbed_id="pilot_region_001")

    # Initialize testbed config
    config = TestbedConfig(
        testbed_id="pilot_region_001",
        region="East Africa (Kenya)",
        node_count=50,
        deployment_date=datetime.utcnow().isoformat() + "Z",
        duration_days=30,
        target_metrics=[
            "bandwidth_savings",
            "reconstruction_time",
            "node_availability",
        ],
        success_criteria={
            "bandwidth_savings": 60.0,  # Target: 60% bandwidth savings
            "reconstruction_time": 3000.0,  # Target: <3s reconstruction
            "node_availability": 80.0,  # Target: 80% node availability
        },
    )
    collector.initialize_testbed(config)

    # Simulate recording some metrics
    print("\n📝 Recording sample metrics...")
    for i in range(20):
        collector.record_bandwidth_savings(
            original_size=1000,
            compressed_size=300 + (i * 10),
            node_id=f"node_{i}",
            region="East Africa (Kenya)",
        )

        collector.record_reconstruction_time(
            content_hash=f"hash_{i}",
            reconstruction_ms=1500 + (i * 100),
            node_id=f"node_{i}",
            region="East Africa (Kenya)",
            network_type="mesh",
        )

        collector.record_node_churn(
            active_nodes=45 - i,
            total_nodes=50,
            churn_rate=0.1,
            node_id=f"node_{i}",
            region="East Africa (Kenya)",
        )

    print("✓ Sample metrics recorded")

    # Generate report
    collector.save_report()

    print(
        "\n✅ Testbed metrics collection complete. Share report with NGOs and evaluators."
    )


if __name__ == "__main__":
    main()
