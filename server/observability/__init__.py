"""Observability primitives: structured correlation IDs and Prometheus metrics.

Framework-independent where practical (`correlation.py` uses only the
standard library's `contextvars`/`logging`; `metrics.py` uses the
`prometheus_client` library, already a `server` dependency) so both are
unit-testable without a running FastAPI app.
"""

from __future__ import annotations

from server.observability.correlation import (
    CorrelationFilter,
    bind,
    current,
    new_request_id,
)
from server.observability.metrics import (
    CONTENT_TYPE_LATEST,
    Metrics,
    create_metrics,
    get_default_metrics,
    render_metrics,
    reset_default_metrics,
)

__all__ = [
    "CONTENT_TYPE_LATEST",
    "CorrelationFilter",
    "Metrics",
    "bind",
    "create_metrics",
    "current",
    "get_default_metrics",
    "new_request_id",
    "render_metrics",
    "reset_default_metrics",
]
