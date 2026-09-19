"""The whole API in-process behind the CLI: Starlette's TestClient runs the
app with its lifespan on its own thread, and a transport hops each of the
CLI's requests over to it, so every command runs under its own `asyncio.run`
the way it does in a terminal."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from api_support import OWNER, add_member, build_container, run, seed_request
from starlette.testclient import TestClient
from typer.testing import CliRunner

from tadas.apps.cli import main
from tadas.client.client import ApiClient
from tadas.om.opcontext import Role
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer

BOB = {"email": "bob@example.test", "password": "pw-5678"}


class Hop(httpx.AsyncBaseTransport):
    """Sends the CLI's request through the TestClient, on a worker thread."""

    def __init__(self, tc: TestClient) -> None:
        self._tc = tc

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        def send() -> httpx.Response:
            return self._tc.request(
                request.method,
                str(request.url),
                content=request.read(),
                headers=dict(request.headers),
            )

        response = await asyncio.to_thread(send)
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )


class Stack:
    def __init__(self, tc: TestClient, container: AppContainer, org_id: Any) -> None:
        self.tc = tc
        self.container = container
        self.org_id = org_id
        self.runner = CliRunner()
        self._tokens: dict[str, str] = {}

    def client(self, token: str | None) -> ApiClient:
        return ApiClient(
            "http://test", app="cli", app_version="cli@test", token=token, transport=Hop(self.tc)
        )

    def session_token(self, email: str, password: str) -> str:
        """One session per person; signing in on every command would trip the login rate limit."""
        if email not in self._tokens:
            self._tokens[email] = self._sign_in(email, password)
        return self._tokens[email]

    def _sign_in(self, email: str, password: str) -> str:
        login = self.tc.post("/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        session = self.tc.post(
            "/v1/auth/sessions",
            json={"org_id": str(self.org_id)},
            headers={"Authorization": f"Bearer {login.json()['token']}"},
        )
        assert session.status_code == 200, session.text
        return session.json()["token"]

    def tadas(self, *args: str, token: str | None = "owner", env: dict[str, str] | None = None):
        """Runs one command as the owner (or as `token`); returns the result."""
        variables = {"TADAS_API_URL": "http://test", **(env or {})}
        if token == "owner":
            token = self.session_token(OWNER["email"], OWNER["password"])
        if token is not None:
            variables["TADAS_TOKEN"] = token
        return self.runner.invoke(main.app, list(args), env=variables, catch_exceptions=False)


@pytest.fixture
def stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
        )
    )
    run(add_member(container, org.id, BOB["email"], BOB["password"], Role.MEMBER))
    monkeypatch.setenv("TADAS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TADAS_TOKEN", raising=False)
    with TestClient(create_app(container)) as tc:
        stack = Stack(tc, container, org.id)
        monkeypatch.setattr(main, "build_client", lambda _url, token: stack.client(token))
        yield stack
