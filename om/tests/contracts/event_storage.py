from uuid import UUID

import pytest

from contracts.racing import race
from tadas.om.base import new_id, utcnow
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event


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

    async def test_append_is_idempotent_on_the_id(self, storage: EventStorageInterface) -> None:
        # The outbox relay appends under the row's id; relaying twice appends once.
        org = new_id()
        event = make_event(org)
        first = await storage.append_event(org, event)
        again = await storage.append_event(org, event.model_copy(update={"kind": "ignored"}))
        assert again == first and first.seq == 1
        assert [e.seq for e in await storage.read_after(org, 0, 10)] == [1]

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
