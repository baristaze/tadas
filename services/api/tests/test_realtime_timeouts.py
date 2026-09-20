"""The client's ping interval, the server's protocol ping and its timeout,
and the load balancer idle timeout are pinned in one shared file, so the
clients, the server, and the infrastructure cannot drift apart."""

import asyncio
import json
from pathlib import Path
from typing import Any

import uvicorn
from uvicorn.server import ServerState

from tadas.services.api.main import server_options
from tadas.services.api.realtime.timeouts import (
    IDLE_TIMEOUT_SECONDS,
    PING_INTERVAL_SECONDS,
    SERVER_PING_INTERVAL_SECONDS,
    SERVER_PING_TIMEOUT_SECONDS,
)
from tadas.services.api.settings import ApiSettings

TIMEOUTS = Path(__file__).resolve().parents[3] / "deployment" / "realtime-timeouts.json"


def pinned() -> dict[str, int]:
    return json.loads(TIMEOUTS.read_text())


def test_ping_interval_matches_the_shared_file() -> None:
    pin = pinned()
    assert PING_INTERVAL_SECONDS == pin["ping_interval_seconds"]
    assert PING_INTERVAL_SECONDS < pin["load_balancer_idle_timeout_seconds"]
    assert IDLE_TIMEOUT_SECONDS >= pin["load_balancer_idle_timeout_seconds"]


def test_the_server_ping_matches_the_shared_file_and_fits_the_idle_timeout() -> None:
    """A socket that has answered nothing for the interval plus the timeout is
    closed by the server itself, before the load balancer would close it."""
    pin = pinned()
    assert SERVER_PING_INTERVAL_SECONDS == pin["server_ping_interval_seconds"]
    assert SERVER_PING_TIMEOUT_SECONDS == pin["server_ping_timeout_seconds"]
    assert SERVER_PING_INTERVAL_SECONDS > 0 and SERVER_PING_TIMEOUT_SECONDS > 0
    assert (
        SERVER_PING_INTERVAL_SECONDS + SERVER_PING_TIMEOUT_SECONDS
        < pin["load_balancer_idle_timeout_seconds"]
    )


async def test_the_server_ping_reaches_uvicorn_and_the_selected_protocol_honors_it() -> None:
    """The options name uvicorn's protocol ping, and the websocket protocol
    class uvicorn selects for this environment reads them: a protocol that
    ignored them would leave a socket to the load balancer's timeout."""
    settings = ApiSettings.model_validate({"environment": "test"})
    options = server_options(settings)
    assert options["ws_ping_interval"] == SERVER_PING_INTERVAL_SECONDS
    assert options["ws_ping_timeout"] == SERVER_PING_TIMEOUT_SECONDS

    config = uvicorn.Config("tadas.services.api.app:create_app", factory=True, **options)
    config.load()
    # uvicorn types the class as a bare asyncio.Protocol; the keepalive fields
    # are what the selected implementation adds.
    protocol_class: Any = config.ws_protocol_class
    assert protocol_class is not None
    protocol = protocol_class(
        config=config, server_state=ServerState(), app_state={}, _loop=asyncio.get_running_loop()
    )
    assert protocol.ping_interval == SERVER_PING_INTERVAL_SECONDS
    assert protocol.ping_timeout == SERVER_PING_TIMEOUT_SECONDS
