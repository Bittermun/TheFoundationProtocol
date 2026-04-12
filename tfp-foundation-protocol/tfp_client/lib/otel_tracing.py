"""
OpenTelemetry tracing and metrics for TFP.
Extends existing Prometheus metrics with distributed tracing.
"""
import os
from typing import Optional
from contextlib import contextmanager

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

def setup_otel_tracing(
    service_name: str = "tfp-node",
    enable_tracing: bool = False,
    prometheus_port: int = 8000
) -> tuple[Optional[trace.Tracer], Optional[metrics.Meter]]:
    """
    Initialize OpenTelemetry tracing and metrics.
    
    Args:
        service_name: Service name for telemetry
        enable_tracing: If True, enable span export (False = metrics only)
        prometheus_port: Port for Prometheus scraper
    
    Returns:
        Tuple of (tracer, meter) - either may be None if not configured
    """
    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": os.environ.get("TFP_ENV", "development"),
    })
    
    # Setup metrics with Prometheus exporter
    reader = PrometheusMetricReader()
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[reader]
    )
    metrics.set_meter_provider(meter_provider)
    meter = metrics.get_meter(__name__)
    
    # Create key metrics
    credits_minted_counter = meter.create_counter(
        "tfp_credits_minted",
        description="Total credits minted via HABP consensus"
    )
    credits_spent_counter = meter.create_counter(
        "tfp_credits_spent",
        description="Total credits spent on content retrieval"
    )
    habp_consensus_counter = meter.create_counter(
        "tfp_habp_consensus_total",
        description="HABP consensus events (success/failure)"
    )
    task_execution_histogram = meter.create_histogram(
        "tfp_task_execution_time",
        description="Task execution time in seconds",
        unit="s"
    )
    
    # Setup tracing if enabled
    tracer = None
    if enable_tracing:
        trace_provider = TracerProvider(resource=resource)
        trace_provider.add_span_processor(
            SimpleSpanProcessor(ConsoleSpanExporter())
        )
        trace.set_tracer_provider(trace_provider)
        tracer = trace.get_tracer(__name__)
    
    return tracer, meter

@contextmanager
def otel_span(tracer: Optional[trace.Tracer], name: str, **attributes):
    """Context manager for creating spans. No-op if tracer is None."""
    if tracer is None:
        yield None
        return
    
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        yield span

# Convenience functions for common TFP operations
def record_credit_mint(meter: metrics.Meter, amount: int, device_id: str):
    """Record credit minting event."""
    counter = meter.get_instrument("tfp_credits_minted")
    if counter:
        counter.add(amount, {"device_id": device_id})

def record_credit_spend(meter: metrics.Meter, amount: int, device_id: str):
    """Record credit spending event."""
    counter = meter.get_instrument("tfp_credits_spent")
    if counter:
        counter.add(amount, {"device_id": device_id})

def record_habp_consensus(meter: metrics.Meter, success: bool, nodes_count: int):
    """Record HABP consensus result."""
    counter = meter.get_instrument("tfp_habp_consensus_total")
    if counter:
        counter.add(1, {"success": str(success), "nodes_count": nodes_count})

def record_task_execution(meter: metrics.Meter, duration: float, task_type: str):
    """Record task execution time."""
    histogram = meter.get_instrument("tfp_task_execution_time")
    if histogram:
        histogram.record(duration, {"task_type": task_type})
