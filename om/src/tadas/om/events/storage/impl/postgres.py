import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    Table,
    Text,
    Uuid,
    bindparam,
    delete,
    exists,
    func,
    insert,
    select,
    true,
    update,
)
from sqlalchemy import cast as cast_
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.dml import ReturningInsert

from tadas.om.base import EMPTY_UUID
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.storage.tables.event_cursors import EventCursors
from tadas.om.events.storage.tables.events import Events
from tadas.om.events.types.event import Event
from tadas.om.exceptions import TenantMismatch, UniqueKeyTaken
from tadas.om.storage.impl.pg_base import PgStorageBase, delete_batch, deleted, violated_constraint
from tadas.om.storage.utils.translation import to_model, to_values

WRITTEN: tuple[str, ...] = tuple(
    name for name in cast(Table, Events.__table__).c.keys() if name not in ("org_id", "seq")
)
"""The columns an append writes from the event; storage writes `org_id` and `seq`."""


def _append_statement() -> ReturningInsert[Any]:
    """The append, in one statement. The events arrive as one array per column,
    so the statement is the same for one event and for a hundred, and it is
    compiled and prepared once. Those not yet in the stream take the next
    numbers from the tenant's cursor row, `head + n` under the row's lock, and
    are written with them, in the order given. The lock is held from this
    statement to the commit and no longer: two appends to one tenant queue on
    it, each leaves with the next contiguous run, and they commit in the order
    of their numbers. The first append inserts the row. Never `MAX(seq) + 1`
    and a retry on the unique index: on a busy tenant that loop is a Conflict
    generator.

    Built on the tables and not the mapped classes, so it runs as one Core
    statement with its arrays as plain parameters."""
    table = cast(Table, Events.__table__)
    cursors = cast(Table, EventCursors.__table__)
    org_id = bindparam("org_id", type_=Uuid())
    incoming = (
        func.unnest(
            *(
                bindparam(name, type_=ARRAY(Text() if name == "payload" else table.c[name].type))
                for name in WRITTEN
            )
        )
        .table_valued(*WRITTEN, with_ordinality="ordinal")
        .render_derived(name="incoming")
    )
    # An event already appended is left out, and takes no number.
    fresh = (
        select(
            *(incoming.c[name] for name in WRITTEN),
            func.row_number().over(order_by=incoming.c.ordinal).label("rank"),
        )
        .where(~exists().where(table.c.org_id == org_id, table.c.id == incoming.c.id))
        .cte("fresh")
    )
    # As many numbers as there are new events, and the cursor untouched when
    # there are none.
    wanted = select(org_id, func.count()).select_from(fresh).having(func.count() > 0)
    reserve = pg_insert(cursors).from_select(["org_id", "head"], wanted)
    taken = (
        reserve.on_conflict_do_update(
            index_elements=[cursors.c.org_id],
            set_={"head": cursors.c.head + reserve.excluded.head},
        )
        .returning(cursors.c.head)
        .cte("taken")
    )
    size = select(func.count()).select_from(fresh).scalar_subquery()
    written = [
        cast_(fresh.c.payload, JSONB) if name == "payload" else fresh.c[name] for name in WRITTEN
    ]
    return (
        insert(table)
        .from_select(
            [*WRITTEN, "org_id", "seq"],
            select(*written, org_id, taken.c.head - size + fresh.c.rank).select_from(
                fresh.join(taken, true())
            ),
        )
        .returning(*table.c)
    )


APPEND = _append_statement()


