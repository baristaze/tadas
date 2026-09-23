"""A revocation crosses processes: two API containers over the compose
stack's Postgres and Valkey, one serving a socket, the other revoking the
session behind it; the socket closes with 4401 on the wire."""

import asyncio
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
import websockets
from api_support import OWNER, seed_request, sign_in_as
from websockets.exceptions import ConnectionClosed

from tadas.om.base import new_id
from tadas.om.tenancy.types.org import Org
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer
from tadas.services.api.gateway.auth import CLOSE_UNAUTHENTICATED
from tadas.services.api.main import server_options
from tadas.services.api.services.realtime import CREDENTIAL_REVOKED
from tadas.services.api.settings import ApiSettings

pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def settings_over_the_stack(tmp_path: Path) -> ApiSettings:
    """The database from TADAS_DATABASE_URL, the bus and the cache on the
    compose Valkey; refused unless both are local."""
    settings = ApiSettings(
        cache_backend="valkey",
        topics_backend="valkey",
        buckets_backend="local",
        buckets_root=tmp_path / "buckets",
        queues_backend="memory",
        secrets_backend="local",
        # The people of the run sign in by address alone, as the local stack does.
        dev_sign_in_enabled=True,
        # The rest comes from the environment and .env, the tracker's DSN
        # and the collector aside: a test reports nothing anywhere.
        sentry_dsn=None,
        otel_endpoint=None,
    )
    settings.refuse_remote()
    return settings


@dataclass(frozen=True)
class TwoProcesses:
    address: str  # where process B serves
    revoker: AppContainer  # process A
    org: Org
    email: str  # the owner seeded for this run; the database is shared


@pytest.fixture
async def two_processes(tmp_path: Path) -> AsyncIterator[TwoProcesses]:
    """Process B serves the socket on a real port; process A is the one that
    revokes. Each has its own listener on the bus, as two replicas do."""
    settings = settings_over_the_stack(tmp_path)
    a = AppContainer.build(settings)
    b = AppContainer.build(settings)
    await a.start()
    suffix = new_id().hex[-8:]  # the random tail; a uuid7 leads with the clock
    email = f"ann-{suffix}@example.test"
    _, org = await a.managers.tenancy.bootstrap(
        seed_request(), "Acme", f"acme-{suffix}", email, OWNER["name"]
    )
    port = free_port()
    config = uvicorn.Config(create_app(b), host="127.0.0.1", port=port, **server_options(settings))
    config.load()
    server = uvicorn.Server(config)
    server.lifespan = config.lifespan_class(config)
    await server.startup()
    serving = asyncio.create_task(server.main_loop())
    try:
        yield TwoProcesses(f"127.0.0.1:{port}", a, org, email)
    finally:
        server.should_exit = True
        await serving
        await server.shutdown()
        await a.close()


async def test_a_revocation_in_one_process_closes_the_socket_in_another(
    two_processes: TwoProcesses,
) -> None:
    address, revoker, org = two_processes.address, two_processes.revoker, two_processes.org
    async with httpx.AsyncClient(base_url=f"http://{address}") as client:
        headers = await sign_in_as(client, two_processes.email, org.id)
        ticket = (await client.post("/v1/realtime/tickets", headers=headers)).json()["ticket"]
    token = headers["Authorization"].removeprefix("Bearer ")
    async with websockets.connect(f"ws://{address}/v1/realtime?ticket={ticket}") as ws:
        assert '"type":"hello"' in str(await ws.recv())
        # Process A revokes the session; its relay publishes on the shared bus.
        ctx = await revoker.managers.tenancy.authenticate(seed_request(), token)
        await revoker.managers.tenancy.logout(ctx)
        with pytest.raises(ConnectionClosed) as closed:
            await asyncio.wait_for(ws.recv(), timeout=10)
    assert closed.value.rcvd is not None
    assert closed.value.rcvd.code == CLOSE_UNAUTHENTICATED
    assert closed.value.rcvd.reason == CREDENTIAL_REVOKED
