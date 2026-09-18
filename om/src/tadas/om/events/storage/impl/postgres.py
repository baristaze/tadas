from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, literal, select
from sqlalchemy.exc import IntegrityError

from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.storage.tables.events import Events
from tadas.om.events.types.event import Event
from tadas.om.exceptions import Conflict
from tadas.om.storage.impl.pg_base import PgStorageBase
from tadas.om.storage.utils.translation import to_model, to_values

APPEND_RETRIES = 32
"""Two appenders in one tenant race on the unique (org_id, seq); the loser
computes the next seq again. The retries are bounded so a broken index
surfaces as a Conflict instead of a spin."""


class EventStoragePostgresImpl(PgStorageBase, EventStorageInterface):
    async def append(self, org_id: UUID, event: Event) -> Event:
        for _ in range(APPEND_RETRIES):
            try:
                return await self._append_once(org_id, event)
            except IntegrityError:
                # Either the seq race or the id already appended; the second
                # case is the relay running twice and returns what is stored.
                stored = await self._read(org_id, event.id)
                if stored is not None:
                    return stored
                continue
        raise Conflict(f"could not append event {event.id} for org {org_id}")

    async def _append_once(self, org_id: UUID, event: Event) -> Event:
        columns = Events.__table__.c
        values: dict[str, Any] = {**to_values(event, Events), "org_id": org_id}
        values.pop("seq", None)
        next_seq = func.coalesce(func.max(Events.seq), 0) + 1
        names = [*values, "seq"]
        source = select(
            *(literal(values[name], columns[name].type).label(name) for name in values),
            next_seq.label("seq"),
        ).where(Events.org_id == org_id)
        stmt = insert(Events).from_select(names, source).returning(Events)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one()
            appended = to_model(row, Event)
            await session.commit()
            return appended

    async def _read(self, org_id: UUID, event_id: UUID) -> Event | None:
        stmt = select(Events).where(Events.org_id == org_id, Events.id == event_id)
        async with self._session_for(stmt) as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else to_model(row, Event)

    async def read_after(self, org_id: UUID, after_seq: int, limit: int) -> list[Event]:
        stmt = (
            select(Events)
            .where(Events.org_id == org_id, Events.seq > after_seq)
            .order_by(Events.seq)
            .limit(limit)
        )
        async with self._session_for(stmt) as session:
            result = await session.execute(stmt)
            return [to_model(row, Event) for row in result.scalars()]
