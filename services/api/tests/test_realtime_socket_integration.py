"""The close code on the wire, as a real client sees it: a websockets client
against a uvicorn instance serving the app, not the test client, because
only the server decides what a close before the accept becomes."""

import asyncio
import logging
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
import websockets
from api_support import OWNER, build_container, seed_request, sign_in_as
from websockets.exceptions import ConnectionClosed

from tadas.om.tenancy.types.org import Org
from tadas.services.api.app import create_app
from tadas.services.api.gateway.auth import CLOSE_UNAUTHENTICATED
from tadas.services.api.main import server_options
from tadas.services.api.settings import ApiSettings

pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass
class Serving:
    address: str
    org: Org
    server: uvicorn.Server

    async def settled(self) -> None:
        """Waits for the server's socket handlers to end, so what a client's
        close did to the handler is known before the test looks."""
        if handlers := set(self.server.server_state.tasks):
            await asyncio.wait(handlers, timeout=5)


@pytest.fixture
async def served(tmp_path: Path) -> AsyncIterator[Serving]:
    """The API on a real port, over memory storage, with one org seeded."""
    container = build_container(tmp_path)
    _, org = await container.managers.tenancy.bootstrap(
        seed_request(), "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
    )
    port = free_port()
    settings = ApiSettings.model_validate({"environment": "test"})
    config = uvicorn.Config(
        create_app(container), host="127.0.0.1", port=port, **server_options(settings)
    )
    # The steps of `Server.serve`, so the fixture knows when the port is open.
    config.load()
    server = uvicorn.Server(config)
    server.lifespan = config.lifespan_class(config)
    await server.startup()
    serving = asyncio.create_task(server.main_loop())
    try:
        yield Serving(f"127.0.0.1:{port}", org, server)
    finally:
        server.should_exit = True
        await serving
        await server.shutdown()


async def test_a_refused_ticket_is_a_4401_close_on_the_wire(served: Serving) -> None:
    address = served.address
    async with websockets.connect(f"ws://{address}/v1/realtime?ticket=wst_not_a_ticket") as ws:
        with pytest.raises(ConnectionClosed) as closed:
            await ws.recv()
    assert closed.value.rcvd is not None
    assert closed.value.rcvd.code == CLOSE_UNAUTHENTICATED
    assert closed.value.rcvd.reason == "not_authenticated"


async def ticket_for(served: Serving) -> str:
    async with httpx.AsyncClient(base_url=f"http://{served.address}") as client:
        headers = await sign_in_as(client, OWNER["email"], OWNER["password"], served.org.id)
        return (await client.post("/v1/realtime/tickets", headers=headers)).json()["ticket"]


async def test_a_good_ticket_opens_the_channel(served: Serving) -> None:
    ticket = await ticket_for(served)
    async with websockets.connect(f"ws://{served.address}/v1/realtime?ticket={ticket}") as ws:
        hello = await ws.recv()
    assert '"type":"hello"' in str(hello)


async def test_a_client_that_closes_is_not_an_error_on_the_server(
    served: Serving, caplog: pytest.LogCaptureFixture
) -> None:
    """The server, not the test client, decides what a send after the peer
    left becomes; here a client's own close ends the handler quietly."""
    ticket = await ticket_for(served)
    with caplog.at_level(logging.ERROR):
        async with websockets.connect(f"ws://{served.address}/v1/realtime?ticket={ticket}") as ws:
            await ws.recv()
        await served.settled()
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
