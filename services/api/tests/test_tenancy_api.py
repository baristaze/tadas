from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import OWNER, build_container, run
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer


async def test_sign_in_round_trip(client: httpx.AsyncClient, owner: dict[str, str]) -> None:
    me = await client.get("/v1/me", headers=owner)
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["user"]["email"] == OWNER["email"]
    assert body["role"] == "owner"
    assert body["app"] == "portal"
    assert "manage_members" in body["permissions"]

    users = await client.get("/v1/users", headers=owner, params={"limit": 1000})
    assert [u["email"] for u in users.json()] == [OWNER["email"]]
    org = await client.get("/v1/orgs/current", headers=owner)
    assert org.json()["slug"] == "acme"


async def test_error_envelope_carries_the_request_id(client: httpx.AsyncClient) -> None:
    request_id = str(uuid4())
    response = await client.get("/v1/me", headers={"x-request-id": request_id})
    assert response.status_code == 401
    assert response.headers["x-request-id"] == request_id
    assert response.json() == {
        "error": {
            "code": "not_authenticated",
            "message": "missing bearer credential",
            "request_id": request_id,
        }
    }


async def test_unknown_fields_are_refused_with_the_envelope(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    response = await client.post("/v1/api-keys", headers=owner, json={"name": "x", "rol": "member"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    UUID(response.json()["error"]["request_id"])


async def test_not_found_flows_through_the_one_handler(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    response = await client.delete(f"/v1/api-keys/{uuid4()}", headers=owner)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_login_is_rate_limited_per_client(client: httpx.AsyncClient) -> None:
    body = {"email": "nobody@example.test", "password": "x"}
    for _ in range(10):
        assert (await client.post("/v1/auth/login", json=body)).status_code == 401
    rejected = await client.post("/v1/auth/login", json=body)
    assert rejected.status_code == 429
    assert rejected.json()["error"]["code"] == "rate_limited"
    assert int(rejected.headers["Retry-After"]) >= 1


async def test_api_key_creation_replays_on_the_same_idempotency_key(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    headers = {**owner, "Idempotency-Key": "create-ci-key-1"}
    body = {"name": "ci", "role": "member"}
    first = await client.post("/v1/api-keys", headers=headers, json=body)
    assert first.status_code == 201, first.text
    second = await client.post("/v1/api-keys", headers=headers, json=body)
    assert second.status_code == 201
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json() == first.json()

    keys = await client.get("/v1/api-keys", headers=owner)
    assert [k["id"] for k in keys.json()] == [first.json()["api_key"]["id"]]

    as_machine = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {first.json()['key']}"}
    )
    assert as_machine.status_code == 200
    assert as_machine.json()["app"] == "api"
    assert as_machine.json()["role"] == "member"

    revoked = await client.delete(f"/v1/api-keys/{first.json()['api_key']['id']}", headers=owner)
    assert revoked.status_code == 200 and revoked.json()["deleted_at"] is not None
    refused = await client.get("/v1/me", headers={"Authorization": f"Bearer {first.json()['key']}"})
    assert refused.status_code == 401


async def test_operator_routes_need_an_operator_sign_in(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    refused = await client.get("/v1/admin/orgs", headers=owner)
    assert refused.status_code == 401
    await container.managers.tenancy.bootstrap(
        "Ops", "ops", "root@example.test", "pw-1234", "Root", operator=True
    )
    login = await client.post(
        "/v1/auth/login", json={"email": "root@example.test", "password": "pw-1234"}
    )
    admitted = await client.get(
        "/v1/admin/orgs", headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    assert admitted.status_code == 200
    assert sorted(o["slug"] for o in admitted.json()) == ["acme", "ops"]


def test_realtime_channel_delivers_tenant_events(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    org = run(
        container.managers.tenancy.bootstrap(
            "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
        )
    )
    app = create_app(container)
    with TestClient(app) as tc:
        login = tc.post(
            "/v1/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}
        )
        session = tc.post(
            "/v1/auth/sessions",
            json={"org_id": str(org.id)},
            headers={"Authorization": f"Bearer {login.json()['token']}"},
        )
        headers = {"Authorization": f"Bearer {session.json()['token']}", "X-App": "portal"}
        ticket = tc.post("/v1/realtime/tickets", headers=headers)
        assert ticket.status_code == 201, ticket.text
        url = f"/v1/realtime?ticket={ticket.json()['ticket']}"
        with tc.websocket_connect(url) as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello" and hello["seq"] == 1
            ws.send_json({"op": "subscribe", "topic": "entity_changed"})
            assert ws.receive_json()["type"] == "subscribed"
            ws.send_json({"op": "ping"})
            assert ws.receive_json()["type"] == "pong"
            created = tc.post(
                "/v1/api-keys", headers=headers, json={"name": "ci", "role": "member"}
            )
            assert created.status_code == 201, created.text
            event = ws.receive_json()
            assert event["type"] == "event" and event["topic"] == "entity_changed"
            assert event["payload"]["entity"] == "api_key"
            assert event["payload"]["entity_id"] == created.json()["api_key"]["id"]
        with pytest.raises(WebSocketDisconnect) as refused:
            with tc.websocket_connect(url):
                pass
        assert refused.value.code == 4401
