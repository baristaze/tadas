"""Helpers the API tests share: the test container and the sign-in flow."""

import asyncio
import secrets
from collections.abc import Coroutine
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.base import new_id, utcnow
from tadas.om.opcontext import Role
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.tenancy.rules import hash_password
from tadas.om.tenancy.types.identity import Identity
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.user import User
from tadas.services.api.container import AppContainer

OWNER = {"email": "ann@example.test", "password": "pw-1234", "name": "Ann"}


def build_container(tmp_path: Path) -> AppContainer:
    return AppContainer.for_tests(StorageMemoryImpl(), InfraLocalImpl(tmp_path))


async def sign_in_as(
    client: httpx.AsyncClient, email: str, password: str, org_id: UUID
) -> dict[str, str]:
    """Signs a person in and chooses a tenant; returns the tenant headers."""
    login = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    session = await client.post(
        "/v1/auth/sessions",
        json={"org_id": str(org_id)},
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    assert session.status_code == 200, session.text
    return {
        "Authorization": f"Bearer {session.json()['token']}",
        "X-App": "portal",
        "X-App-Version": "portal@test",
    }


async def sign_in(client: httpx.AsyncClient, container: AppContainer) -> dict[str, str]:
    """Bootstraps an org, signs its owner in, and returns the tenant headers."""
    _, org = await container.managers.tenancy.bootstrap(
        "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
    )
    return await sign_in_as(client, OWNER["email"], OWNER["password"], org.id)


async def add_member(
    container: AppContainer, org_id: UUID, email: str, password: str, role: Role
) -> User:
    """Seeds a second member straight into storage; there is no invitation flow yet."""
    storage = container.storage.get_tenancy_storage()
    now = utcnow()
    identity_id, user_id = new_id(), new_id()
    await storage.write_identity(
        Identity(
            id=identity_id,
            created_at=now,
            updated_at=now,
            created_by=identity_id,
            email=email,
            password_hash=hash_password(password, secrets.token_bytes(16)),
        )
    )
    user = User(
        id=user_id,
        created_at=now,
        updated_at=now,
        created_by=user_id,
        identity_id=identity_id,
        email=email,
        display_name=email.split("@")[0].title(),
    )
    await storage.write_user(org_id, user)
    await storage.write_membership(
        org_id,
        Membership(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=user_id,
            user_id=user_id,
            role=role,
        ),
    )
    return user


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """For the few sync tests that need a manager call before the app runs."""
    return asyncio.run(coro)
