from uuid import UUID, uuid4

import httpx
from api_support import add_member, sign_in_as

from tadas.om.base import PROVENANCE_FIELDS
from tadas.om.opcontext import Role
from tadas.services.api.container import AppContainer
from tadas.services.api.types.tasks import UpdateTaskRequest


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


async def patch(
    client: httpx.AsyncClient, headers: dict[str, str], task: dict, **changes: object
) -> dict:
    """An update from the task as held: it names the version it carries."""
    body = {**changes, "version": task["version"]}
    patched = await client.patch(f"/v1/tasks/{task['id']}", headers=headers, json=body)
    assert patched.status_code == 200, patched.text
    return patched.json()


async def move(
    client: httpx.AsyncClient, headers: dict[str, str], task: dict, after_id: str | None
) -> httpx.Response:
    body = {"after_id": after_id, "version": task["version"]}
    return await client.post(f"/v1/tasks/{task['id']}/move", headers=headers, json=body)


async def test_task_round_trip(client: httpx.AsyncClient, owner: dict[str, str]) -> None:
    created = await client.post(
        "/v1/tasks",
        headers={**owner, "Idempotency-Key": "task-1"},
        json={"title": "Write the scaffold", "notes": "and test it"},
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "open" and task["assignee_id"] is None and task["deleted_at"] is None
    assert task["version"] == 1

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

    done = await client.patch(
        f"/v1/tasks/{task['id']}", headers=owner, json={"status": "done", "version": 1}
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done" and done.json()["notes"] == "and test it"
    assert done.json()["updated_at"] > task["updated_at"] and done.json()["version"] == 2
    assert await titles(client, owner) == []
    assert await titles(client, owner, status="done") == ["Write the scaffold"]

    deleted = await client.delete(f"/v1/tasks/{task['id']}", headers=owner, params={"version": 2})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None and deleted.json()["version"] == 3
    assert (await client.get(f"/v1/tasks/{task['id']}", headers=owner)).status_code == 404
    assert await titles(client, owner, status="done") == []


async def test_done_list_pages_by_cursor(client: httpx.AsyncClient, owner: dict[str, str]) -> None:
    for i in range(5):
        task = await add(client, owner, f"t{i}")
        await patch(client, owner, task, status="done")
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

    moved = await move(client, owner, a, c["id"])
    assert moved.status_code == 200, moved.text
    assert await titles(client, owner) == ["b", "c", "a"]
    back = await move(client, owner, moved.json(), None)
    assert back.status_code == 200, back.text
    assert await titles(client, owner) == ["a", "b", "c"]

    assert await titles(client, as_bob, scope="mine") == ["a"]
    assert await titles(client, owner, scope="mine") == ["b", "c"]
    assert await titles(client, as_bob, scope="team") == ["a", "b", "c"]

    unassigned = await patch(client, owner, back.json(), assignee_id=None)
    assert unassigned["assignee_id"] is None
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


def test_the_partial_update_cannot_name_provenance() -> None:
    """The service's merge copies the request's set fields onto the stored
    task; the request type has no provenance field to set and forbids extra
    ones, so the translation cannot rewrite who made a row or its deletion."""
    reserved = PROVENANCE_FIELDS | {"id", "updated_at", "updated_by", "position"}
    assert set(UpdateTaskRequest.model_fields).isdisjoint(reserved)
    assert UpdateTaskRequest.model_config.get("extra") == "forbid"


async def test_a_patch_naming_provenance_is_refused(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    created = await client.post("/v1/tasks", headers=owner, json={"title": "keep me"})
    assert created.status_code == 201
    task_id = created.json()["id"]
    for field in ("created_by", "created_at", "deleted_at", "deleted_by"):
        patched = await client.patch(
            f"/v1/tasks/{task_id}", headers=owner, json={"title": "x", "version": 1, field: None}
        )
        assert patched.status_code == 422, (field, patched.text)
    unchanged = await client.get(f"/v1/tasks/{task_id}", headers=owner)
    assert unchanged.json() == created.json()


async def test_every_write_names_the_version_it_read(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    # The version is not optional: a write that does not say which task it
    # saw is a validation failure, not a write that wins by default.
    task = await add(client, owner, "unversioned")
    no_version = await client.patch(f"/v1/tasks/{task['id']}", headers=owner, json={"title": "x"})
    assert no_version.status_code == 422, no_version.text
    no_move = await client.post(
        f"/v1/tasks/{task['id']}/move", headers=owner, json={"after_id": None}
    )
    assert no_move.status_code == 422, no_move.text
    no_delete = await client.delete(f"/v1/tasks/{task['id']}", headers=owner)
    assert no_delete.status_code == 422, no_delete.text
    assert (await client.get(f"/v1/tasks/{task['id']}", headers=owner)).json() == task


async def test_two_updates_from_one_snapshot_one_wins_and_the_other_is_409(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = UUID((await client.get("/v1/orgs/current", headers=owner)).json()["id"])
    await add_member(container, org_id, "bob@example.test", "pw-1234", Role.MEMBER)
    as_bob = await sign_in_as(client, "bob@example.test", "pw-1234", org_id)
    # Both read the task at version 1; Ann's edit lands, Bob's names a version
    # the task is no longer at and is refused with a stable code and nothing
    # changed. Bob reads again and his edit lands over Ann's.
    task = await add(client, owner, "as read")
    anns = await patch(client, owner, task, title="ann's")
    bobs = await client.patch(
        f"/v1/tasks/{task['id']}", headers=as_bob, json={"title": "bob's", "version": 1}
    )
    assert bobs.status_code == 409, bobs.text
    assert bobs.json()["error"]["code"] == "version_mismatch"
    assert (await client.get(f"/v1/tasks/{task['id']}", headers=as_bob)).json() == anns
    again = await patch(client, as_bob, anns, title="bob's")
    assert again["title"] == "bob's" and again["version"] == 3

    # The same for a move and a delete from the stale snapshot.
    stale_move = await move(client, as_bob, task, None)
    assert stale_move.status_code == 409, stale_move.text
    assert stale_move.json()["error"]["code"] == "version_mismatch"
    stale_delete = await client.delete(
        f"/v1/tasks/{task['id']}", headers=as_bob, params={"version": 1}
    )
    assert stale_delete.status_code == 409
    assert stale_delete.json()["error"]["code"] == "version_mismatch"
    assert await titles(client, owner) == ["bob's"]


async def test_a_delete_racing_an_edit_cannot_be_undone_by_the_edit(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    task = await add(client, owner, "going")
    deleted = await client.delete(
        f"/v1/tasks/{task['id']}", headers=owner, params={"version": task["version"]}
    )
    assert deleted.status_code == 200, deleted.text
    # The edit holds the snapshot from before the delete: the task is gone
    # for it, and its "not deleted" never lands.
    edit = await client.patch(
        f"/v1/tasks/{task['id']}", headers=owner, json={"title": "back?", "version": 1}
    )
    assert edit.status_code == 404, edit.text
    assert await titles(client, owner) == [] and await titles(client, owner, status="done") == []
