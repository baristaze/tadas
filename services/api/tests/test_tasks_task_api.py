from uuid import UUID, uuid4

import httpx
from api_support import add_member, sign_in_as

from tadas.om.opcontext import Role
from tadas.services.api.container import AppContainer


async def add(
    client: httpx.AsyncClient, headers: dict[str, str], title: str, **extra: object
) -> dict:
    created = await client.post("/v1/tasks", headers=headers, json={"title": title, **extra})
    assert created.status_code == 201, created.text
    return created.json()


async def titles(
    client: httpx.AsyncClient, headers: dict[str, str], **params: str | int
) -> list[str]:
    listed = await client.get("/v1/tasks", headers=headers, params=params)
    assert listed.status_code == 200, listed.text
    return [t["title"] for t in listed.json()["items"]]


async def test_task_round_trip(client: httpx.AsyncClient, owner: dict[str, str]) -> None:
    created = await client.post(
        "/v1/tasks",
        headers={**owner, "Idempotency-Key": "task-1"},
        json={"title": "Write the scaffold", "notes": "and test it"},
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "open" and task["assignee_id"] is None and task["deleted_at"] is None

    replay = await client.post(
        "/v1/tasks",
        headers={**owner, "Idempotency-Key": "task-1"},
        json={"title": "Write the scaffold", "notes": "and test it"},
    )
    assert replay.status_code == 201 and replay.json()["id"] == task["id"]
    assert replay.headers["Idempotent-Replayed"] == "true"

    listed = await client.get("/v1/tasks", headers=owner)
    assert listed.json() == {"items": [task], "next_cursor": None}

    fetched = await client.get(f"/v1/tasks/{task['id']}", headers=owner)
    assert fetched.status_code == 200 and fetched.json()["title"] == "Write the scaffold"

    done = await client.patch(f"/v1/tasks/{task['id']}", headers=owner, json={"status": "done"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done" and done.json()["notes"] == "and test it"
    assert done.json()["updated_at"] > task["updated_at"]
    assert await titles(client, owner) == []
    assert await titles(client, owner, status="done") == ["Write the scaffold"]

    deleted = await client.delete(f"/v1/tasks/{task['id']}", headers=owner)
    assert deleted.status_code == 200 and deleted.json()["deleted_at"] is not None
    assert (await client.get(f"/v1/tasks/{task['id']}", headers=owner)).status_code == 404
    assert await titles(client, owner, status="done") == []


async def test_done_list_pages_by_cursor(client: httpx.AsyncClient, owner: dict[str, str]) -> None:
    for i in range(5):
        task = await add(client, owner, f"t{i}")
        await client.patch(f"/v1/tasks/{task['id']}", headers=owner, json={"status": "done"})
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"status": "done", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/v1/tasks", headers=owner, params=params)).json()
        seen += [t["title"] for t in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ["t4", "t3", "t2", "t1", "t0"] and pages == 3


async def test_move_and_scopes(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = UUID((await client.get("/v1/orgs/current", headers=owner)).json()["id"])
    bob = await add_member(container, org_id, "bob@example.test", "pw-1234", Role.MEMBER)
    as_bob = await sign_in_as(client, "bob@example.test", "pw-1234", org_id)

    c = await add(client, owner, "c")
    await add(client, owner, "b")
    a = await add(client, owner, "a", assignee_id=str(bob.id))
    assert await titles(client, owner) == ["a", "b", "c"]

    moved = await client.post(
        f"/v1/tasks/{a['id']}/move", headers=owner, json={"after_id": c["id"]}
    )
    assert moved.status_code == 200, moved.text
    assert await titles(client, owner) == ["b", "c", "a"]
    await client.post(f"/v1/tasks/{a['id']}/move", headers=owner, json={"after_id": None})
    assert await titles(client, owner) == ["a", "b", "c"]

    assert await titles(client, as_bob, scope="mine") == ["a"]
    assert await titles(client, owner, scope="mine") == ["b", "c"]
    assert await titles(client, as_bob, scope="team") == ["a", "b", "c"]

    unassigned = await client.patch(
        f"/v1/tasks/{a['id']}", headers=owner, json={"assignee_id": None}
    )
    assert unassigned.json()["assignee_id"] is None
    assert await titles(client, owner, scope="mine") == ["a", "b", "c"]


async def test_task_errors_use_the_envelope(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    missing = await client.get(f"/v1/tasks/{uuid4()}", headers=owner)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"

    blank = await client.post("/v1/tasks", headers=owner, json={"title": "   "})
    assert blank.status_code == 422 and blank.json()["error"]["code"] == "validation_failed"

    stranger = await client.post(
        "/v1/tasks", headers=owner, json={"title": "x", "assignee_id": str(uuid4())}
    )
    assert stranger.status_code == 422 and stranger.json()["error"]["code"] == "validation_failed"

    bad_cursor = await client.get(
        "/v1/tasks", headers=owner, params={"status": "done", "cursor": "nope"}
    )
    assert bad_cursor.status_code == 422

    unknown_field = await client.post("/v1/tasks", headers=owner, json={"titel": "x"})
    assert unknown_field.status_code == 422

    anonymous = await client.get("/v1/tasks")
    assert anonymous.status_code == 401
