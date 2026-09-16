from uuid import uuid4

import httpx


async def test_task_round_trip(client: httpx.AsyncClient, owner: dict[str, str]) -> None:
    created = await client.post(
        "/v1/tasks",
        headers={**owner, "Idempotency-Key": "task-1"},
        json={"title": "Write the scaffold", "notes": "and test it"},
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "open" and task["deleted_at"] is None

    replay = await client.post(
        "/v1/tasks",
        headers={**owner, "Idempotency-Key": "task-1"},
        json={"title": "Write the scaffold"},
    )
    assert replay.status_code == 201 and replay.json()["id"] == task["id"]

    listed = await client.get("/v1/tasks", headers=owner, params={"limit": 100000})
    assert [t["id"] for t in listed.json()] == [task["id"]]

    fetched = await client.get(f"/v1/tasks/{task['id']}", headers=owner)
    assert fetched.status_code == 200 and fetched.json()["title"] == "Write the scaffold"

    updated = await client.put(
        f"/v1/tasks/{task['id']}",
        headers=owner,
        json={"title": "Write the scaffold", "notes": "tested", "status": "done"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "done"
    assert updated.json()["updated_at"] > task["updated_at"]

    deleted = await client.delete(f"/v1/tasks/{task['id']}", headers=owner)
    assert deleted.status_code == 200 and deleted.json()["deleted_at"] is not None
    assert (await client.get(f"/v1/tasks/{task['id']}", headers=owner)).status_code == 404
    assert (await client.get("/v1/tasks", headers=owner)).json() == []


async def test_task_errors_use_the_envelope(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    missing = await client.get(f"/v1/tasks/{uuid4()}", headers=owner)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"

    blank = await client.post("/v1/tasks", headers=owner, json={"title": "   "})
    assert blank.status_code == 422 and blank.json()["error"]["code"] == "validation_failed"

    unknown_field = await client.post("/v1/tasks", headers=owner, json={"titel": "x"})
    assert unknown_field.status_code == 422

    anonymous = await client.get("/v1/tasks")
    assert anonymous.status_code == 401
