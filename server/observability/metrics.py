"""Prometheus metrics for the application server.

One counter/histogram/gauge per processing stage, per
docs/PRODUCT_REQUIREMENTS.md ("Metrics for every processing stage") and
docs/ACCEPTANCE_CRITERIA.md ("Metrics expose stage latency and queue
depth"). Metric label values are always small, bounded-cardinality tags
(stream source, priority, status, backend name) -- never audio, transcript,
prompt or translation content -- consistent with this project's
logging-privacy rules.

Call sites use the standard ``prometheus_client`` API directly on the
fields of a :class:`Metrics` instance (e.g.
``metrics.packets_received_total.labels(source="microphone").inc()``)
rather than a bespoke wrapper, since that API is already minimal and
well-known.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

__all__ = [
    "CONTENT_TYPE_LATEST",
    "Metrics",
    "create_metrics",
    "get_default_metrics",
    "render_metrics",
    "reset_default_metrics",
]


@dataclass
class Metrics:
    """One process's full metrics set, bound to its own registry.

    A fresh instance (via :func:`create_metrics`) is fully isolated: tests
    can create as many as they like without clashing with each other or
    with the process-wide default instance. ``prometheus_client``'s default
    global registry raises on duplicate metric names, which would otherwise
    make per-test isolation impossible.
    """

    registry: CollectorRegistry
    sessions_active: Gauge
    packets_received_total: Counter
    packets_lost_total: Counter
    packets_duplicate_total: Counter
    translation_requests_total: Counter
    translation_latency_seconds: Histogram
    asr_latency_seconds: Histogram
    translation_queue_depth: Gauge
    circuit_breaker_state: Gauge


def create_metrics(registry: CollectorRegistry | None = None) -> Metrics:
    """Create a new, independent :class:`Metrics` instance."""
    reg = registry if registry is not None else CollectorRegistry()
    return Metrics(
        registry=reg,
        sessions_active=Gauge(
            "meeting_translator_sessions_active",
            "Number of currently active WebSocket sessions.",
            registry=reg,
        ),
        packets_received_total=Counter(
            "meeting_translator_packets_received_total",
            "Total audio packets received, per stream source.",
            ["source"],
            registry=reg,
        ),
        packets_lost_total=Counter(
            "meeting_translator_packets_lost_total",
            "Total audio packets reported lost by the jitter buffer "
            "(forced advance past a gap), per stream source.",
            ["source"],
            registry=reg,
        ),
        packets_duplicate_total=Counter(
            "meeting_translator_packets_duplicate_total",
            "Total duplicate/stale audio packets ignored, per stream source.",
            ["source"],
            registry=reg,
        ),
        translation_requests_total=Counter(
            "meeting_translator_translation_requests_total",
            "Total translation requests, per priority and outcome status.",
            ["priority", "status"],
            registry=reg,
        ),
        translation_latency_seconds=Histogram(
            "meeting_translator_translation_latency_seconds",
            "Translation backend request latency in seconds, per priority.",
            ["priority"],
            registry=reg,
        ),
        asr_latency_seconds=Histogram(
            "meeting_translator_asr_latency_seconds",
            "ASR decode latency in seconds, per stage (partial/final).",
            ["stage"],
            registry=reg,
        ),
        translation_queue_depth=Gauge(
            "meeting_translator_translation_queue_depth",
            "Current translation queue depth, per priority.",
            ["priority"],
            registry=reg,
        ),
        circuit_breaker_state=Gauge(
            "meeting_translator_circuit_breaker_state",
            "Circuit breaker state per backend (0=closed, 1=half_open, 2=open).",
            ["backend"],
            registry=reg,
        ),
    )


_default_metrics: Metrics | None = None


def get_default_metrics() -> Metrics:
    """Return the process-wide default :class:`Metrics` instance (created once)."""
    global _default_metrics
    if _default_metrics is None:
        _default_metrics = create_metrics()
    return _default_metrics


def reset_default_metrics() -> None:
    """Discard the process-wide default instance (test isolation only)."""
    global _default_metrics
    _default_metrics = None


def render_metrics(metrics: Metrics | None = None) -> bytes:
    """Render metrics in the Prometheus text exposition format."""
    target = metrics if metrics is not None else get_default_metrics()
    return generate_latest(target.registry)
