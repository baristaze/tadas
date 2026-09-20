"""A refused ticket is a close with 4401 on an open socket, never a
handshake failure: the socket is accepted first, then the ticket is
redeemed. An admitted socket lives as long as the credential behind its
ticket and no longer."""

import logging
from datetime import timedelta
from pathlib import Path

import pytest
from api_support import OWNER, build_container, run, seed_request
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tadas.om.base import utcnow
from tadas.om.tenancy.rules import hash_token
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer
from tadas.services.api.gateway.auth import CLOSE_UNAUTHENTICATED
from tadas.services.api.realtime.send_buffer import SendBuffer


def test_a_refused_ticket_closes_the_accepted_socket_with_4401(tmp_path: Path) -> None:
    with TestClient(create_app(build_container(tmp_path))) as tc:
        with tc.websocket_connect("/v1/realtime?ticket=wst_not_a_ticket") as ws:
            # The handshake succeeded; the refusal is the first thing received.
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == "not_authenticated"


def test_a_client_that_drops_mid_stream_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The drainer dies the way it does when the peer is gone; the teardown
    that follows is the normal end of a socket, not an unhandled exception."""
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
        )
    )

    async def dead_drain(self: SendBuffer, websocket: object) -> None:
        raise OSError("client gone")

    monkeypatch.setattr(SendBuffer, "drain", dead_drain)
    with TestClient(create_app(container)) as tc:
        login = tc.post(
            "/v1/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}
        )
        session = tc.post(
            "/v1/auth/sessions",
            json={"org_id": str(org.id)},
            headers={"Authorization": f"Bearer {login.json()['token']}"},
        )
        headers = {"Authorization": f"Bearer {session.json()['token']}"}
        ticket = tc.post("/v1/realtime/tickets", headers=headers).json()["ticket"]
        with caplog.at_level(logging.ERROR):
            with tc.websocket_connect(f"/v1/realtime?ticket={ticket}"):
                pass  # the client leaves at once
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


def session_token_expiring_in(container: AppContainer, seconds: float) -> str:
    """Signs the owner in and shortens the session behind the token in storage."""
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
        )
    )
    tenancy = container.managers.tenancy

    async def issue() -> str:
        login = await tenancy.login(seed_request(), OWNER["email"], OWNER["password"])
        identity = await tenancy.authenticate_login(seed_request(), login.token)
        return (await tenancy.exchange_login(identity, org.id)).token

    token = run(issue())
    storage = container.storage.get_tenancy_storage()
    found = run(storage.read_session_by_token_hash(hash_token(token)))
    assert found is not None
    org_id, session = found
    shortened = session.model_copy(update={"expires_at": utcnow() + timedelta(seconds=seconds)})
    run(storage.write_session(org_id, shortened))
    return token


def test_a_socket_is_closed_with_4401_when_the_session_behind_it_expires(tmp_path: Path) -> None:
    """The client does nothing; the server closes at the session's expiry."""
    container = build_container(tmp_path)
    token = session_token_expiring_in(container, 0.2)
    with TestClient(create_app(container)) as tc:
        headers = {"Authorization": f"Bearer {token}"}
        ticket = tc.post("/v1/realtime/tickets", headers=headers).json()["ticket"]
        with tc.websocket_connect(f"/v1/realtime?ticket={ticket}") as ws:
            assert ws.receive_json()["type"] == "hello"
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == "credential_expired"
