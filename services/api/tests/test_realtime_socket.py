"""A refused ticket is a close with 4401 on an open socket, never a
handshake failure: the socket is accepted first, then the ticket is
redeemed."""

from pathlib import Path

import pytest
from api_support import build_container
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tadas.services.api.app import create_app
from tadas.services.api.gateway.auth import CLOSE_UNAUTHENTICATED


def test_a_refused_ticket_closes_the_accepted_socket_with_4401(tmp_path: Path) -> None:
    with TestClient(create_app(build_container(tmp_path))) as tc:
        with tc.websocket_connect("/v1/realtime?ticket=wst_not_a_ticket") as ws:
            # The handshake succeeded; the refusal is the first thing received.
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == "not_authenticated"
