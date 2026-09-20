"""Behind a load balancer every request arrives from its address; the login
rate limit keys on the client only when the proxy is trusted to say who the
client is, and never on a header an untrusted peer sent."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from api_support import build_container
from httpx import ASGITransport

from tadas.infra.cache import CacheScope
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer
from tadas.services.api.main import server_options
from tadas.services.api.settings import ApiSettings

PROXY = "10.10.3.7"
OUTSIDER = "198.51.100.7"
CLIENT = "203.0.113.9"


@dataclass
class Served:
    """The app the way `serve` hands it to uvicorn, proxy handling included,
    and every rate-limit key the login route counted, in order."""

    app: Any
    keys: list[str] = field(default_factory=list)

    async def login_from(self, peer: str, forwarded: str | None) -> httpx.Response:
        headers = {"X-Forwarded-For": forwarded} if forwarded else {}
        transport = ASGITransport(app=self.app, client=(peer, 40000), raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/v1/auth/login",
                json={"email": "nobody@example.test", "password": "x"},
                headers=headers,
            )


@pytest.fixture
async def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Served]:
    settings = ApiSettings.model_validate(
        {"environment": "test", "trusted_proxies": ["10.10.0.0/16"]}
    )
    roots = build_container(tmp_path)
    container = AppContainer.for_tests(roots.storage, roots.infra, settings)
    app = create_app(container)
    config = uvicorn.Config(app, **server_options(settings))
    config.load()
    served = Served(config.loaded_app)
    cache = container.infra.get_cache(CacheScope.RATE_LIMIT)
    original = cache.increment

    async def spy(org_id: Any, key: str, ttl: Any) -> Any:
        served.keys.append(key)
        return await original(org_id, key, ttl)

    monkeypatch.setattr(cache, "increment", spy)
    async with app.router.lifespan_context(app):
        yield served


async def test_a_trusted_proxy_names_the_client(served: Served) -> None:
    assert (await served.login_from(PROXY, CLIENT)).status_code == 401
    assert served.keys == [f"login:addr:{CLIENT}"]


async def test_an_untrusted_peer_cannot_choose_its_address(served: Served) -> None:
    assert (await served.login_from(OUTSIDER, CLIENT)).status_code == 401
    assert served.keys == [f"login:addr:{OUTSIDER}"]


def test_no_proxy_means_the_peer_is_the_client() -> None:
    options = server_options(ApiSettings.model_validate({"environment": "test"}))
    assert options["proxy_headers"] is False
    uvicorn.Config(create_app, factory=True, **options)  # loads as `serve` runs it
