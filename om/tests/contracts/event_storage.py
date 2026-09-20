"""The event storage contract. The cases named in `CROSS_TENANT_CASES` are the
tenant fence's evidence: each one presents another tenant's identifier and
asserts that nothing is found and nothing changes. The negative control that
says what they catch is in `docs/runbooks/tenant-isolation.md`."""

from datetime import timedelta
from uuid import UUID

import pytest

from contracts.racing import race
from tadas.om.base import new_id, utcnow
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event
from tadas.om.exceptions import TenantMismatch

CROSS_TENANT_CASES: frozenset[str] = frozenset({"append_event", "read_after", "read_head"})
"""Every method of `EventStorageInterface` that takes a tenant has a case in
this module that presents another tenant's. `test_storage_exceptions.py` holds
the two sets to each other, so a new method arrives with its case."""


def make_event(org_id: UUID, kind: str = "tasks.task.created") -> Event:
    return Event(
        id=new_id(),
        org_id=org_id,
        kind=kind,
        target_id=new_id(),
        payload={"title": "t"},
        produced_at=utcnow(),
        actor_id=new_id(),
        request_id=new_id(),
        app="portal",
    )


class EventStorageContract:
    @pytest.fixture
    def storage(self) -> EventStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_append_assigns_a_dense_sequence_per_tenant(
        self, storage: EventStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        assert await storage.read_head(org_a) == 0
        appended = [await storage.append_event(org_a, make_event(org_a)) for _ in range(3)]
        assert [e.seq for e in appended] == [1, 2, 3]
        assert await storage.read_head(org_a) == 3
        elsewhere = await storage.append_event(org_b, make_event(org_b))
        assert elsewhere.seq == 1
        assert await storage.read_head(org_b) == 1
        first = appended[0]
        assert first == make_event(org_a).model_copy(
            update={
                "id": first.id,
                "seq": 1,
                "target_id": first.target_id,
                "produced_at": first.produced_at,
                "actor_id": first.actor_id,
                "request_id": first.request_id,
            }
        )
        assert first.payload == {"title": "t"}
        assert await storage.read_after(org_a, 0, 10) == appended
        assert await storage.read_after(org_a, 2, 10) == appended[2:]
        assert await storage.read_after(org_a, 3, 10) == []
        assert await storage.read_after(org_a, 0, 2) == appended[:2]
        assert await storage.read_after(org_b, 0, 10) == [elsewhere]
        assert await storage.read_after(new_id(), 0, 10) == []

    async def test_the_count_since_a_moment_spans_every_tenant(
        self, storage: EventStorageInterface
    ) -> None:
        """The traffic figure the platform's size reads: events produced at or
        after the cut, in whichever tenant's stream."""
        cut = utcnow()
        assert await storage.count_since(cut) == 0
        org_a, org_b = new_id(), new_id()
        await storage.append_event(org_a, make_event(org_a))
        await storage.append_event(org_b, make_event(org_b))
        earlier = make_event(org_b).model_copy(update={"produced_at": cut - timedelta(hours=25)})
        await storage.append_event(org_b, earlier)
        assert await storage.count_since(cut) == 2
        assert await storage.count_since(cut - timedelta(days=2)) == 3

    async def test_an_appended_event_names_its_own_tenant(
        self, storage: EventStorageInterface
    ) -> None:
        """The relay appends with no context and a client replays records, so
        the tenant is on the event and not beside it. An event that names
        another tenant is appended under the one the caller names."""
        org = new_id()
        appended = await storage.append_event(org, make_event(new_id()))
        assert appended.org_id == org
        assert [e.org_id for e in await storage.read_after(org, 0, 10)] == [org]

    async def test_append_is_idempotent_on_the_id(self, storage: EventStorageInterface) -> None:
        # The outbox relay appends under the row's id; relaying twice appends once.
        org = new_id()
        event = make_event(org)
        first = await storage.append_event(org, event)
        again = await storage.append_event(org, event.model_copy(update={"kind": "ignored"}))
        assert again == first and first.seq == 1
        assert [e.seq for e in await storage.read_after(org, 0, 10)] == [1]

    async def test_an_id_another_tenant_appended_is_never_written_over(
        self, storage: EventStorageInterface
    ) -> None:
        """The append is idempotent on the id, so a repeat returns what is
        stored. The id is unique across tenants, and a repeat from another
        tenant is not the same event: it is refused, and the stream it named
        stays as it was."""
        org_a, org_b = new_id(), new_id()
        event = make_event(org_a)
        appended = await storage.append_event(org_a, event)
        with pytest.raises(TenantMismatch):
            await storage.append_event(org_b, event.model_copy(update={"kind": "stolen"}))
        assert await storage.read_after(org_a, 0, 10) == [appended]
        assert await storage.read_after(org_b, 0, 10) == []
        # The refusal spends nothing: an id another tenant owns never moves
        # this tenant's cursor, so the next append here is still the first.
        assert await storage.read_head(org_b) == 0

    async def test_many_appends_never_share_or_skip_a_seq(
        self, storage: EventStorageInterface
    ) -> None:
        # N appends reach one tenant's cursor and leave with 1..N: no gap, no
        # duplicate, and the head is the last of them. See contracts/racing.py
        # for what each impl's run of this proves.
        org, n = new_id(), 32
        run = await race(*(storage.append_event(org, make_event(org)) for _ in range(n)))
        appended = run.outcomes
        assert sorted(e.seq for e in appended) == list(range(1, n + 1))
        assert [e.seq for e in await storage.read_after(org, 0, n * 2)] == list(range(1, n + 1))
        assert await storage.read_head(org) == n
        # The cursor the appends left is the one the next append takes from.
        assert (await storage.append_event(org, make_event(org))).seq == n + 1

    async def test_many_appends_keep_one_cursor_per_tenant(
        self, storage: EventStorageInterface
    ) -> None:
        # Two tenants appending at once never see each other's numbers.
        org_a, org_b, n = new_id(), new_id(), 16
        run = await race(
            *(storage.append_event(org, make_event(org)) for org in (org_a, org_b) * n)
        )
        appended = run.outcomes
        assert sorted(e.seq for e in appended[0::2]) == list(range(1, n + 1))
        assert sorted(e.seq for e in appended[1::2]) == list(range(1, n + 1))
        assert await storage.read_head(org_a) == n
        assert await storage.read_head(org_b) == n

    async def test_a_retried_append_consumes_no_seq(self, storage: EventStorageInterface) -> None:
        # The retry of an appended id rolls back, and the number it took goes
        # back with it: the next event is 2, not 3.
        org = new_id()
        event = make_event(org)
        await storage.append_event(org, event)
        await storage.append_event(org, event)
        assert (await storage.append_event(org, make_event(org))).seq == 2
        assert await storage.read_head(org) == 2
