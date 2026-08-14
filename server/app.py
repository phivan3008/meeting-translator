"""FastAPI application with liveness/readiness endpoints, metrics and
graceful shutdown.

Liveness indicates the process is running. Readiness indicates the service
is prepared to accept work -- it reflects settings, whether a graceful
shutdown has begun, and (opt-in) a best-effort translation-backend
reachability probe, without ever dumping raw error/exception details.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Response, status

from server.observability.correlation import CorrelationFilter
from server.observability.metrics import (
    CONTENT_TYPE_LATEST,
    Metrics,
    create_metrics,
    render_metrics,
)
from server.reliability.shutdown import ShutdownCoordinator
from server.transport.auth import Authenticator, JwtAuthenticator, StaticTokenAuthenticator
from server.transport.gateway import create_gateway_router
from server.transport.session import SessionManager
from shared.logging import configure_logging
from shared.settings import Settings, get_settings
from shared.version import __version__

_LOG = logging.getLogger("server.app")


def _build_authenticator(settings: Settings) -> Authenticator:
    """Choose the production JWT authenticator when a public key is
    configured, else the development static-token authenticator.

    Fails fast (at app construction, not on first request) if
    ``jwt_public_key_path`` is set but unreadable -- a misconfigured
    deployment should refuse to start rather than silently accept no auth.
    """
    if settings.jwt_public_key_path:
        try:
            public_key = Path(settings.jwt_public_key_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(
                f"jwt_public_key_path is set but could not be read: {settings.jwt_public_key_path}"
            ) from exc
        return JwtAuthenticator(
            public_key=public_key,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            algorithm=settings.jwt_algorithm,
            leeway_seconds=settings.jwt_leeway_seconds,
        )
    return StaticTokenAuthenticator(
        expected_token=settings.auth_dev_token,
        allow_anonymous=not settings.is_production,
    )


async def _check_translation_backend(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> bool:
    """Best-effort reachability probe against the translation backend.

    Never raises and never surfaces the exception/response detail to the
    caller -- only a boolean -- so a network error, DNS failure or non-200
    response cannot leak internal addresses or error text into
    ``/health/ready``'s response body.
    """
    timeout_s = settings.readiness_check_timeout_ms / 1000.0
    url = f"{settings.vllm_base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as client:
            response = await client.get(url)
        return response.status_code == 200
    except Exception:  # noqa: BLE001 - readiness must never raise
        return False


def create_app(
    settings: Settings | None = None,
    *,
    metrics: Metrics | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    root_logger = logging.getLogger()
    if not any(isinstance(f, CorrelationFilter) for f in root_logger.filters):
        root_logger.addFilter(CorrelationFilter())

    resolved_metrics = metrics if metrics is not None else create_metrics()
    shutdown = ShutdownCoordinator()

    authenticator = _build_authenticator(resolved)
    session_manager = SessionManager(
        max_streams_per_session=resolved.ws_max_streams_per_session,
        jitter_capacity=resolved.ws_jitter_buffer_capacity,
        ack_every_packets=resolved.ws_ack_every_packets,
        ack_every_ms=resolved.ws_ack_every_ms,
        max_sessions=resolved.ws_max_sessions,
    )
    shutdown.set_active_count_source(lambda: session_manager.active_count)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Graceful shutdown: flip readiness to not-ready immediately (done
        # via begin_shutdown(), read by the /health/ready route below),
        # then wait, bounded by shutdown_drain_timeout_ms, for in-flight
        # sessions to finish/disconnect on their own before the process
        # actually exits.
        shutdown.begin_shutdown()
        deadline_s = resolved.shutdown_drain_timeout_ms / 1000.0
        poll_s = 0.1
        elapsed_s = 0.0
        while not shutdown.drained() and elapsed_s < deadline_s:
            await asyncio.sleep(poll_s)
            elapsed_s += poll_s
        if not shutdown.drained():
            _LOG.warning(
                "shutdown drain timed out with %d session(s) still active",
                shutdown.active_count(),
            )

    app = FastAPI(title="Meeting Translator Server", version=__version__, lifespan=lifespan)
    app.state.settings = resolved
    app.state.metrics = resolved_metrics
    app.state.shutdown = shutdown
    app.state.session_manager = session_manager

    app.include_router(
        create_gateway_router(
            settings=resolved,
            authenticator=authenticator,
            session_manager=session_manager,
            metrics=resolved_metrics,
            shutdown=shutdown,
        )
    )

    @app.get("/health/live")
    def live() -> dict[str, Any]:
        """Liveness probe: the process is up."""
        return {"status": "alive", "app_env": resolved.app_env}

    @app.get("/health/ready")
    async def ready(response: Response) -> dict[str, Any]:
        """Readiness probe.

        Reflects settings having loaded, whether a graceful shutdown has
        begun (a load balancer should stop routing new connections the
        instant shutdown starts), and -- only when
        ``readiness_check_translation_backend`` is enabled -- a bounded,
        best-effort reachability check against the translation backend.
        Never includes raw error details, hostnames or tokens; only
        per-check booleans.
        """
        checks: dict[str, bool] = {
            "settings": resolved is not None,
            "not_shutting_down": not shutdown.is_shutting_down,
        }
        if resolved.readiness_check_translation_backend:
            checks["translation_backend"] = await _check_translation_backend(resolved)
        is_ready = all(checks.values())
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ready" if is_ready else "not_ready", "checks": checks}

    @app.get("/metrics")
    def metrics_endpoint() -> Response:
        """Prometheus text-format metrics (docs/PRODUCT_REQUIREMENTS.md:
        "Metrics for every processing stage")."""
        return Response(content=render_metrics(resolved_metrics), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
