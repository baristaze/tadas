"""Helpers the API tests share: the test container and the sign-in flow."""

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import httpx

from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.services.api.container import AppContainer

OWNER = {"email": "ann@example.test", "password": "pw-1234", "name": "Ann"}


def build_container(tmp_path: Path) -> AppContainer:
    return AppContainer.for_tests(StorageMemoryImpl(), InfraLocalImpl(tmp_path))


async def sign_in(client: httpx.AsyncClient, container: AppContainer) -> dict[str, str]:
    """Bootstraps an org, signs its owner in, and returns the tenant headers."""
    org = await container.managers.tenancy.bootstrap(
        "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
    )
    login = await client.post(
        "/v1/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}
    )
    assert login.status_code == 200, login.text
    session = await client.post(
        "/v1/auth/sessions",
        json={"org_id": str(org.id)},
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert session.status_code == 200, session.text
    return {
        "Authorization": f"Bearer {session.json()['token']}",
        "X-App": "portal",
        "X-App-Version": "portal@test",
    }


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """For the few sync tests that need a manager call before the app runs."""
    return asyncio.run(coro)
