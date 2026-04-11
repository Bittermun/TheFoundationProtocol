"""
TFP v3.2: Prometheus Metrics Exporter

Integrates with Prometheus client to expose real-time metrics:
- Bandwidth savings ratio
- Reconstruction latency
- Node availability
- Cache hit rates

Usage:
    exporter = MetricsExporter()
    exporter.record_bandwidth_savings(1000, 400)
    exporter.start_server()  # Exposes /metrics on port 9090
"""

import logging
import threading
from typing import Optional

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

logger = logging.getLogger(__name__)


class MetricsExporter:
    """Prometheus metrics exporter for TFP protocol"""

    def __init__(self, port: int = 9090, registry: Optional[CollectorRegistry] = None):
        """
        Initialize metrics exporter.

        Args:
            port: Port to expose /metrics endpoint (default: 9090)
            registry: Prometheus CollectorRegistry (default: global registry)
        """
        self.port = port
        self.registry = registry if registry else CollectorRegistry()
        self._server_started = False

        # Define metrics
        self.bandwidth_savings_ratio = Gauge(
            "tfp_bandwidth_savings_ratio",
            "Ratio of bandwidth saved via compression/caching (0.0-1.0)",
            registry=self.registry,
        )

        self.reconstruction_latency = Histogram(
            "tfp_reconstruction_latency_seconds",
            "Time to reconstruct content from shards",
            buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry,
        )

        self.node_availability = Counter(
            "tfp_node_availability_total",
            "Total count of node availability checks",
            ["status"],  # labels: available, unavailable
            registry=self.registry,
        )

        self.cache_hits = Counter(
            "tfp_cache_hits_total", "Total cache hit events", registry=self.registry
        )

        self.cache_misses = Counter(
            "tfp_cache_misses_total", "Total cache miss events", registry=self.registry
        )

        self.active_connections = Gauge(
            "tfp_active_connections",
            "Current number of active peer connections",
            registry=self.registry,
        )

    def record_bandwidth_savings(
        self, original_size: int, compressed_size: int
    ) -> None:
        """
        Record bandwidth savings from compression/caching.

        Args:
            original_size: Original content size in bytes
            compressed_size: Size after compression/caching
        """
        if original_size <= 0:
            logger.warning("Original size must be positive")
            return

        savings_ratio = (original_size - compressed_size) / original_size
        savings_ratio = max(0.0, min(1.0, savings_ratio))  # Clamp to [0, 1]
        self.bandwidth_savings_ratio.set(savings_ratio)
        logger.debug(f"Recorded bandwidth savings: {savings_ratio:.2%}")

    def record_reconstruction_time(self, duration_ms: float) -> None:
        """
        Record content reconstruction latency.

        Args:
            duration_ms: Reconstruction time in milliseconds
        """
        duration_seconds = duration_ms / 1000.0
        self.reconstruction_latency.observe(duration_seconds)
        logger.debug(f"Recorded reconstruction time: {duration_seconds:.3f}s")

    def record_node_availability(self, available: bool) -> None:
        """
        Record node availability status.

        Args:
            available: True if node is available, False otherwise
        """
        status = "available" if available else "unavailable"
        self.node_availability.labels(status=status).inc()
        logger.debug(f"Recorded node availability: {status}")

    def record_cache_hit(self) -> None:
        """Record a cache hit event."""
        self.cache_hits.inc()

    def record_cache_miss(self) -> None:
        """Record a cache miss event."""
        self.cache_misses.inc()

    def set_active_connections(self, count: int) -> None:
        """
        Set the current number of active peer connections.

        Args:
            count: Number of active connections
        """
        self.active_connections.set(count)

    def get_metrics(self) -> dict:
        """
        Get current metric values as a dictionary.

        Returns:
            Dictionary of metric names to values
        """
        # Note: This is a simplified representation
        # In production, you'd collect from the registry properly
        return {
            "tfp_bandwidth_savings_ratio": self.bandwidth_savings_ratio._value.get(),
            "tfp_reconstruction_latency_seconds": self.reconstruction_latency._sum.get(),
            "tfp_node_availability_total": (
                self.node_availability.labels(status="available")._value.get()
                + self.node_availability.labels(status="unavailable")._value.get()
            ),
            "tfp_cache_hits_total": self.cache_hits._value.get(),
            "tfp_cache_misses_total": self.cache_misses._value.get(),
        }

    def get_prometheus_format(self) -> str:
        """
        Get metrics in Prometheus text exposition format.

        Returns:
            String in Prometheus format
        """
        return generate_latest(self.registry).decode("utf-8")

    def start_server(self, blocking: bool = False) -> None:
        """
        Start HTTP server to expose /metrics endpoint.

        Args:
            blocking: If True, block until server stops. If False, run in background thread.
        """
        if self._server_started:
            logger.warning("Metrics server already started")
            return

        logger.info(f"Starting Prometheus metrics server on port {self.port}")

        if blocking:
            start_http_server(self.port, registry=self.registry)
        else:
            thread = threading.Thread(
                target=start_http_server,
                args=(self.port,),
                kwargs={"registry": self.registry},
                daemon=True,
            )
            thread.start()

        self._server_started = True
        logger.info(f"Metrics available at http://localhost:{self.port}/metrics")

    def stop_server(self) -> None:
        """Stop the metrics HTTP server."""
        # Note: prometheus_client doesn't provide a clean stop method
        # In production, you'd manage this differently
        self._server_started = False
        logger.info("Metrics server stopped")
