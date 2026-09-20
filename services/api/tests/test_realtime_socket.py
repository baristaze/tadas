"""A refused ticket is a close with 4401 on an open socket, never a
handshake failure: the socket is accepted first, then the ticket is
redeemed."""

import logging
from pathlib import Path

import pytest
from api_support import OWNER, build_container, run, seed_request
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tadas.services.api.app import create_app
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
