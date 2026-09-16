"""The declarative base that derives each table's schema from the role map,
and the column mixins that mirror the OM mixins."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, MetaData, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tadas.om.storage.roles import role_for

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        str: Text(),
        bool: Boolean(),
        int: Integer(),
        datetime: DateTime(timezone=True),
        UUID: Uuid(),
        dict[str, Any]: JSONB(),
        list[str]: JSONB(),
    }

    def __init_subclass__(cls, **kwargs: Any) -> None:
        tablename = cls.__dict__.get("__tablename__")
        if tablename is not None:
            schema = {"schema": role_for(tablename).value}
            args = cls.__dict__.get("__table_args__", ())
            if isinstance(args, dict):
                cls.__table_args__ = {**args, **schema}
            elif args and isinstance(args[-1], dict):
                cls.__table_args__ = (*args[:-1], {**args[-1], **schema})
            else:
                cls.__table_args__ = (*args, schema)
        super().__init_subclass__(**kwargs)


class IdentifiableMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, sort_order=-1000)
    org_id: Mapped[UUID] = mapped_column(index=True, sort_order=-999)  # storage-only


class GlobalIdentifiableMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, sort_order=-1000)


class NamedMixin:
    name: Mapped[str] = mapped_column(sort_order=-900)


class TrackableMixin:
    created_at: Mapped[datetime] = mapped_column(sort_order=-800)
    updated_at: Mapped[datetime] = mapped_column(sort_order=-799)
    created_by: Mapped[UUID] = mapped_column(sort_order=-798)


class SoftDeletableMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(sort_order=-700)
    deleted_by: Mapped[UUID | None] = mapped_column(sort_order=-699)
