"""The operator plane over the live app: which permission each route asks
for, the reads of one tenant and the trail they leave, the platform's size,
and the two creates under the operator's idempotency record."""

import logging
from typing import Any
from uuid import UUID

import httpx
import pytest
from api_support import OWNER, seed_request, sign_in_as

from tadas.om.opcontext import OperatorRole
from tadas.services.api.container import AppContainer

PASSWORD = "pw-1234"
OPERATOR_LOG = "tadas.om.tenancy.impl.operator"


async def admit(
    client: httpx.AsyncClient, container: AppContainer, role: OperatorRole, email: str
) -> dict[str, str]:
    """An operator's headers: the person's own sign-in, on the allowlist with `role`."""
    slug = email.split("@")[0]
    await container.managers.tenancy.bootstrap(
        seed_request(), slug.title(), slug, email, PASSWORD, "Op", operator_role=role
    )
    login = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}", "X-App": "cli"}


@pytest.fixture
async def writer(client: httpx.AsyncClient, container: AppContainer) -> dict[str, str]:
    return await admit(client, container, OperatorRole.WRITE, "root@example.test")


@pytest.fixture
async def reader(client: httpx.AsyncClient, container: AppContainer) -> dict[str, str]:
    return await admit(client, container, OperatorRole.READ, "sup@example.test")


@pytest.fixture
async def org_id(client: httpx.AsyncClient, owner: dict[str, str]) -> str:
    """The seeded tenant, with two open tasks and one done, over its owner."""
    current = await client.get("/v1/orgs/current", headers=owner)
    for title in ("first", "second", "third"):
        created = await client.post("/v1/tasks", headers=owner, json={"title": title})
        assert created.status_code == 201, created.text
        if title == "third":
            done = await client.patch(
                f"/v1/tasks/{created.json()['id']}",
                headers=owner,
                json={"status": "done", "version": 1},
            )
            assert done.status_code == 200, done.text
    return current.json()["id"]


def routes(org_id: str) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Every operator route, the permission it asks for, and a request that
    passes its validation. The write ones name a fresh slug and email, so the
    write operator's call lands."""
    return [
        ("read", "GET", "/v1/admin/size", {}),
        ("read", "GET", "/v1/admin/orgs", {}),
        ("read", "GET", f"/v1/admin/orgs/{org_id}", {}),
        ("read", "GET", f"/v1/admin/orgs/{org_id}/members", {}),
        ("read", "GET", f"/v1/admin/orgs/{org_id}/tasks", {}),
        ("read", "GET", f"/v1/admin/orgs/{org_id}/events", {}),
        (
            "write",
            "POST",
            "/v1/admin/orgs",
            {
                "json": {
                    "name": "Other",
                    "slug": "other",
                    "owner_email": "otto@example.test",
                    "owner_password": PASSWORD,
                    "owner_name": "Otto",
                }
            },
        ),
        (
            "write",
            "POST",
            f"/v1/admin/orgs/{org_id}/members",
            {
                "json": {
                    "email": "bob@example.test",
                    "password": PASSWORD,
                    "display_name": "Bob",
                    "role": "member",
                }
            },
        ),
        ("write", "DELETE", f"/v1/admin/orgs/{org_id}", {}),
    ]


async def test_every_route_is_held_to_its_permission(
    client: httpx.AsyncClient,
    owner: dict[str, str],
    reader: dict[str, str],
    writer: dict[str, str],
    org_id: str,
) -> None:
    """A read operator passes every read and is refused every write with the
    `not_authorized` shape a viewer's write gets; a write operator passes
    both; a tenant session is not an operator at all."""
    for permission, method, path, extra in routes(org_id):
        as_tenant = await client.request(method, path, headers=owner, **extra)
        assert as_tenant.status_code == 401, f"{method} {path}: {as_tenant.text}"
        as_reader = await client.request(method, path, headers=reader, **extra)
        if permission == "read":
            assert as_reader.status_code == 200, f"{method} {path}: {as_reader.text}"
        else:
            assert as_reader.status_code == 403, f"{method} {path}: {as_reader.text}"
            assert as_reader.json()["error"]["code"] == "not_authorized"
            assert as_reader.json()["error"]["message"] == "operator lacks write"
        as_writer = await client.request(method, path, headers=writer, **extra)
        expected = 201 if method == "POST" else 200
        assert as_writer.status_code == expected, f"{method} {path}: {as_writer.text}"
    # The refused writes landed nothing: the org is only now deleted, by the writer.
    orgs = {o["slug"]: o for o in (await client.get("/v1/admin/orgs", headers=reader)).json()}
    assert orgs["acme"]["deleted_at"] is not None and orgs["other"]["deleted_at"] is None


