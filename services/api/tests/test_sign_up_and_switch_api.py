"""Sign-up, the memberships of the signed-in person, and the switch between
tenants, over the whole API in-process."""

from pathlib import Path
from uuid import UUID

import httpx
import pytest
from api_support import OWNER, build_container, enrol_operator, seed_request, sign_in_as
from httpx import ASGITransport

from tadas.om.opcontext import OperatorRole, Role
from tadas.om.tenancy.rules import email_digest
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer

DEE = {
    "email": "dee@example.test",
    "password": "long-enough",
    "display_name": "Dee",
    "org_name": "Dee's Bakery",
    "org_slug": "dees-bakery",
}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-App": "portal"}


async def enter(client: httpx.AsyncClient, token: str, org_id: str) -> str:
    """The exchange: the credential presented, the org chosen, the session's token back."""
    session = await client.post("/v1/auth/sessions", json={"org_id": org_id}, headers=bearer(token))
    assert session.status_code == 200, session.text
    return session.json()["token"]


async def test_sign_up_answers_as_a_sign_in_and_the_exchange_follows(
    client: httpx.AsyncClient,
) -> None:
    signed_up = await client.post("/v1/auth/signup", json=DEE)
    assert signed_up.status_code == 200, signed_up.text
    body = signed_up.json()
    assert body["token"].startswith("lgn_")
    [owner] = body["memberships"]
    assert owner["role"] == "owner"
    assert owner["org"]["name"] == "Dee's Bakery" and owner["org"]["slug"] == "dees-bakery"
    assert owner["user"]["email"] == "dee@example.test"
    session = await enter(client, body["token"], owner["org"]["id"])
    me = await client.get("/v1/me", headers=bearer(session))
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "owner" and me.json()["org"]["slug"] == "dees-bakery"
    # The password it chose signs in.
    login = await client.post(
        "/v1/auth/login", json={"email": DEE["email"], "password": DEE["password"]}
    )
    assert login.status_code == 200 and len(login.json()["memberships"]) == 1


async def test_sign_up_refuses_a_held_email_and_a_taken_slug(
    client: httpx.AsyncClient, owner: dict[str, str]
) -> None:
    held = await client.post("/v1/auth/signup", json=DEE | {"email": OWNER["email"]})
    assert held.status_code == 409, held.text
    assert held.json()["error"]["code"] == "conflict"
    taken = await client.post("/v1/auth/signup", json=DEE | {"org_slug": "acme"})
    assert taken.status_code == 409, taken.text
    login = await client.post(
        "/v1/auth/login", json={"email": DEE["email"], "password": DEE["password"]}
    )
    assert login.status_code == 401, "nothing landed"


@pytest.mark.parametrize(
    "change",
    [
        {"password": "short"},
        {"email": "nobody"},
        {"org_slug": "Not A Slug"},
        {"org_name": ""},
        {"extra": "field"},
    ],
)
async def test_a_malformed_sign_up_is_refused(
    client: httpx.AsyncClient, change: dict[str, str]
) -> None:
    refused = await client.post("/v1/auth/signup", json=DEE | change)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "validation_failed"


async def test_a_closed_sign_up_answers_as_no_route_would(tmp_path: Path) -> None:
    container = build_container(tmp_path, signup_enabled=False)
    app = create_app(container)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            closed = await client.post("/v1/auth/signup", json=DEE)
            missing = await client.post("/v1/auth/no-such-route", json=DEE)
            malformed = await client.post("/v1/auth/signup", json={})
            for answer in (closed, missing, malformed):
                assert answer.status_code == 404, answer.text
                error = answer.json()["error"]
                assert (error["code"], error["message"]) == ("not_found", "Not Found")
    storage = container.storage.get_tenancy_storage()
    assert await storage.read_identity_by_email_digest(email_digest(DEE["email"])) is None


