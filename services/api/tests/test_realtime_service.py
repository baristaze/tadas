"""The realtime service hears every change on the bus and ends the sockets a
revocation names: the one the session or the api key opened, every one of a
user whose membership ended or whose role changed, or every one of a deleted
org, and no other. It re-checks a socket's credential when asked."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from api_support import OWNER, add_member, build_container, on_plan, seed_request

from tadas.infra.topics import EntityChangedPayload, Topics
from tadas.om.base import new_id, utcnow
from tadas.om.billing.types.plan import Plan
from tadas.om.opcontext import Role
from tadas.om.tenancy.rules import hash_token
from tadas.om.tenancy.types.socket_ticket import SocketPrincipal
from tadas.services.api.container import AppContainer
from tadas.services.api.services.realtime import (
    CREDENTIAL_REVOKED,
    MEMBERSHIP_ENDED,
    RIGHTS_CHANGED,
)


async def test_a_revocation_ends_the_sockets_it_names_and_no_other(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    tenancy = container.managers.tenancy
    _, org = await tenancy.bootstrap(seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"])
    await on_plan(container, org.id, Plan.TEAM)
    bob = await add_member(container, org.id, "bob@example.test", Role.MEMBER)

    async def session_of(email: str) -> str:
        login = await tenancy.dev_sign_in(seed_request(), email)
        identity = await tenancy.authenticate_login(seed_request(), login.token)
        return (await tenancy.exchange_login(identity, org.id)).token

    async def socket_principal(credential: str) -> SocketPrincipal:
        """The principal a socket opened on `credential` runs as."""
        ctx = await tenancy.authenticate(seed_request(), credential)
        ticket = await tenancy.issue_ticket(ctx)
        return await tenancy.redeem_ticket(seed_request(), ticket.ticket)

    ann_first = await socket_principal(await session_of(OWNER["email"]))
    ann_second = await socket_principal(await session_of(OWNER["email"]))
    bob_first = await socket_principal(await session_of("bob@example.test"))
    bob_second = await socket_principal(await session_of("bob@example.test"))
    owner = await tenancy.authenticate(seed_request(), await session_of(OWNER["email"]))
    key = await tenancy.create_api_key(owner, "ci", Role.MEMBER)
    from_key = await socket_principal(key.key)

    realtime = container.services.get_realtime_service()
    ended: dict[str, list[str]] = {}
    detach: dict[str, Callable[[], None]] = {}
    for name, principal in {
        "ann_first": ann_first,
        "ann_second": ann_second,
        "bob_first": bob_first,
        "bob_second": bob_second,
        "from_key": from_key,
    }.items():
        ended[name] = []
        detach[name] = realtime.attach(principal, ended[name].append)
    detach["bob_second"]()

    topics = container.infra.get_topics()

    async def announce(kind: str, target_id: UUID, org_id: UUID = org.id) -> None:
        await topics.publish(
            Topics.ENTITY_CHANGED,
            EntityChangedPayload(
                idempotency_key=new_id(),
                produced_at=utcnow(),
                org_id=org_id,
                kind=kind,
                target_id=target_id,
                seq=1,
                actor_id=owner.user_id,
            ),
        )

    # Another tenant's frame with the same ids ends nothing; nor does a change of another kind.
    await announce("tenancy.session.revoked", ann_first.ctx.credential_id, org_id=new_id())
    await announce("tasks.task.updated", ann_first.ctx.credential_id)
    # A membership's change names the membership, never the user.
    await announce("tenancy.membership.updated", bob.id)
    assert all(reasons == [] for reasons in ended.values())

    await announce("tenancy.session.revoked", ann_first.ctx.credential_id)
    assert ended["ann_first"] == [CREDENTIAL_REVOKED]
    assert ended["ann_second"] == [] and ended["from_key"] == []

    await announce("tenancy.api_key.deleted", from_key.ctx.credential_id)
    assert ended["from_key"] == [CREDENTIAL_REVOKED]

    # The member's membership ended: every socket of theirs still attached ends.
    await announce("tenancy.user.deleted", bob.id)
    assert ended["bob_first"] == [MEMBERSHIP_ENDED]
    assert ended["bob_second"] == []  # detached before the frame
    assert ended["ann_second"] == []  # another user

    # The org was deleted: every socket of the tenant still attached ends, and
    # another tenant's deletion ends none of them.
    other_org = new_id()
    await announce("tenancy.org.deleted", other_org, org_id=other_org)
    assert ended["ann_second"] == []
    await announce("tenancy.org.deleted", org.id)
    assert ended["ann_second"] == [MEMBERSHIP_ENDED]
    assert ended["bob_second"] == []  # detached before the frame


async def session_of(container: AppContainer, org_id: UUID, email: str) -> str:
    tenancy = container.managers.tenancy
    login = await tenancy.dev_sign_in(seed_request(), email)
    identity = await tenancy.authenticate_login(seed_request(), login.token)
    return (await tenancy.exchange_login(identity, org_id)).token


async def principal_of(container: AppContainer, credential: str) -> SocketPrincipal:
    """What redeeming a ticket minted on `credential` yields, as the gateway gets it."""
    tenancy = container.managers.tenancy
    ctx = await tenancy.authenticate(seed_request(), credential)
    ticket = await tenancy.issue_ticket(ctx)
    return await tenancy.redeem_ticket(seed_request(), ticket.ticket)


async def test_a_change_of_role_ends_the_members_sockets_to_reconnect(tmp_path: Path) -> None:
    """The bus names the membership whose role changed. Every socket built
    from it ends with the reason that asks the client to reconnect, the
    member's api key's among them, since a key's role is capped by the
    member's; another member's socket stays."""
    container = build_container(tmp_path)
    tenancy = container.managers.tenancy
    _, org = await tenancy.bootstrap(seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"])
    await on_plan(container, org.id, Plan.TEAM)
    bob = await add_member(container, org.id, "bob@example.test", Role.ADMIN)
    owner = await tenancy.authenticate(
        seed_request(), await session_of(container, org.id, OWNER["email"])
    )
    bob_session = await session_of(container, org.id, "bob@example.test")
    bob_ctx = await tenancy.authenticate(seed_request(), bob_session)
    bob_key = await tenancy.create_api_key(bob_ctx, "ci", Role.MEMBER)
    realtime = container.services.get_realtime_service()
    ended: dict[str, list[str]] = {"bob": [], "bob_key": [], "ann": []}
    realtime.attach(await principal_of(container, bob_session), ended["bob"].append)
    realtime.attach(await principal_of(container, bob_key.key), ended["bob_key"].append)
    realtime.attach(
        await principal_of(container, await session_of(container, org.id, OWNER["email"])),
        ended["ann"].append,
    )

    await tenancy.update_membership_role(owner, bob.id, Role.MEMBER)

    assert ended == {"bob": [RIGHTS_CHANGED], "bob_key": [RIGHTS_CHANGED], "ann": []}


async def test_the_recheck_answers_what_the_redemption_would(tmp_path: Path) -> None:
    """None while the credential holds as it did; the change of role; the
    refusal once the session is revoked, idle, or the key deleted. Each
    change is made in storage alone, as when the bus lost its message."""
    container = build_container(tmp_path)
    tenancy = container.managers.tenancy
    storage = container.storage.get_tenancy_storage()
    _, org = await tenancy.bootstrap(seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"])
    await on_plan(container, org.id, Plan.TEAM)
    bob = await add_member(container, org.id, "bob@example.test", Role.ADMIN)
    realtime = container.services.get_realtime_service()

    token = await session_of(container, org.id, OWNER["email"])
    principal = await principal_of(container, token)
    assert await realtime.recheck(principal) is None

    # Revoked in storage, with no message on any bus.
    found = await storage.read_session_by_digest(hash_token(token))
    assert found is not None
    _, session = found
    await storage.write_session(org.id, session.model_copy(update={"revoked_at": utcnow()}))
    assert await realtime.recheck(principal) == "not_authenticated"

    # A session idle past its lifetime is refused as a request would be.
    idle_token = await session_of(container, org.id, OWNER["email"])
    idle = await principal_of(container, idle_token)
    found = await storage.read_session_by_digest(hash_token(idle_token))
    assert found is not None
    _, session = found
    long_ago = utcnow() - timedelta(days=1)
    await storage.write_session(org.id, session.model_copy(update={"last_seen_at": long_ago}))
    assert await realtime.recheck(idle) == "not_authenticated"

    # The role, changed in storage alone.
    bob_principal = await principal_of(
        container, await session_of(container, org.id, "bob@example.test")
    )
    membership = await storage.read_membership_for_user(org.id, bob.id)
    assert membership is not None
    await storage.write_membership(org.id, membership.model_copy(update={"role": Role.MEMBER}), ())
    assert await realtime.recheck(bob_principal) == RIGHTS_CHANGED

    owner = await tenancy.authenticate(
        seed_request(), await session_of(container, org.id, OWNER["email"])
    )
    key = await tenancy.create_api_key(owner, "ci", Role.MEMBER)
    from_key = await principal_of(container, key.key)
    assert await realtime.recheck(from_key) is None
    await tenancy.revoke_api_key(owner, key.api_key.id)
    assert await realtime.recheck(from_key) == "not_authenticated"


async def test_the_recheck_is_not_a_use_of_the_session(tmp_path: Path) -> None:
    """A recheck asks; it does not count as a use. An open socket never keeps
    an idle session alive, so a tab left open is signed out at the idle
    lifetime exactly as a tab left closed is."""
    container = build_container(tmp_path)
    tenancy = container.managers.tenancy
    storage = container.storage.get_tenancy_storage()
    _, org = await tenancy.bootstrap(seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"])
    token = await session_of(container, org.id, OWNER["email"])
    principal = await principal_of(container, token)
    found = await storage.read_session_by_digest(hash_token(token))
    assert found is not None
    _, session = found
    seen = utcnow() - timedelta(hours=1)
    await storage.write_session(org.id, session.model_copy(update={"last_seen_at": seen}))

    assert await container.services.get_realtime_service().recheck(principal) is None

    found = await storage.read_session_by_digest(hash_token(token))
    assert found is not None
    assert found[1].last_seen_at == seen
