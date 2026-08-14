"""Authentication interface for the WebSocket gateway.

The gateway authenticates each connection through an :class:`Authenticator`.
A functional development implementation (:class:`StaticTokenAuthenticator`)
and a real production implementation (:class:`JwtAuthenticator`, verifying a
signed JWT's signature/issuer/audience/expiry against an asymmetric public
key) are both provided.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import jwt


@dataclass(frozen=True)
class AuthContext:
    """Result of a successful authentication."""

    client_id: str
    subject: str
    claims: dict[str, str] = field(default_factory=dict)


class AuthError(Exception):
    """Raised when authentication fails.

    The message is safe for logging but must not contain the raw token.
    """


class Authenticator(ABC):
    """Interface implemented by concrete authenticators.

    Implementations must be side-effect free with respect to the token value and
    must never log or echo the raw credential.
    """

    @abstractmethod
    def authenticate(self, *, token: str | None, client_id: str) -> AuthContext:
        """Validate ``token`` for ``client_id`` or raise :class:`AuthError`."""
        raise NotImplementedError


class StaticTokenAuthenticator(Authenticator):
    """Development authenticator using a shared static token.

    - When ``expected_token`` is empty and ``allow_anonymous`` is true, any
      client is accepted (development convenience only).
    - When ``expected_token`` is set, the presented token must match it exactly
      using a constant-time comparison.
    """

    def __init__(self, *, expected_token: str = "", allow_anonymous: bool = True) -> None:
        self._expected_token = expected_token
        self._allow_anonymous = allow_anonymous

    def authenticate(self, *, token: str | None, client_id: str) -> AuthContext:
        if not client_id:
            raise AuthError("client_id is required")

        if not self._expected_token:
            if self._allow_anonymous:
                return AuthContext(client_id=client_id, subject=client_id, claims={"dev": "true"})
            raise AuthError("authentication required")

        if token is None:
            raise AuthError("missing token")
        if not _constant_time_equals(token, self._expected_token):
            raise AuthError("invalid token")
        return AuthContext(client_id=client_id, subject=client_id, claims={"dev": "true"})


def _constant_time_equals(left: str, right: str) -> bool:
    """Constant-time string comparison to avoid leaking length/content timing."""
    import hmac

    return hmac.compare_digest(left, right)


class JwtAuthenticator(Authenticator):
    """Production authenticator validating signed JWTs.

    Verifies the token's signature against an asymmetric public key, plus
    issuer, audience and expiry (with configurable clock-skew leeway).
    Requires a non-empty ``sub`` claim, used as the auth subject. Never logs
    or echoes the raw token or key; failure messages name only the class of
    error (e.g. "expired", "invalid signature"), never token content.
    """

    def __init__(
        self,
        *,
        public_key: str,
        issuer: str,
        audience: str,
        algorithm: str = "RS256",
        leeway_seconds: int = 30,
    ) -> None:
        if not public_key:
            raise ValueError("public_key must be non-empty")
        if not issuer:
            raise ValueError("issuer must be non-empty")
        if not audience:
            raise ValueError("audience must be non-empty")
        if algorithm.upper().startswith("HS"):
            # A symmetric (HS*) algorithm's "public" key is actually the
            # shared signing secret -- accepting one here would mean anyone
            # who can read this (non-secret-handling) configuration could
            # forge tokens. Only asymmetric algorithms (RS*/ES*/PS*) are
            # appropriate for a verification-only authenticator.
            raise ValueError(
                f"symmetric algorithm {algorithm!r} is not supported for "
                "verification-only JWT auth; use an asymmetric algorithm "
                "(RS256, ES256, PS256, ...)"
            )
        self._public_key = public_key
        self._issuer = issuer
        self._audience = audience
        self._algorithm = algorithm
        self._leeway = leeway_seconds

    def authenticate(self, *, token: str | None, client_id: str) -> AuthContext:
        if not client_id:
            raise AuthError("client_id is required")
        if not token:
            raise AuthError("missing token")

        try:
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=[self._algorithm],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"token rejected: {type(exc).__name__}") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthError("token missing subject claim")

        # Only string-valued claims are carried into AuthContext.claims
        # (its declared type); numeric/structured claims (exp, iat, ...)
        # are already enforced above and are not needed by callers.
        string_claims = {k: v for k, v in claims.items() if isinstance(v, str)}
        return AuthContext(client_id=client_id, subject=subject, claims=string_claims)