async def test_an_operator_reads_one_tenant_and_leaves_a_trail(
    client: httpx.AsyncClient,
    container: AppContainer,
    reader: dict[str, str],
    org_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=OPERATOR_LOG):
        org = await client.get(f"/v1/admin/orgs/{org_id}", headers=reader)
        assert org.status_code == 200 and org.json()["slug"] == "acme", org.text
        unknown = await client.get(f"/v1/admin/orgs/{UUID(int=7)}", headers=reader)
        assert unknown.status_code == 404

        members = await client.get(f"/v1/admin/orgs/{org_id}/members", headers=reader)
        assert members.status_code == 200, members.text
        assert [m["email"] for m in members.json()["items"]] == [OWNER["email"]]
        assert members.json()["next_cursor"] is None

        opened = await client.get(
            f"/v1/admin/orgs/{org_id}/tasks", headers=reader, params={"limit": 1}
        )
        assert opened.status_code == 200, opened.text
        assert [t["title"] for t in opened.json()["items"]] == ["second"]  # the top of the list
        cursor = opened.json()["next_cursor"]
        assert cursor is not None
        rest = await client.get(
            f"/v1/admin/orgs/{org_id}/tasks", headers=reader, params={"cursor": cursor}
        )
        assert [t["title"] for t in rest.json()["items"]] == ["first"]
        assert rest.json()["next_cursor"] is None
        done = await client.get(
            f"/v1/admin/orgs/{org_id}/tasks", headers=reader, params={"status": "done"}
        )
        assert [t["title"] for t in done.json()["items"]] == ["third"]
        crossed = await client.get(
            f"/v1/admin/orgs/{org_id}/tasks",
            headers=reader,
            params={"status": "done", "cursor": cursor},
        )
        assert crossed.status_code == 422, crossed.text

        events = await client.get(f"/v1/admin/orgs/{org_id}/events", headers=reader)
        assert events.status_code == 200, events.text
        assert [e["seq"] for e in events.json()] == [1, 2, 3, 4]
        assert {e["kind"] for e in events.json()} == {
            "tasks.task.created",
            "tasks.task.updated",
        }
        later = await client.get(
            f"/v1/admin/orgs/{org_id}/events", headers=reader, params={"after_seq": 3}
        )
        assert [e["seq"] for e in later.json()] == [4]

    trail = [r.getMessage() for r in caplog.records if r.name == OPERATOR_LOG]
    # Seven reads landed; the cursor of the other list was refused before any.
    assert len(trail) == 7 and all(org_id in line for line in trail)
    assert not any("example.test" in line or "first" in line for line in trail)


async def test_the_size_is_what_the_first_responder_reads(
    client: httpx.AsyncClient, reader: dict[str, str], org_id: str
) -> None:
    size = await client.get("/v1/admin/size", headers=reader)
    assert size.status_code == 200, size.text
    body = size.json()
    # The seeded tenant and the operator's own; their two owners.
    assert (body["tenants"], body["users"]) == (2, 2)
    assert (body["tasks_last_24h"], body["events_last_24h"]) == (3, 4)
    assert body["since"].endswith("Z") or "+" in body["since"]


async def test_the_creates_run_under_the_operators_idempotency_record(
    client: httpx.AsyncClient, writer: dict[str, str]
) -> None:
    """A creating route of the operator plane carries a key like every other:
    the retry replays the org the first call created, a reused key with
    another body is refused, and the org's owner signs in like any owner."""
    body = {
        "name": "Other",
        "slug": "other",
        "owner_email": "otto@example.test",
        "owner_password": PASSWORD,
        "owner_name": "Otto",
    }
    headers = {**writer, "Idempotency-Key": "org-1"}
    first = await client.post("/v1/admin/orgs", headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert first.json()["slug"] == "other" and first.json()["deleted_at"] is None
    second = await client.post("/v1/admin/orgs", headers=headers, json=body)
    assert second.status_code == 201 and second.headers["Idempotent-Replayed"] == "true"
    assert second.json() == first.json()
    reused = await client.post("/v1/admin/orgs", headers=headers, json={**body, "slug": "another"})
    assert reused.status_code == 422, reused.text
    taken = await client.post(
        "/v1/admin/orgs", headers={**writer, "Idempotency-Key": "org-2"}, json=body
    )
    assert taken.status_code == 409, taken.text
    assert taken.json()["error"]["code"] == "conflict"
    org_id = UUID(first.json()["id"])

    member = {
        "email": "bob@example.test",
        "password": PASSWORD,
        "display_name": "Bob",
        "role": "admin",
    }
    headers = {**writer, "Idempotency-Key": "member-1"}
    added = await client.post(f"/v1/admin/orgs/{org_id}/members", headers=headers, json=member)
    assert added.status_code == 201, added.text
    assert added.json()["email"] == "bob@example.test"
    replayed = await client.post(f"/v1/admin/orgs/{org_id}/members", headers=headers, json=member)
    assert replayed.status_code == 201 and replayed.headers["Idempotent-Replayed"] == "true"
    assert replayed.json() == added.json()
    as_owner = await client.post(
        f"/v1/admin/orgs/{org_id}/members",
        headers={**writer, "Idempotency-Key": "member-2"},
        json={**member, "email": "cat@example.test", "role": "owner"},
    )
    assert as_owner.status_code == 422, as_owner.text
    blank = await client.post(
        f"/v1/admin/orgs/{org_id}/members", headers=writer, json={**member, "email": ""}
    )
    assert blank.status_code == 422, blank.text

    # Both people sign into the org the operator made, with the roles given.
    otto = await sign_in_as(client, "otto@example.test", PASSWORD, org_id)
    assert (await client.get("/v1/me", headers=otto)).json()["role"] == "owner"
    bob = await sign_in_as(client, "bob@example.test", PASSWORD, org_id)
    assert (await client.get("/v1/me", headers=bob)).json()["role"] == "admin"
    listed = await client.get(f"/v1/admin/orgs/{org_id}/members", headers=writer)
    assert sorted(m["email"] for m in listed.json()["items"]) == [
        "bob@example.test",
        "otto@example.test",
    ]
