from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from api_support import OWNER, add_member, build_container, run, seed_request, sign_in_as
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tadas.om.idempotency.impl.manager import IdempotencyOptions
from tadas.om.opcontext import Role
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


async def test_a_member_cannot_mint_a_service_key(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = UUID((await client.get("/v1/orgs/current", headers=owner)).json()["id"])
    await add_member(container, org_id, "bob@example.test", "pw-1234", Role.MEMBER)
    bob = await sign_in_as(client, "bob@example.test", "pw-1234", org_id)
    for headers in (bob, owner):
        refused = await client.post(
            "/v1/api-keys", headers=headers, json={"name": "svc", "role": "service"}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "validation_failed"
    assert (await client.get("/v1/api-keys", headers=owner)).json() == []


async def test_a_crash_between_the_key_create_and_finish_reissues_the_secret(
    client: httpx.AsyncClient,
    container: AppContainer,
    owner: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The key landed, then the process died before the outcome reached the
    # marker, so the secret reached no one. The retry takes the marker over and
    # runs the create again on the same id: a fresh secret on the same key.
    manager = container.managers.idempotency
    monkeypatch.setattr(manager, "_options", IdempotencyOptions(pending_ttl=timedelta(0)))
    original_finish = manager.finish
    crashed = False

    async def crash_once(ctx, key, attempt_id, status, body):
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("the process died before finish")
        return await original_finish(ctx, key, attempt_id, status, body)

    monkeypatch.setattr(manager, "finish", crash_once)
    headers = {**owner, "Idempotency-Key": "key-crash-1"}
    body = {"name": "ci", "role": "member"}
    first = await client.post("/v1/api-keys", headers=headers, json=body)
    assert first.status_code == 500 and crashed
    keys = (await client.get("/v1/api-keys", headers=owner)).json()
    assert len(keys) == 1, "the create landed before the crash"

    retry = await client.post("/v1/api-keys", headers=headers, json=body)
    assert retry.status_code == 201, retry.text
    assert "Idempotent-Replayed" not in retry.headers
    assert retry.json()["api_key"]["id"] == keys[0]["id"]
    assert (await client.get("/v1/api-keys", headers=owner)).json() == [retry.json()["api_key"]]
    as_machine = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {retry.json()['key']}"}
    )
    assert as_machine.status_code == 200, as_machine.text
    replay = await client.post("/v1/api-keys", headers=headers, json=body)
    assert replay.status_code == 201 and replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == retry.json()


async def test_api_key_ttl_is_bounded_on_the_wire(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    for ttl_days in (0, 91):
        response = await client.post(
            "/v1/api-keys",
            headers=owner,
            json={"name": "x", "role": "member", "ttl_days": ttl_days},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_failed"
    accepted = await client.post(
        "/v1/api-keys", headers=owner, json={"name": "x", "role": "member", "ttl_days": 7}
    )
    assert accepted.status_code == 201, accepted.text


async def test_idempotency_keys_are_per_user_inside_a_tenant(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = (await client.get("/v1/orgs/current", headers=owner)).json()["id"]
    await add_member(container, UUID(org_id), "bob@example.test", "pw-1234", Role.MEMBER)
    bob = await sign_in_as(client, "bob@example.test", "pw-1234", UUID(org_id))
    body = {"name": "ci", "role": "member"}

    first = await client.post(
        "/v1/api-keys", headers={**owner, "Idempotency-Key": "shared-1"}, json=body
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/v1/api-keys", headers={**bob, "Idempotency-Key": "shared-1"}, json=body
    )
    assert second.status_code == 201, second.text
    assert "Idempotent-Replayed" not in second.headers
    assert second.json()["api_key"]["id"] != first.json()["api_key"]["id"]
    assert second.json()["api_key"]["user_id"] != first.json()["api_key"]["user_id"]


async def test_members_are_promoted_and_removed_by_a_member_manager(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = UUID((await client.get("/v1/orgs/current", headers=owner)).json()["id"])
    bob = await add_member(container, org_id, "bob@example.test", "pw-1234", Role.VIEWER)
    as_bob = await sign_in_as(client, "bob@example.test", "pw-1234", org_id)

    refused = await client.patch(
        f"/v1/memberships/{bob.id}", headers=as_bob, json={"role": "admin"}
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "not_authorized"

    promoted = await client.patch(
        f"/v1/memberships/{bob.id}", headers=owner, json={"role": "admin"}
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "admin"
    assert (await client.get("/v1/me", headers=as_bob)).json()["role"] == "admin"

    missing = await client.delete(f"/v1/memberships/{uuid4()}", headers=owner)
    assert missing.status_code == 404
    removed = await client.delete(f"/v1/memberships/{bob.id}", headers=owner)
    assert removed.status_code == 200, removed.text
    assert removed.json()["id"] == str(bob.id)
    assert (await client.get("/v1/me", headers=as_bob)).status_code == 401
    users = await client.get("/v1/users", headers=owner)
    assert [u["email"] for u in users.json()] == [OWNER["email"]]


async def test_me_is_renamed_and_the_identity_is_read(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    renamed = await client.patch("/v1/me", headers=owner, json={"display_name": "Ann B."})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["display_name"] == "Ann B."
    assert (await client.get("/v1/me", headers=owner)).json()["user"]["display_name"] == "Ann B."
    blank = await client.patch("/v1/me", headers=owner, json={"display_name": ""})
    assert blank.status_code == 422

    identity = await client.get("/v1/me/identity", headers=owner)
    assert identity.status_code == 200, identity.text
    assert identity.json()["email"] == OWNER["email"]
    assert identity.json()["is_operator"] is False
    assert "password_hash" not in identity.json()


async def test_sessions_are_listed_revoked_and_logged_out(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = UUID((await client.get("/v1/orgs/current", headers=owner)).json()["id"])
    other = await sign_in_as(client, OWNER["email"], OWNER["password"], org_id)

    listed = await client.get("/v1/sessions", headers=owner)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 2
    assert all(s["credential_kind"] == "session_token" for s in listed.json())
    assert all(s["revoked_at"] is None for s in listed.json())

    mine = (await client.post("/v1/auth/logout", headers=other)).json()["id"]
    remaining = [s["id"] for s in (await client.get("/v1/sessions", headers=owner)).json()]
    assert mine not in remaining and len(remaining) == 1
    assert (await client.get("/v1/me", headers=other)).status_code == 401

    revoked = await client.delete(f"/v1/sessions/{remaining[0]}", headers=owner)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revoked_at"] is not None
    assert (await client.get("/v1/me", headers=owner)).status_code == 401


async def test_operator_routes_need_an_operator_sign_in(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    refused = await client.get("/v1/admin/orgs", headers=owner)
    assert refused.status_code == 401
    await container.managers.tenancy.bootstrap(
        seed_request(), "Ops", "ops", "root@example.test", "pw-1234", "Root", operator=True
    )
    login = await client.post(
        "/v1/auth/login", json={"email": "root@example.test", "password": "pw-1234"}
    )
    admitted = await client.get(
        "/v1/admin/orgs", headers={"Authorization": f"Bearer {login.json()['token']}"}
    )
    assert admitted.status_code == 200
    assert sorted(o["slug"] for o in admitted.json()) == ["acme", "ops"]


async def test_operators_delete_an_org(
    client: httpx.AsyncClient, container: AppContainer, owner: dict[str, str]
) -> None:
    org_id = (await client.get("/v1/orgs/current", headers=owner)).json()["id"]
    await container.managers.tenancy.bootstrap(
        seed_request(), "Ops", "ops", "root@example.test", "pw-1234", "Root", operator=True
    )
    login = await client.post(
        "/v1/auth/login", json={"email": "root@example.test", "password": "pw-1234"}
    )
    admin = {"Authorization": f"Bearer {login.json()['token']}"}

    assert (await client.delete(f"/v1/admin/orgs/{org_id}", headers=owner)).status_code == 401
    deleted = await client.delete(f"/v1/admin/orgs/{org_id}", headers=admin)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_at"] is not None
    assert (await client.delete(f"/v1/admin/orgs/{org_id}", headers=admin)).status_code == 404
    assert (await client.get("/v1/me", headers=owner)).status_code == 401


def test_realtime_channel_delivers_tenant_events(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
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
        assert ticket.json()["ticket"].startswith("tkt_")
        assert 0 < ticket.json()["expires_in_seconds"] <= 60
        url = f"/v1/realtime?ticket={ticket.json()['ticket']}"
        with tc.websocket_connect(url) as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello" and hello["org_id"] == str(org.id)
            ws.send_json({"op": "subscribe", "topic": "entity_changed"})
            assert ws.receive_json()["type"] == "subscribed"
            ws.send_json({"op": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong" and pong["seq"] == hello["seq"]
            created = tc.post(
                "/v1/api-keys", headers=headers, json={"name": "ci", "role": "member"}
            )
            assert created.status_code == 201, created.text
            event = ws.receive_json()
            assert event["type"] == "event" and event["topic"] == "entity_changed"
            assert event["payload"]["kind"] == "tenancy.api_key.created"
            assert event["payload"]["target_id"] == created.json()["api_key"]["id"]
            assert set(event["payload"]) == {"kind", "target_id", "seq", "actor_id"}
        with pytest.raises(WebSocketDisconnect) as refused:
            with tc.websocket_connect(url):
                pass
        assert refused.value.code == 4401
