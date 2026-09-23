"""The memberships of the signed-in person, the switch between tenants, and
a team org of one's own, over the whole API in-process."""

from uuid import UUID

import httpx
import pytest
from api_support import OWNER, enrol_operator, seed_request, sign_in_as

from tadas.om.opcontext import OperatorRole, Role
from tadas.services.api.container import AppContainer

DEE = {"email": "dee@example.test", "display_name": "Dee"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-App": "portal"}


async def enter(client: httpx.AsyncClient, token: str, org_id: str) -> str:
    """The exchange: the credential presented, the org chosen, the session's token back."""
    session = await client.post("/v1/auth/sessions", json={"org_id": org_id}, headers=bearer(token))
    assert session.status_code == 200, session.text
    return session.json()["token"]


async def two_orgs(client: httpx.AsyncClient, container: AppContainer) -> tuple[str, str]:
    """Ann owns Acme and is a member of Beta; returns both org ids."""
    tenancy = container.managers.tenancy
    _, acme = await tenancy.bootstrap(seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"])
    await tenancy.bootstrap(seed_request(), "Beta", "beta", "bea@example.test", "Bea")
    await tenancy.add_member(seed_request(), "beta", OWNER["email"], OWNER["name"], Role.MEMBER)
    beta = await container.storage.get_tenancy_storage().read_org_by_slug("beta")
    assert beta is not None
    return str(acme.id), str(beta.id)


async def test_the_memberships_are_read_with_the_sign_in_or_a_session(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    acme, beta = await two_orgs(client, container)
    login = await client.post("/v1/auth/dev-sign-in", json={"email": OWNER["email"]})
    token = login.json()["token"]
    by_login = await client.get("/v1/auth/memberships", headers=bearer(token))
    assert by_login.status_code == 200, by_login.text
    places = by_login.json()["items"]
    assert {m["org"]["id"] for m in places if m["org"]["kind"] == "team"} == {acme, beta}
    assert [m["org"]["kind"] for m in places].count("personal") == 1
    assert by_login.json()["next_cursor"] is None
    # The same list, with the one bearer a signed-in app holds.
    session = await enter(client, token, acme)
    by_session = await client.get("/v1/auth/memberships", headers=bearer(session))
    assert by_session.json() == by_login.json()
    # A page at a time.
    first = await client.get("/v1/auth/memberships", headers=bearer(session), params={"limit": 2})
    cursor = first.json()["next_cursor"]
    assert len(first.json()["items"]) == 2 and cursor is not None
    rest = await client.get(
        "/v1/auth/memberships", headers=bearer(session), params={"limit": 2, "cursor": cursor}
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
    held = await sign_in_as(client, OWNER["email"], UUID(acme))
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
    ops = next(m["org"]["id"] for m in orgs.json()["items"] if m["org"]["kind"] == "team")
    session = await client.post("/v1/auth/sessions", headers=admin, json={"org_id": ops})
    assert session.status_code == 200, session.text
    refused = await client.get("/v1/admin/orgs", headers=bearer(session.json()["token"]))
    assert refused.status_code == 401, refused.text
    admitted = await client.get("/v1/admin/orgs", headers=admin)
    assert admitted.status_code == 200, admitted.text


# A team org of one's own.


async def signed_up_session(client: httpx.AsyncClient) -> dict[str, str]:
    """Dee signs in for the first time and enters her personal org; the
    tenant headers back."""
    body = (await client.post("/v1/auth/dev-sign-in", json=DEE)).json()
    return bearer(await enter(client, body["token"], body["memberships"][0]["org"]["id"]))


async def test_a_person_creates_a_team_org_and_switches_to_it(
    client: httpx.AsyncClient,
) -> None:
    home = await signed_up_session(client)
    created = await client.post(
        "/v1/orgs", json={"name": "Dee's Bakery"}, headers=home | {"Idempotency-Key": "o1"}
    )
    assert created.status_code == 201, created.text
    place = created.json()
    assert place["role"] == "owner" and place["user"]["display_name"] == "Dee"
    assert place["org"]["kind"] == "team" and place["org"]["name"] == "Dee's Bakery"
    assert place["org"]["slug"].startswith("dee-s-bakery-")
    # The switch is the exchange, presented with the session she holds.
    token = home["Authorization"].removeprefix("Bearer ")
    there = await enter(client, token, place["org"]["id"])
    me = (await client.get("/v1/me", headers=bearer(there))).json()
    assert me["org"]["id"] == place["org"]["id"] and me["role"] == "owner"
    assert (await client.get("/v1/me", headers=home)).status_code == 401, "the switch ended it"
    places = (await client.get("/v1/auth/memberships", headers=bearer(there))).json()["items"]
    assert sorted(m["org"]["kind"] for m in places) == ["personal", "team"]


async def test_a_retried_create_makes_one_org(client: httpx.AsyncClient) -> None:
    home = await signed_up_session(client)
    body = {"name": "Cafe", "slug": "cafe"}
    first = await client.post("/v1/orgs", json=body, headers=home | {"Idempotency-Key": "o1"})
    again = await client.post("/v1/orgs", json=body, headers=home | {"Idempotency-Key": "o1"})
    assert first.status_code == again.status_code == 201, again.text
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert again.json()["org"]["id"] == first.json()["org"]["id"]
    assert first.json()["org"]["slug"] == "cafe"
    taken = await client.post("/v1/orgs", json=body, headers=home | {"Idempotency-Key": "o2"})
    assert taken.status_code == 409, taken.text


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "Cafe", "slug": "Not A Slug"}, {}])
async def test_a_malformed_org_is_refused(client: httpx.AsyncClient, body: dict[str, str]) -> None:
    home = await signed_up_session(client)
    refused = await client.post("/v1/orgs", json=body, headers=home | {"Idempotency-Key": "o1"})
    assert refused.status_code == 422, refused.text


async def test_an_api_key_creates_no_org(client: httpx.AsyncClient) -> None:
    home = await signed_up_session(client)
    key = await client.post(
        "/v1/api-keys",
        headers=home | {"Idempotency-Key": "k1"},
        json={"name": "ci", "role": "owner"},
    )
    refused = await client.post(
        "/v1/orgs", json={"name": "Bots"}, headers=bearer(key.json()["key"])
    )
    assert refused.status_code == 403, refused.text
    assert (await client.post("/v1/orgs", json={"name": "Nobody"})).status_code == 401


async def test_the_person_of_a_personal_org_stays_in_it(
    client: httpx.AsyncClient, container: AppContainer
) -> None:
    home = await signed_up_session(client)
    me = (await client.get("/v1/me", headers=home)).json()
    # The seeding puts a second owner in her personal org; nothing refuses it.
    tenancy = container.managers.tenancy
    org = await container.storage.get_tenancy_storage().read_org(UUID(me["org"]["id"]))
    assert org is not None
    await tenancy.add_member(seed_request(), org.slug, "eve@example.test", "Eve", Role.OWNER)
    eve = await sign_in_as(client, "eve@example.test", org.id)
    # Even an owner of it neither removes her nor changes her role.
    for refused in (
        await client.delete(f"/v1/memberships/{me['user']['id']}", headers=eve),
        await client.patch(
            f"/v1/memberships/{me['user']['id']}", headers=eve, json={"role": "viewer"}
        ),
    ):
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "personal_org_fixed"
    assert (await client.get("/v1/me", headers=home)).json()["role"] == "owner"
