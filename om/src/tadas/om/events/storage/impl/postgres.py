from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from tadas.om.base import EMPTY_UUID
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.storage.tables.event_cursors import EventCursors
from tadas.om.events.storage.tables.events import Events
from tadas.om.events.types.event import Event
from tadas.om.exceptions import TenantMismatch, UniqueKeyTaken
from tadas.om.storage.impl.pg_base import PgStorageBase, violated_constraint
from tadas.om.storage.utils.translation import to_model, to_values


class EventStoragePostgresImpl(PgStorageBase, EventStorageInterface):
    async def append_event(self, org_id: UUID, event: Event) -> Event:
        # The next number comes from the tenant's cursor row, `head + 1` under
        # the row's lock, in the same transaction as the event: two appends to
        # one tenant queue on the lock and each leaves with the next number. The
        # first append inserts the row. Never `MAX(seq) + 1` and a retry on the
        # unique index: on a busy tenant that loop is a Conflict generator.
        take_next = (
            pg_insert(EventCursors)
            .values(org_id=org_id, head=1)
            .on_conflict_do_update(
                index_elements=[EventCursors.org_id],
                set_={"head": EventCursors.head + 1},
            )
            .returning(EventCursors.head)
        )
        async with self._session_for(Events, org_id) as session:
            head = (await session.execute(take_next)).scalar_one()
            values: dict[str, Any] = {**to_values(event, Events), "org_id": org_id, "seq": head}
            stmt = insert(Events).values(values).returning(Events)
            try:
                row = (await session.execute(stmt)).scalar_one()
                appended = to_model(row, Event)
                await session.commit()
            except IntegrityError as error:
                # The rollback returns the number with it, so the stream stays gapless.
                await session.rollback()
                constraint = violated_constraint(error)
                if constraint != cast(Table, Events.__table__).primary_key.name:
                    raise UniqueKeyTaken(
                        f"events {event.id}: {constraint or 'a unique key'} is taken"
                    ) from error
                # The id is already appended: the relay ran twice, and the
                # second run returns what is stored.
                stored = await self._read(org_id, event.id)
                if stored is None:
                    raise TenantMismatch(f"events {event.id} is not in {org_id}") from error
                return stored
            return appended

    async def _read(self, org_id: UUID, event_id: UUID) -> Event | None:
        stmt = select(Events).where(Events.org_id == org_id, Events.id == event_id)
        async with self._session_for(stmt, org_id) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Event)

    async def read_after(self, org_id: UUID, after_seq: int, limit: int) -> list[Event]:
        stmt = (
            select(Events)
            .where(Events.org_id == org_id, Events.seq > after_seq)
            .order_by(Events.seq)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id) as session:
            result = await session.execute(stmt)
            return [to_model(row, Event) for row in result.scalars()]

    async def purge_tenant(self, org_id: UUID) -> int:
        events = delete(Events).where(Events.org_id == org_id).returning(Events.id)
        cursor = delete(EventCursors).where(EventCursors.org_id == org_id)
        async with self._session_for(Events, org_id) as session:
            purged = len((await session.execute(events)).scalars().all())
            await session.execute(cursor)
            await session.commit()
            return purged

    async def count_since(self, since: datetime) -> int:
        stmt = select(func.count()).select_from(Events).where(Events.produced_at >= since)
        async with self._session_for(stmt, EMPTY_UUID) as session:
            return (await session.execute(stmt)).scalar_one()

    async def read_head(self, org_id: UUID) -> int:
        # The cursor row is the head: one row, never a scan of the stream.
        stmt = select(EventCursors.head).where(EventCursors.org_id == org_id)
        async with self._session_for(stmt, org_id) as session:
            return int(await session.scalar(stmt) or 0)
