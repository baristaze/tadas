"""The realtime service hears every change on the bus and ends the sockets a
revocation names: the one the session or the api key opened, or every one
of a user whose membership ended, and no other."""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from api_support import OWNER, add_member, build_container, seed_request

from tadas.infra.topics import EntityChangedPayload, Topics
from tadas.om.base import new_id, utcnow
from tadas.om.opcontext import OpContext, Role
from tadas.services.api.services.realtime import CREDENTIAL_REVOKED, MEMBERSHIP_ENDED


async def test_a_revocation_ends_the_sockets_it_names_and_no_other(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    tenancy = container.managers.tenancy
    _, org = await tenancy.bootstrap(
        seed_request(), "Acme", "acme", OWNER["email"], OWNER["password"], OWNER["name"]
    )
    bob = await add_member(container, org.id, "bob@example.test", "pw-1234", Role.MEMBER)

    async def session_of(email: str) -> str:
        login = await tenancy.login(seed_request(), email, "pw-1234")
        identity = await tenancy.authenticate_login(seed_request(), login.token)
        return (await tenancy.exchange_login(identity, org.id)).token

    async def socket_ctx(credential: str) -> OpContext:
        """The context a socket opened on `credential` runs as."""
        ctx = await tenancy.authenticate(seed_request(), credential)
        ticket = await tenancy.issue_ticket(ctx)
        return (await tenancy.redeem_ticket(seed_request(), ticket.ticket)).ctx

    ann_first = await socket_ctx(await session_of(OWNER["email"]))
    ann_second = await socket_ctx(await session_of(OWNER["email"]))
    bob_first = await socket_ctx(await session_of("bob@example.test"))
    bob_second = await socket_ctx(await session_of("bob@example.test"))
    owner = await tenancy.authenticate(seed_request(), await session_of(OWNER["email"]))
    key = await tenancy.create_api_key(owner, "ci", Role.MEMBER)
    from_key = await socket_ctx(key.key)

    realtime = container.services.get_realtime_service()
    ended: dict[str, list[str]] = {}
    detach: dict[str, Callable[[], None]] = {}
    for name, ctx in {
        "ann_first": ann_first,
        "ann_second": ann_second,
        "bob_first": bob_first,
        "bob_second": bob_second,
        "from_key": from_key,
    }.items():
        ended[name] = []
        detach[name] = realtime.attach(ctx, ended[name].append)
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
    await announce("tenancy.session.revoked", ann_first.credential_id, org_id=new_id())
    await announce("tasks.task.updated", ann_first.credential_id)
    await announce("tenancy.membership.updated", bob.id)
    assert all(reasons == [] for reasons in ended.values())

    await announce("tenancy.session.revoked", ann_first.credential_id)
    assert ended["ann_first"] == [CREDENTIAL_REVOKED]
    assert ended["ann_second"] == [] and ended["from_key"] == []

    await announce("tenancy.api_key.deleted", from_key.credential_id)
    assert ended["from_key"] == [CREDENTIAL_REVOKED]

    # The member's membership ended: every socket of theirs still attached ends.
    await announce("tenancy.user.deleted", bob.id)
    assert ended["bob_first"] == [MEMBERSHIP_ENDED]
    assert ended["bob_second"] == []  # detached before the frame
    assert ended["ann_second"] == []  # another user
