# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
OpenTelemetry Tracing Integration for TFP.

Provides distributed tracing for multi-node debugging, HABP consensus analysis,
shard delivery tracking, and end-to-end request flow visibility.

Architecture:
- Auto-instrumentation: FastAPI, SQLAlchemy, Redis, HTTPX
- Manual spans: HABP consensus, task dispatch, shard verification
- Exporter: OTLP HTTP to OTEL Collector
- Backend: Jaeger, Tempo, or any OTLP-compatible tracer

Usage:
    from tfp_client.lib.otel_tracing import setup_otel_tracing

    # In main app initialization
    app = FastAPI()
    setup_otel_tracing(app, service_name="tfp-daemon")

    # Manual spans for custom logic
    from opentelemetry import trace
    tracer = trace.get_tracer("tfp")

    with tracer.start_as_current_span("habp_consensus"):
        # Consensus logic here
        pass
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def setup_otel_tracing(
    app=None,
    service_name: str = "tfp-daemon",
    service_version: str = "3.1.1",
    otlp_endpoint: Optional[str] = None,
    sample_rate: float = 1.0,
    enable_auto_instrumentation: bool = True,
):
    """
    Set up OpenTelemetry tracing for TFP daemon.

    Args:
        app: FastAPI application (optional, for auto-instrumentation)
        service_name: Service name for traces
        service_version: Service version
        otlp_endpoint: OTLP exporter endpoint (default: http://localhost:4318/v1/traces)
        sample_rate: Sampling rate (0.0-1.0), 1.0 = sample all traces
        enable_auto_instrumentation: Enable auto-instrumentation for common libs

    Returns:
        TracerProvider instance
    """
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Determine endpoint
    otlp_endpoint = otlp_endpoint or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
    )

    # Create resource with service metadata
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment": os.getenv("TFP_ENVIRONMENT", "development"),
        }
    )

    # Create tracer provider
    tracer_provider = TracerProvider(resource=resource)

    # Configure sampler
    from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio

    sampler = ParentBasedTraceIdRatio(sample_rate)
    tracer_provider.sampler = sampler

    # Set up OTLP exporter
    try:
        exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
        span_processor = BatchSpanProcessor(exporter)
        tracer_provider.add_span_processor(span_processor)
        logger.info(f"OTLP tracing enabled -> {otlp_endpoint}")
    except Exception as e:
        logger.warning(f"Failed to set up OTLP exporter: {e}. Tracing disabled.")
        return tracer_provider

    # Set global tracer provider
    trace.set_tracer_provider(tracer_provider)

    # Auto-instrument common libraries
    if enable_auto_instrumentation and app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(
                app,
                excluded_urls="/health,/metrics,/api/dev/rag/stats",
            )
            logger.info("FastAPI auto-instrumentation enabled")
        except ImportError:
            logger.warning("opentelemetry-instrumentation-fastapi not installed")

        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument()
            logger.info("SQLAlchemy auto-instrumentation enabled")
        except ImportError:
            pass

        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor

            RedisInstrumentor().instrument()
            logger.info("Redis auto-instrumentation enabled")
        except ImportError:
            pass

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
            logger.info("HTTPX auto-instrumentation enabled")
        except ImportError:
            pass

    return tracer_provider


def instrument_habp_consensus(func):
    """
    Decorator to add tracing to HABP consensus functions.

    Usage:
        @instrument_habp_consensus
        def run_consensus_round(...):
            ...
    """
    from functools import wraps

    from opentelemetry import trace

    tracer = trace.get_tracer("tfp.habp")

    @wraps(func)
    def wrapper(*args, **kwargs):
        with tracer.start_as_current_span(
            f"{func.__name__}",
            attributes={
                "tfp.component": "habp_consensus",
                "tfp.function": func.__name__,
            },
        ) as span:
            # Add function arguments as span attributes (careful with sensitive data)
            if "round_id" in kwargs:
                span.set_attribute("tfp.round_id", str(kwargs["round_id"]))
            if len(args) > 0 and hasattr(args[0], "__dict__"):
                # First arg is likely self, skip
                pass

            try:
                result = func(*args, **kwargs)
                span.set_attribute("tfp.status", "success")
                return result
            except Exception as e:
                span.set_attribute("tfp.status", "error")
                span.record_exception(e)
                raise

    return wrapper


def instrument_shard_verification(func):
    """
    Decorator to add tracing to shard verification functions.

    Usage:
        @instrument_shard_verification
        def verify_shard(...):
            ...
    """
    from functools import wraps

    from opentelemetry import trace

    tracer = trace.get_tracer("tfp.shards")

    @wraps(func)
    def wrapper(*args, **kwargs):
        with tracer.start_as_current_span(
            f"{func.__name__}",
            attributes={
                "tfp.component": "shard_verification",
                "tfp.function": func.__name__,
            },
        ) as span:
            # Add shard metadata if available
            if "shard_id" in kwargs:
                span.set_attribute("tfp.shard_id", str(kwargs["shard_id"]))
            if "task_id" in kwargs:
                span.set_attribute("tfp.task_id", str(kwargs["task_id"]))

            try:
                result = func(*args, **kwargs)
                span.set_attribute("tfp.status", "success")
                return result
            except Exception as e:
                span.set_attribute("tfp.status", "error")
                span.record_exception(e)
                raise

    return wrapper


def get_current_trace_context():
    """
    Get current trace context for manual propagation.

    Returns:
        Tuple of (trace_id, span_id) as hex strings
    """
    from opentelemetry import trace

    current_span = trace.get_current_span()
    if current_span.get_span_context().is_valid:
        ctx = current_span.get_span_context()
        return (
            format(ctx.trace_id, "032x"),
            format(ctx.span_id, "016x"),
        )
    return (None, None)


def create_span_from_context(trace_id: str, span_id: str):
    """
    Create a span context from propagated trace IDs.

    Useful for continuing traces across service boundaries.

    Args:
        trace_id: 32-char hex trace ID
        span_id: 16-char hex parent span ID

    Returns:
        SpanContext object
    """
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

    ctx = SpanContext(
        trace_id=int(trace_id, 16),
        span_id=int(span_id, 16),
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return NonRecordingSpan(ctx)


# Context manager for custom spans
class CustomSpan:
    """
    Context manager for creating custom spans with metadata.

    Usage:
        with CustomSpan("my_operation", {"key": "value"}):
            # Operation here
            pass
    """

    def __init__(self, name: str, attributes: Optional[dict] = None):
        self.name = name
        self.attributes = attributes or {}
        self._span = None

    def __enter__(self):
        from opentelemetry import trace

        tracer = trace.get_tracer("tfp.custom")
        self._span = tracer.start_span(self.name, attributes=self.attributes)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            self._span.record_exception(exc_val)
            self._span.set_attribute("tfp.status", "error")
        else:
            self._span.set_attribute("tfp.status", "success")
        self._span.end()


# Prometheus metrics integration for tracing
def add_tracing_metrics():
    """
    Add tracing-related Prometheus metrics.

    Metrics:
    - otel_spans_total: Total number of spans created
    - otel_span_duration_seconds: Span duration histogram
    """
    from prometheus_client import Counter, Histogram

    spans_total = Counter(
        "otel_spans_total",
        "Total number of OpenTelemetry spans created",
        ["component", "status"],
    )

    span_duration = Histogram(
        "otel_span_duration_seconds",
        "OpenTelemetry span duration in seconds",
        ["component"],
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    )

    return spans_total, span_duration
