"""Tests for the development authenticator."""

from __future__ import annotations

import pytest

from server.transport.auth import AuthError, StaticTokenAuthenticator


def test_anonymous_allowed_when_no_token_configured() -> None:
    auth = StaticTokenAuthenticator(expected_token="", allow_anonymous=True)
    context = auth.authenticate(token=None, client_id="client-1")
    assert context.client_id == "client-1"
    assert context.subject == "client-1"


def test_anonymous_denied_when_disabled() -> None:
    auth = StaticTokenAuthenticator(expected_token="", allow_anonymous=False)
    with pytest.raises(AuthError):
        auth.authenticate(token=None, client_id="client-1")


def test_matching_token_accepted() -> None:
    auth = StaticTokenAuthenticator(expected_token="s3cret")
    context = auth.authenticate(token="s3cret", client_id="client-1")
    assert context.client_id == "client-1"


def test_wrong_or_missing_token_rejected() -> None:
    auth = StaticTokenAuthenticator(expected_token="s3cret")
    with pytest.raises(AuthError):
        auth.authenticate(token="nope", client_id="client-1")
    with pytest.raises(AuthError):
        auth.authenticate(token=None, client_id="client-1")


def test_missing_client_id_rejected() -> None:
    auth = StaticTokenAuthenticator(expected_token="")
    with pytest.raises(AuthError):
        auth.authenticate(token=None, client_id="")