async def test_sign_up_is_rate_limited_per_client(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    budget = container.rate_limits.of("signup").limit
    for index in range(budget):
        body = DEE | {"email": f"d{index}@example.test", "org_slug": f"bakery-{index}"}
        assert (await client.post("/v1/auth/signup", json=body)).status_code == 200
    rejected = await client.post("/v1/auth/signup", json=DEE)
    assert rejected.status_code == 429
    assert rejected.json()["error"]["code"] == "rate_limited"


async def two_orgs(client: httpx.AsyncClient, container: AppContainer) -> tuple[str, str]:
    """Ann owns Acme and is a member of Beta; returns both org ids."""
    tenancy = container.managers.tenancy
    _, acme = await tenancy.bootstrap(
        seed_request(), "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
    )
    await tenancy.bootstrap(seed_request(), "Beta", "beta", "bea@example.test", "pw-1234", "Bea")
    await tenancy.add_member(
        seed_request(), "beta", OWNER["email"], OWNER["password"], OWNER["name"], Role.MEMBER
    )
    beta = await container.storage.get_tenancy_storage().read_org_by_slug("beta")
    assert beta is not None
    return str(acme.id), str(beta.id)


async def test_the_memberships_are_read_with_the_sign_in_or_a_session(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    acme, beta = await two_orgs(client, container)
    login = await client.post(
        "/v1/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}
    )
    token = login.json()["token"]
    by_login = await client.get("/v1/auth/memberships", headers=bearer(token))
    assert by_login.status_code == 200, by_login.text
    assert {m["org"]["id"] for m in by_login.json()["items"]} == {acme, beta}
    assert by_login.json()["next_cursor"] is None
    # The same list, with the one bearer a signed-in app holds.
    session = await enter(client, token, acme)
    by_session = await client.get("/v1/auth/memberships", headers=bearer(session))
    assert by_session.json() == by_login.json()
    # A page at a time.
    first = await client.get("/v1/auth/memberships", headers=bearer(session), params={"limit": 1})
    cursor = first.json()["next_cursor"]
    assert len(first.json()["items"]) == 1 and cursor is not None
    rest = await client.get(
        "/v1/auth/memberships", headers=bearer(session), params={"limit": 1, "cursor": cursor}
    )
    assert first.json()["items"] + rest.json()["items"] == by_login.json()["items"]
    assert rest.json()["next_cursor"] is None
    # An api key is an agent's credential and proves no identity.
    key = await client.post(
        "/v1/api-keys",
        headers=bearer(session) | {"Idempotency-Key": "k1"},
        json={"name": "ci", "role": "member"},
    )
    refused = await client.get("/v1/auth/memberships", headers=bearer(key.json()["key"]))
    assert refused.status_code == 401
    assert (await client.get("/v1/auth/memberships")).status_code == 401


async def test_a_switch_ends_the_session_it_was_presented_with(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    acme, beta = await two_orgs(client, container)
    held = await sign_in_as(client, OWNER["email"], OWNER["password"], UUID(acme))
    held_token = held["Authorization"].removeprefix("Bearer ")
    switched = await enter(client, held_token, beta)
    me = await client.get("/v1/me", headers=bearer(switched))
    assert me.json()["org"]["id"] == beta and me.json()["role"] == "member"
    # The old session answers 401 now, on a tenant route and on the exchange.
    gone = await client.get("/v1/me", headers=held)
    assert gone.status_code == 401
    again = await client.post(
        "/v1/auth/sessions", json={"org_id": acme}, headers=bearer(held_token)
    )
    assert again.status_code == 401
    # Switching back works from the new session, and ends it in turn.
    back = await enter(client, switched, acme)
    assert (await client.get("/v1/me", headers=bearer(back))).json()["org"]["id"] == acme
    assert (await client.get("/v1/me", headers=bearer(switched))).status_code == 401


async def test_a_session_never_admits_an_operator(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    """A portal session proves the identity, and the identity is on the
    operator allowlist; the operator plane still refuses a tenant's
    credential, even one exchanged from a sign-in with a second factor."""
    admin, _ = await enrol_operator(client, container, "root@example.test", OperatorRole.WRITE)
    orgs = await client.get("/v1/auth/memberships", headers=admin)
    ops = orgs.json()["items"][0]["org"]["id"]
    session = await client.post("/v1/auth/sessions", headers=admin, json={"org_id": ops})
    assert session.status_code == 200, session.text
    refused = await client.get("/v1/admin/orgs", headers=bearer(session.json()["token"]))
    assert refused.status_code == 401, refused.text
    admitted = await client.get("/v1/admin/orgs", headers=admin)
    assert admitted.status_code == 200, admitted.text
