"""Tests for Prometheus metrics."""

from __future__ import annotations

from server.observability.metrics import (
    CONTENT_TYPE_LATEST,
    create_metrics,
    get_default_metrics,
    render_metrics,
    reset_default_metrics,
)


def test_create_metrics_instances_are_independent() -> None:
    a = create_metrics()
    b = create_metrics()
    a.sessions_active.set(3)
    b.sessions_active.set(7)

    text_a = render_metrics(a).decode("utf-8")
    text_b = render_metrics(b).decode("utf-8")
    assert "meeting_translator_sessions_active 3.0" in text_a
    assert "meeting_translator_sessions_active 7.0" in text_b


def test_counters_gauges_and_histograms_render() -> None:
    metrics = create_metrics()
    metrics.packets_received_total.labels(source="microphone").inc()
    metrics.packets_received_total.labels(source="microphone").inc()
    metrics.packets_lost_total.labels(source="loopback").inc(3)
    metrics.translation_requests_total.labels(priority="final", status="completed").inc()
    metrics.translation_latency_seconds.labels(priority="final").observe(0.42)
    metrics.translation_queue_depth.labels(priority="completeness").set(2)
    metrics.circuit_breaker_state.labels(backend="translation").set(0)

    text = render_metrics(metrics).decode("utf-8")
    assert 'meeting_translator_packets_received_total{source="microphone"} 2.0' in text
    assert 'meeting_translator_packets_lost_total{source="loopback"} 3.0' in text
    assert (
        'meeting_translator_translation_requests_total{priority="final",status="completed"} 1.0'
        in text
    )
    assert "meeting_translator_translation_latency_seconds_sum" in text
    assert 'meeting_translator_translation_queue_depth{priority="completeness"} 2.0' in text
    assert 'meeting_translator_circuit_breaker_state{backend="translation"} 0.0' in text


def test_get_default_metrics_is_a_singleton() -> None:
    reset_default_metrics()
    try:
        a = get_default_metrics()
        b = get_default_metrics()
        assert a is b
    finally:
        reset_default_metrics()


def test_render_metrics_defaults_to_the_default_instance() -> None:
    reset_default_metrics()
    try:
        get_default_metrics().sessions_active.set(5)
        text = render_metrics().decode("utf-8")
        assert "meeting_translator_sessions_active 5.0" in text
    finally:
        reset_default_metrics()


def test_content_type_is_prometheus_text_format() -> None:
    assert "text/plain" in CONTENT_TYPE_LATEST
