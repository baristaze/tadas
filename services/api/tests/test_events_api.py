"""Every push is also a record: a task write appears on the channel with its
stream position and again on /v1/events after the last seq a client saw."""

from pathlib import Path

import httpx
from api_support import OWNER, build_container, run
from starlette.testclient import TestClient

from tadas.services.api.app import create_app


async def test_events_are_paged_by_seq(client: httpx.AsyncClient, owner: dict[str, str]) -> None:
    created = await client.post("/v1/tasks", headers=owner, json={"title": "one"})
    task_id = created.json()["id"]
    await client.patch(f"/v1/tasks/{task_id}", headers=owner, json={"status": "done"})
    await client.delete(f"/v1/tasks/{task_id}", headers=owner)

    everything = await client.get("/v1/events", headers=owner, params={"after_seq": 0})
    assert everything.status_code == 200, everything.text
    events = everything.json()
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert [e["action"] for e in events] == ["created", "updated", "deleted"]
    assert all(e["entity"] == "task" and e["entity_id"] == task_id for e in events)
    assert set(events[0]) == {"seq", "entity", "entity_id", "action", "produced_at"}

    tail = await client.get("/v1/events", headers=owner, params={"after_seq": 2, "limit": 10})
    assert [e["seq"] for e in tail.json()] == [3]
    assert (
        await client.get("/v1/events", headers=owner, params={"after_seq": -1})
    ).status_code == 422
    assert (await client.get("/v1/events")).status_code == 401


def test_a_push_carries_the_stream_position(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
        )
    )
    with TestClient(create_app(container)) as tc:
        login = tc.post(
            "/v1/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}
        )
        session = tc.post(
            "/v1/auth/sessions",
            json={"org_id": str(org.id)},
            headers={"Authorization": f"Bearer {login.json()['token']}"},
        )
        headers = {"Authorization": f"Bearer {session.json()['token']}", "X-App": "portal"}
        ticket = tc.post("/v1/realtime/tickets", headers=headers).json()["ticket"]
        with tc.websocket_connect(f"/v1/realtime?ticket={ticket}") as ws:
            assert ws.receive_json()["type"] == "hello"
            ws.send_json({"op": "subscribe", "topic": "entity_changed"})
            assert ws.receive_json()["type"] == "subscribed"
            ws.send_json({"op": "subscribe", "topic": "work_available"})
            refused = ws.receive_json()
            assert refused["type"] == "error" and refused["code"] == "validation_failed"

            created = tc.post("/v1/tasks", headers=headers, json={"title": "one"})
            assert created.status_code == 201, created.text
            event = ws.receive_json()
            assert event["type"] == "event" and event["topic"] == "entity_changed"
            assert event["payload"] == {
                "entity": "task",
                "entity_id": created.json()["id"],
                "action": "created",
                "seq": 1,
            }
        replay = tc.get("/v1/events", headers=headers, params={"after_seq": 0})
        assert [e["seq"] for e in replay.json()] == [1]
