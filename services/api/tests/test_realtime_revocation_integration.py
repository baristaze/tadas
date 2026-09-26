"""A revocation crosses processes: two API containers over the compose
stack's Postgres and Valkey, one serving a socket, the other revoking the
session behind it; the socket closes with 4401 on the wire. When the bus
never carries the message, the serving process's own recheck closes it
within its interval. A change of role closes the socket with 1012."""

import asyncio
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
import websockets
from api_support import OWNER, add_member, seed_request, sign_in_as
from websockets.exceptions import ConnectionClosed

from tadas.om.base import new_id
from tadas.om.opcontext import OpContext, Role
from tadas.om.tenancy.types.org import Org
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer
from tadas.services.api.gateway.auth import CLOSE_UNAUTHENTICATED
from tadas.services.api.main import server_options
from tadas.services.api.realtime.socket import CLOSE_RECONNECT
from tadas.services.api.services.realtime import CREDENTIAL_REVOKED, RIGHTS_CHANGED
from tadas.services.api.settings import ApiSettings

pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def settings_over_the_stack(
    tmp_path: Path, topics_backend: str = "valkey", **overrides: object
) -> ApiSettings:
    """The database from TADAS_DATABASE_URL, the bus and the cache on the
    compose Valkey; refused unless both are local. A process given the
    memory bus publishes where no other process hears: every message it
    sends is lost to the others."""
    settings = ApiSettings.model_validate(
        {
            "cache_backend": "valkey",
            "topics_backend": topics_backend,
            "buckets_root": tmp_path / "buckets",
            **OVER_THE_STACK,
            **overrides,
        }
    )
    settings.refuse_remote()
    return settings


OVER_THE_STACK: dict[str, object] = {
    "buckets_backend": "local",
    "queues_backend": "memory",
    "secrets_backend": "local",
    # The people of the run sign in by address alone, as the local stack does.
    "dev_sign_in_enabled": True,
    # The rest comes from the environment and .env, the tracker's DSN and
    # the collector aside: a test reports nothing anywhere.
    "sentry_dsn": None,
    "otel_endpoint": None,
}


@dataclass(frozen=True)
class TwoProcesses:
    address: str  # where process B serves
    revoker: AppContainer  # process A
    server: AppContainer  # process B
    org: Org
    email: str  # the owner seeded for this run; the database is shared


@asynccontextmanager
async def serving(
    tmp_path: Path, revoker_bus: str = "valkey", **server_settings: object
) -> AsyncIterator[TwoProcesses]:
    """Process B serves the socket on a real port; process A is the one that
    revokes. Each has its own listener on the bus, as two replicas do, unless
    A is given the memory bus, which no other process hears."""
    a = AppContainer.build(settings_over_the_stack(tmp_path, revoker_bus))
    settings = settings_over_the_stack(tmp_path, "valkey", **server_settings)
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
        yield TwoProcesses(f"127.0.0.1:{port}", a, b, org, email)
    finally:
        server.should_exit = True
        await serving
        await server.shutdown()
        await a.close()


@pytest.fixture
async def two_processes(tmp_path: Path) -> AsyncIterator[TwoProcesses]:
    async with serving(tmp_path) as processes:
        yield processes


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


RECHECK_SECONDS = 1.0


async def ticket_for(address: str, headers: dict[str, str]) -> str:
    async with httpx.AsyncClient(base_url=f"http://{address}") as client:
        return (await client.post("/v1/realtime/tickets", headers=headers)).json()["ticket"]


async def headers_of(address: str, email: str, org: Org) -> dict[str, str]:
    async with httpx.AsyncClient(base_url=f"http://{address}") as client:
        return await sign_in_as(client, email, org.id)


async def context_of(container: AppContainer, headers: dict[str, str]) -> OpContext:
    token = headers["Authorization"].removeprefix("Bearer ")
    return await container.managers.tenancy.authenticate(seed_request(), token)


async def closed_within(ws: websockets.ClientConnection, seconds: float) -> ConnectionClosed:
    with pytest.raises(ConnectionClosed) as closed:
        while True:
            await asyncio.wait_for(ws.recv(), timeout=seconds)
    return closed.value


async def test_a_revocation_the_bus_never_carried_closes_within_the_recheck(
    tmp_path: Path,
) -> None:
    """Process A revokes on a bus B does not hear: the message is lost to B.
    B's own recheck finds the session revoked and closes the socket with
    4401 within one interval."""
    async with serving(
        tmp_path, revoker_bus="memory", realtime_recheck_seconds=RECHECK_SECONDS
    ) as processes:
        address, revoker = processes.address, processes.revoker
        headers = await headers_of(address, processes.email, processes.org)
        ticket = await ticket_for(address, headers)
        async with websockets.connect(f"ws://{address}/v1/realtime?ticket={ticket}") as ws:
            assert '"type":"hello"' in str(await ws.recv())
            await revoker.managers.tenancy.logout(await context_of(revoker, headers))
            started = time.monotonic()
            closed = await closed_within(ws, RECHECK_SECONDS + 5)
            waited = time.monotonic() - started
    assert closed.rcvd is not None
    assert closed.rcvd.code == CLOSE_UNAUTHENTICATED
    assert closed.rcvd.reason == "not_authenticated"
    assert waited <= RECHECK_SECONDS + 1.0, f"closed after {waited:.2f}s"


async def test_a_change_of_role_in_one_process_closes_the_socket_in_another(
    tmp_path: Path,
) -> None:
    """The bus names the membership; B closes its member's socket with 1012,
    and the reconnect is admitted under the new role."""
    async with serving(tmp_path) as processes:
        address, revoker, org = processes.address, processes.revoker, processes.org
        bob = await add_member(revoker, org.id, f"bob-{new_id().hex[-8:]}@example.test", Role.ADMIN)
        identity = await revoker.storage.get_tenancy_storage().read_identity(bob.identity_id)
        assert identity is not None
        member = await headers_of(address, identity.email, org)
        owner = await headers_of(address, processes.email, org)
        ticket = await ticket_for(address, member)
        async with websockets.connect(f"ws://{address}/v1/realtime?ticket={ticket}") as ws:
            assert '"type":"hello"' in str(await ws.recv())
            await revoker.managers.tenancy.update_membership_role(
                await context_of(revoker, owner), bob.id, Role.MEMBER
            )
            closed = await closed_within(ws, 10)
        assert closed.rcvd is not None
        assert closed.rcvd.code == CLOSE_RECONNECT
        assert closed.rcvd.reason == RIGHTS_CHANGED
        ticket = await ticket_for(address, member)
        async with websockets.connect(f"ws://{address}/v1/realtime?ticket={ticket}") as ws:
            assert '"type":"hello"' in str(await ws.recv())
