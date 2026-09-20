import pytest
from contracts.event_storage import EventStorageContract, make_event

from tadas.om.base import new_id
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.storage.impl.postgres import EventStoragePostgresImpl
from tadas.om.events.storage.tables.event_cursors import EventCursors
from tadas.om.storage.impl.pg_base import SessionFactory, set_scope
from tadas.om.storage.roles import DatabaseRole

pytestmark = pytest.mark.integration


class TestEventStoragePostgres(EventStorageContract):
    @pytest.fixture
    def storage(self, pg_sessions: dict[DatabaseRole, SessionFactory]) -> EventStorageInterface:
        return EventStoragePostgresImpl(pg_sessions)

    async def test_the_cursor_row_is_the_head_and_the_next_number(
        self, storage: EventStorageInterface, pg_sessions: dict[DatabaseRole, SessionFactory]
    ) -> None:
        # The head is the cursor row, never a scan of the stream: a cursor set
        # ahead of the stream is what read_head says and what the append continues from.
        # Both transactions here reach around the impl, so each names the
        # tenant itself: a transaction that names none reads nothing and
        # writes nothing, which is the second fence holding.
        org = new_id()
        async with pg_sessions[DatabaseRole.ACTIVITY]() as session:
            await set_scope(session, org, None, None)
            session.add(EventCursors(org_id=org, head=7))
            await session.commit()
        assert await storage.read_head(org) == 7
        assert (await storage.append_event(org, make_event(org))).seq == 8
        async with pg_sessions[DatabaseRole.ACTIVITY]() as session:
            await set_scope(session, org, None, None)
            assert (await session.get(EventCursors, org)).head == 8  # type: ignore[union-attr]
