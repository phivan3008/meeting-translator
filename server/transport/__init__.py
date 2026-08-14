"""Server-side WebSocket transport: gateway, sessions and supporting logic.

The submodules separate pure, framework-independent logic (authentication
interface, rate limiting, jitter/reorder buffering, acknowledgement batching and
session management) from the FastAPI WebSocket adapter in :mod:`gateway`.
"""

from __future__ import annotations

from server.transport.acks import AckBatcher
from server.transport.auth import (
    AuthContext,
    Authenticator,
    AuthError,
    StaticTokenAuthenticator,
)
from server.transport.jitter_buffer import JitterBuffer, OfferResult, ReleasedFrame
from server.transport.limits import TokenBucket
from server.transport.session import Session, SessionManager, StreamContext

__all__ = [
    "AckBatcher",
    "AuthContext",
    "AuthError",
    "Authenticator",
    "JitterBuffer",
    "OfferResult",
    "ReleasedFrame",
    "Session",
    "SessionManager",
    "StaticTokenAuthenticator",
    "StreamContext",
    "TokenBucket",
]
