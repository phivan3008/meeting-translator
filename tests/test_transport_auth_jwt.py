"""Tests for the production JWT authenticator.

Uses a real, locally-generated RSA keypair (via ``cryptography``, pulled in
by the ``PyJWT[crypto]`` extra) to sign and verify real tokens end-to-end --
no network access, no external service, fully offline and deterministic.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from server.transport.auth import AuthError, JwtAuthenticator

ISSUER = "meeting-translator"
AUDIENCE = "meeting-translator-client"


@pytest.fixture(scope="module")
def keypair() -> tuple[str, str]:
    """Generate a real RSA keypair once; return (private_pem, public_pem)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


@pytest.fixture(scope="module")
def other_keypair() -> tuple[str, str]:
    """A second, unrelated keypair (for signature-mismatch tests)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


def _make_token(
    private_pem: str,
    *,
    sub: str = "user-1",
    iss: str = ISSUER,
    aud: str = AUDIENCE,
    exp_offset_s: float = 300.0,
    algorithm: str = "RS256",
    extra_claims: dict[str, object] | None = None,
) -> str:
    now = time.time()
    claims: dict[str, object] = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + exp_offset_s,
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, private_pem, algorithm=algorithm)


def _authenticator(public_pem: str, **overrides: object) -> JwtAuthenticator:
    kwargs: dict[str, object] = {
        "public_key": public_pem,
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "algorithm": "RS256",
        "leeway_seconds": 5,
    }
    kwargs.update(overrides)
    return JwtAuthenticator(**kwargs)  # type: ignore[arg-type]


def test_valid_token_accepted(keypair: tuple[str, str]) -> None:
    private_pem, public_pem = keypair
    token = _make_token(private_pem, sub="user-42", extra_claims={"role": "meeting-host"})
    auth = _authenticator(public_pem)

    context = auth.authenticate(token=token, client_id="client-1")

    assert context.client_id == "client-1"
    assert context.subject == "user-42"
    assert context.claims["role"] == "meeting-host"


def test_expired_token_rejected(keypair: tuple[str, str]) -> None:
    private_pem, public_pem = keypair
    token = _make_token(private_pem, exp_offset_s=-3600.0)
    auth = _authenticator(public_pem)

    with pytest.raises(AuthError):
        auth.authenticate(token=token, client_id="client-1")


def test_leeway_tolerates_small_clock_skew(keypair: tuple[str, str]) -> None:
    private_pem, public_pem = keypair
    # Expired 2s ago; leeway is 5s, so this must still be accepted.
    token = _make_token(private_pem, exp_offset_s=-2.0)
    auth = _authenticator(public_pem, leeway_seconds=5)

    context = auth.authenticate(token=token, client_id="client-1")
    assert context.subject == "user-1"


def test_wrong_issuer_rejected(keypair: tuple[str, str]) -> None:
    private_pem, public_pem = keypair
    token = _make_token(private_pem, iss="someone-else")
    auth = _authenticator(public_pem)

    with pytest.raises(AuthError):
        auth.authenticate(token=token, client_id="client-1")


def test_wrong_audience_rejected(keypair: tuple[str, str]) -> None:
    private_pem, public_pem = keypair
    token = _make_token(private_pem, aud="someone-elses-app")
    auth = _authenticator(public_pem)

    with pytest.raises(AuthError):
        auth.authenticate(token=token, client_id="client-1")


def test_wrong_signature_rejected(keypair: tuple[str, str], other_keypair: tuple[str, str]) -> None:
    # Signed with a *different* private key than the authenticator trusts.
    wrong_private_pem, _ = other_keypair
    _, trusted_public_pem = keypair
    token = _make_token(wrong_private_pem)
    auth = _authenticator(trusted_public_pem)

    with pytest.raises(AuthError):
        auth.authenticate(token=token, client_id="client-1")


def test_missing_subject_claim_rejected(keypair: tuple[str, str]) -> None:
    private_pem, public_pem = keypair
    now = time.time()
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300},
        private_pem,
        algorithm="RS256",
    )
    auth = _authenticator(public_pem)

    with pytest.raises(AuthError):
        auth.authenticate(token=token, client_id="client-1")


def test_missing_token_rejected(keypair: tuple[str, str]) -> None:
    _, public_pem = keypair
    auth = _authenticator(public_pem)
    with pytest.raises(AuthError):
        auth.authenticate(token=None, client_id="client-1")
    with pytest.raises(AuthError):
        auth.authenticate(token="", client_id="client-1")


def test_missing_client_id_rejected(keypair: tuple[str, str]) -> None:
    private_pem, public_pem = keypair
    token = _make_token(private_pem)
    auth = _authenticator(public_pem)
    with pytest.raises(AuthError):
        auth.authenticate(token=token, client_id="")


def test_none_algorithm_token_rejected(keypair: tuple[str, str]) -> None:
    # A classic JWT attack: a token signed with alg "none" (no signature at
    # all). Restricting `algorithms=[...]` in jwt.decode must reject this.
    _, public_pem = keypair
    now = time.time()
    unsigned = jwt.api_jwt.encode(
        {"sub": "user-1", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300},
        key=None,  # type: ignore[arg-type]
        algorithm="none",
    )
    auth = _authenticator(public_pem)

    with pytest.raises(AuthError):
        auth.authenticate(token=unsigned, client_id="client-1")


def test_symmetric_algorithm_rejected_at_construction(keypair: tuple[str, str]) -> None:
    _, public_pem = keypair
    with pytest.raises(ValueError):
        _authenticator(public_pem, algorithm="HS256")


def test_empty_config_rejected_at_construction() -> None:
    with pytest.raises(ValueError):
        JwtAuthenticator(public_key="", issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(ValueError):
        JwtAuthenticator(public_key="x", issuer="", audience=AUDIENCE)
    with pytest.raises(ValueError):
        JwtAuthenticator(public_key="x", issuer=ISSUER, audience="")


def test_error_message_never_contains_raw_token(keypair: tuple[str, str]) -> None:
    private_pem, public_pem = keypair
    token = _make_token(private_pem, exp_offset_s=-3600.0)
    auth = _authenticator(public_pem)

    with pytest.raises(AuthError) as excinfo:
        auth.authenticate(token=token, client_id="client-1")
    assert token not in str(excinfo.value)
