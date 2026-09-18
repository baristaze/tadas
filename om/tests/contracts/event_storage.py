import asyncio

import pytest

from tadas.om.base import new_id, utcnow
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.types.event import Event


def make_event(action: str = "created") -> Event:
    return Event(
        id=new_id(),
        entity="task",
        entity_id=new_id(),
        action=action,
        produced_at=utcnow(),
        idempotency_key=new_id(),
        actor_id=new_id(),
        request_id=new_id(),
    )


class EventStorageContract:
    @pytest.fixture
    def storage(self) -> EventStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_append_assigns_a_dense_sequence_per_tenant(
        self, storage: EventStorageInterface
    ) -> None:
        org_a, org_b = new_id(), new_id()
        appended = [await storage.append(org_a, make_event()) for _ in range(3)]
        assert [e.seq for e in appended] == [1, 2, 3]
        elsewhere = await storage.append(org_b, make_event())
        assert elsewhere.seq == 1
        first = appended[0]
        assert first == make_event().model_copy(
            update={
                "id": first.id,
                "seq": 1,
                "entity_id": first.entity_id,
                "produced_at": first.produced_at,
                "idempotency_key": first.idempotency_key,
                "actor_id": first.actor_id,
                "request_id": first.request_id,
            }
        )
        assert await storage.read_after(org_a, 0, 10) == appended
        assert await storage.read_after(org_a, 2, 10) == appended[2:]
        assert await storage.read_after(org_a, 3, 10) == []
        assert await storage.read_after(org_a, 0, 2) == appended[:2]
        assert await storage.read_after(org_b, 0, 10) == [elsewhere]
        assert await storage.read_after(new_id(), 0, 10) == []

    async def test_concurrent_appends_never_share_or_skip_a_seq(
        self, storage: EventStorageInterface
    ) -> None:
        org = new_id()
        appended = await asyncio.gather(*(storage.append(org, make_event()) for _ in range(10)))
        assert sorted(e.seq for e in appended) == list(range(1, 11))
        assert [e.seq for e in await storage.read_after(org, 0, 20)] == list(range(1, 11))
