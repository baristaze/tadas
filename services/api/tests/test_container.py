"""The container builds every root once, at boot; a request constructs
nothing (ADR 0007)."""

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.services.api import container as container_module
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer


async def test_managers_are_built_once_for_any_number_of_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_build = container_module.build_managers

    def counting_build(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return real_build(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(container_module, "build_managers", counting_build)
    container = AppContainer.for_tests(StorageMemoryImpl(), InfraLocalImpl(tmp_path))
    assert len(calls) == 1

    app: FastAPI = create_app(container)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Flows that touch different managers, or none: the health probe,
            # readiness (storage), a sign-in attempt (tenancy), a task list
            # (the gateway refuses before tasks), events.
            for path in ("/healthz", "/readyz", "/v1/tasks", "/v1/events", "/metrics"):
                await client.get(path)
            await client.post(
                "/v1/auth/login", json={"email": "nobody@example.test", "password": "x"}
            )
    assert len(calls) == 1
    # Every router resolves the same frozen object the container built.
    assert app.state.container.managers is container.managers