class EventStoragePostgresImpl(PgStorageBase, EventStorageInterface):
    async def append_events(self, org_id: UUID, events: Sequence[Event]) -> tuple[Event, ...]:
        batch = list(events)
        if len({event.id for event in batch}) != len(batch):
            raise ValueError("an append names one event id twice")
        stored: dict[UUID, Event] = {}
        while pending := [event for event in batch if event.id not in stored]:
            try:
                stored.update(await self._append(org_id, pending))
            except IntegrityError as error:
                constraint = violated_constraint(error)
                if constraint != cast(Table, Events.__table__).primary_key.name:
                    raise UniqueKeyTaken(
                        f"events of {org_id}: {constraint or 'a unique key'} is taken"
                    ) from error
                # An id of the batch was appended since the statement read the
                # stream: a relay that ran twice at once. The rollback returned
                # every number, and the retry leaves out what is stored now.
                # An id that stays out of reach is another tenant's.
                found = await self._read_ids(org_id, [event.id for event in pending])
                if not found:
                    raise TenantMismatch(
                        f"events {[str(event.id) for event in pending]}: an id is not in {org_id}"
                    ) from error
                stored.update(found)
                continue
            # What the statement left out was already appended: the relay ran
            # twice, and the second run returns what is stored.
            skipped = [event.id for event in pending if event.id not in stored]
            if skipped:
                stored.update(await self._read_ids(org_id, skipped))
            break
        return tuple(stored[event.id] for event in batch)

    async def _append(self, org_id: UUID, events: list[Event]) -> dict[UUID, Event]:
        """`APPEND` for these events: the new ones take the next numbers from
        the cursor row and are written with them, and come back by id."""
        rows = [to_values(event, Events) for event in events]
        params: dict[str, object] = {name: [row[name] for row in rows] for name in WRITTEN}
        # The payload travels as JSON text and is cast back in the statement.
        params["payload"] = [json.dumps(row["payload"]) for row in rows]
        params["org_id"] = org_id
        async with self._session_for(Events, org_id=org_id) as session:
            try:
                result = (await session.execute(APPEND, params)).all()
                appended = {row.id: to_model(row, Event) for row in result}
                await session.commit()
            except IntegrityError:
                # The rollback returns the numbers with it, so the stream stays gapless.
                await session.rollback()
                raise
            return appended

    async def _read_ids(self, org_id: UUID, event_ids: list[UUID]) -> dict[UUID, Event]:
        stmt = select(Events).where(Events.org_id == org_id, Events.id.in_(event_ids))
        async with self._session_for(stmt, org_id=org_id) as session:
            return {row.id: to_model(row, Event) for row in (await session.execute(stmt)).scalars()}

    async def read_after(self, org_id: UUID, after_seq: int, limit: int) -> list[Event]:
        stmt = (
            select(Events)
            .where(Events.org_id == org_id, Events.seq > after_seq)
            .order_by(Events.seq)
            .limit(limit)
        )
        async with self._session_for(stmt, org_id=org_id) as session:
            result = await session.execute(stmt)
            return [to_model(row, Event) for row in result.scalars()]

    async def purge_tenant(self, org_id: UUID, limit: int) -> int:
        events = delete_batch(Events, Events.org_id == org_id, limit=limit)
        cursor = delete(EventCursors).where(EventCursors.org_id == org_id)
        async with self._session_for(Events, org_id=org_id) as session:
            purged = deleted(await session.execute(events))
            if purged < limit:
                # The stream is empty now, so its counter goes too.
                await session.execute(cursor)
            await session.commit()
            return purged

    async def trim(self, org_id: UUID, before: datetime, limit: int) -> int:
        # The cursor row's lock first, as the append takes it: a second trim
        # waits here and then reads the floor the first one left, and an
        # append waits the few milliseconds one bounded batch takes.
        lock = select(EventCursors.floor).where(EventCursors.org_id == org_id).with_for_update()
        async with self._session_for(Events, org_id=org_id) as session:
            floor = (await session.execute(lock)).scalar_one_or_none()
            if floor is None:
                return 0
            bottom = (
                select(Events.seq, Events.produced_at)
                .where(Events.org_id == org_id, Events.seq > floor)
                .order_by(Events.seq)
                .limit(limit)
            )
            top: int | None = None
            for seq, produced_at in (await session.execute(bottom)).all():
                if produced_at >= before:
                    break
                top = seq
            if top is None:
                await session.rollback()
                return 0
            # A range on the (org_id, seq) index, and the floor with it, in one
            # transaction: no reader sees the events gone and the floor below them.
            gone = delete(Events).where(
                Events.org_id == org_id, Events.seq > floor, Events.seq <= top
            )
            trimmed = deleted(await session.execute(gone))
            moved = update(EventCursors).where(EventCursors.org_id == org_id).values(floor=top)
            await session.execute(moved)
            await session.commit()
            return trimmed

    async def read_floor(self, org_id: UUID) -> int:
        stmt = select(EventCursors.floor).where(EventCursors.org_id == org_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            return int(await session.scalar(stmt) or 0)

    async def count_since(self, since: datetime) -> int:
        stmt = select(func.count()).select_from(Events).where(Events.produced_at >= since)
        async with self._session_for(stmt, org_id=EMPTY_UUID) as session:
            return (await session.execute(stmt)).scalar_one()

    async def read_head(self, org_id: UUID) -> int:
        # The cursor row is the head: one row, never a scan of the stream.
        stmt = select(EventCursors.head).where(EventCursors.org_id == org_id)
        async with self._session_for(stmt, org_id=org_id) as session:
            return int(await session.scalar(stmt) or 0)
