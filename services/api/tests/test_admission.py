"""Admission: the process refuses past the bound of what it has in flight,
fast and in the unavailable shape, and never refuses the probes that say so."""

import asyncio
from pathlib import Path

import httpx
import pytest
from api_support import build_container
from fastapi import FastAPI

from tadas.services.api.container import AppContainer

BOUND = 1
"""One request in flight, so a second is the refused one."""


@pytest.fixture
def container(tmp_path: Path) -> AppContainer:
    """Overrides the container of `conftest`, so the `app` and `client`
    fixtures above run against a process with a bound of one."""
    return build_container(tmp_path, admission_in_flight_limit=BOUND)


def holding_route(app: FastAPI, entered: asyncio.Event, release: asyncio.Event) -> None:
    """A route that holds its slot: it says it is in flight and waits for the
    test to let it go, the way a slow dependency holds a real request."""

    @app.get("/v1/holding", include_in_schema=False)
    async def holding() -> dict[str, bool]:
        entered.set()
        await release.wait()
        return {"held": True}


async def hold(
    app: FastAPI, client: httpx.AsyncClient
) -> tuple[asyncio.Task[httpx.Response], asyncio.Event]:
    """Fills the bound and returns the held request with the event that ends it."""
    entered, release = asyncio.Event(), asyncio.Event()
    holding_route(app, entered, release)
    held = asyncio.create_task(client.get("/v1/holding"))
    await asyncio.wait_for(entered.wait(), timeout=5)
    return held, release


async def test_admission_refuses_past_the_bound(app: FastAPI, client: httpx.AsyncClient) -> None:
    held, release = await hold(app, client)

    refused = await client.get("/v1/holding", headers={"Origin": "http://localhost:5173"})

    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "unavailable"
    assert refused.headers["Retry-After"] == "1"
    # Where admission sits: inside the request id, so the refusal carries one,
    # and inside CORS, so a browser may read the body and the wait.
    assert refused.headers["x-request-id"] != ""
    assert refused.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "Retry-After" in refused.headers["access-control-expose-headers"]
    release.set()
    assert (await held).status_code == 200


async def test_the_slot_is_free_again_once_the_request_answers(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    held, release = await hold(app, client)
    assert (await client.get("/v1/holding")).status_code == 503

    release.set()
    await held

    # The same route, now answering at once: the count came back down, so the
    # process admits again instead of staying closed after a burst.
    assert (await client.get("/v1/holding")).status_code == 200


async def test_the_probes_answer_while_admission_is_saturated(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """A saturated process must still be able to say that it is saturated, and
    the collector must still be able to read the counter that says by how much."""
    held, release = await hold(app, client)

    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/readyz")).status_code == 200
    assert (await client.get("/metrics")).status_code == 200

    release.set()
    assert (await held).status_code == 200
