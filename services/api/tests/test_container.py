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
from tadas.services.api.main import main


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


@pytest.mark.parametrize("role", ["owner", "service"])
def test_add_member_refuses_a_role_no_membership_can_take(
    role: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The ops CLI's --role choices are the roles `update_membership_role`
    accepts. OWNER is the org's own, minted by bootstrap, and SERVICE is the
    role a sweep's context carries, which the manager refuses outright: either
    one offered here would fail with an uncaught ValidationFailed instead of a
    usage message."""
    with pytest.raises(SystemExit) as exit_code:
        main(
            [
                "add-member",
                "--slug",
                "acme",
                "--email",
                "a@b.test",
                "--password",
                "pw-1234",
                "--name",
                "A",
                "--role",
                role,
            ]
        )
    assert exit_code.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
