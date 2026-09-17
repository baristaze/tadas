"""Edge idempotency over the durable record: a retry replays, a reused key
with another body is refused, keys are personal, and a request still
running answers 409 to its own retry."""

import asyncio
from uuid import UUID

import httpx
import pytest
from api_support import add_member, sign_in_as

from tadas.om.opcontext import Role
from tadas.services.api.container import AppContainer

BODY = {"title": "Write the scaffold", "notes": "and test it"}


async def test_a_retry_replays_the_stored_response(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    headers = {**owner, "Idempotency-Key": "task-1"}
    first = await client.post("/v1/tasks", headers=headers, json=BODY)
    assert first.status_code == 201, first.text
    second = await client.post("/v1/tasks", headers=headers, json=BODY)
    assert second.status_code == 201
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.headers["content-type"] == first.headers["content-type"]
    assert second.json() == first.json()
    listed = await client.get("/v1/tasks", headers=owner)
    assert [t["id"] for t in listed.json()["items"]] == [first.json()["id"]]


async def test_a_reused_key_with_another_body_is_refused(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    headers = {**owner, "Idempotency-Key": "task-1"}
    assert (await client.post("/v1/tasks", headers=headers, json=BODY)).status_code == 201
    reused = await client.post("/v1/tasks", headers=headers, json={**BODY, "notes": "changed"})
    assert reused.status_code == 422, reused.text
    assert reused.json()["error"]["code"] == "validation_failed"
    assert "Idempotent-Replayed" not in reused.headers


async def test_a_refusal_is_replayed_too(client: httpx.AsyncClient, owner: dict[str, str]) -> None:
    headers = {**owner, "Idempotency-Key": "blank-1"}
    first = await client.post("/v1/tasks", headers=headers, json={"title": "   "})
    assert first.status_code == 422 and first.json()["error"]["code"] == "validation_failed"
    second = await client.post("/v1/tasks", headers=headers, json={"title": "   "})
    assert second.status_code == 422
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json() == first.json()


async def test_keys_are_personal_inside_a_tenant(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = UUID((await client.get("/v1/orgs/current", headers=owner)).json()["id"])
    await add_member(container, org_id, "bob@example.test", "pw-1234", Role.MEMBER)
    bob = await sign_in_as(client, "bob@example.test", "pw-1234", org_id)
    first = await client.post("/v1/tasks", headers={**owner, "Idempotency-Key": "k"}, json=BODY)
    second = await client.post("/v1/tasks", headers={**bob, "Idempotency-Key": "k"}, json=BODY)
    assert first.status_code == 201 and second.status_code == 201
    assert "Idempotent-Replayed" not in second.headers
    assert second.json()["id"] != first.json()["id"]


async def test_a_request_still_running_answers_409_to_its_retry(
    client: httpx.AsyncClient,
    container: AppContainer,
    owner: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    original = container.managers.tasks.create_task

    async def slow_create(ctx, task):
        entered.set()
        await release.wait()
        return await original(ctx, task)

    monkeypatch.setattr(container.managers.tasks, "create_task", slow_create)
    headers = {**owner, "Idempotency-Key": "slow-1"}
    first = asyncio.create_task(client.post("/v1/tasks", headers=headers, json=BODY))
    await asyncio.wait_for(entered.wait(), timeout=5)

    retry = await client.post("/v1/tasks", headers=headers, json=BODY)
    assert retry.status_code == 409, retry.text
    assert retry.json()["error"]["code"] == "idempotency_in_progress"

    release.set()
    assert (await first).status_code == 201
    replay = await client.post("/v1/tasks", headers=headers, json=BODY)
    assert replay.status_code == 201 and replay.headers["Idempotent-Replayed"] == "true"


async def test_without_a_key_every_request_creates(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    first = await client.post("/v1/tasks", headers=owner, json=BODY)
    second = await client.post("/v1/tasks", headers=owner, json=BODY)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
