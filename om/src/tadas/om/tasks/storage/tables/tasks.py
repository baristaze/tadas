from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Index, text
from sqlalchemy.orm import Mapped, mapped_column

from tadas.om.storage.tables.base import (
    Base,
    IdentifiableMixin,
    SoftDeletableMixin,
    TrackableMixin,
)


class Tasks(IdentifiableMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "tasks"
    # Two lists per org: the open one in manual order, the done one newest
    # first; and the open one newest first, the short list Slack shows. Each
    # has its compound index, so org_id gets none of its own.
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_tasks_org_id_status_position", "org_id", "status", "position"),
        Index("ix_tasks_org_id_status_id", "org_id", "status", "id"),
        # The done list and the archive, one index per shelf, so the cleanup's
        # read of the archivable tasks never walks the archive. The predicates
        # leave `status` out: it is bound as a parameter, and a generic plan
        # cannot prove a partial predicate on one.
        Index(
            "ix_tasks_org_id_status_updated_at_id_unarchived",
            "org_id",
            "status",
            "updated_at",
            "id",
            postgresql_where=text("archived_at IS NULL AND deleted_at IS NULL"),
        ),
        Index(
            "ix_tasks_org_id_status_updated_at_id_archived",
            "org_id",
            "status",
            "updated_at",
            "id",
            postgresql_where=text("archived_at IS NOT NULL AND deleted_at IS NULL"),
        ),
        # The `mine` scope, one index per arm of its OR: the tasks assigned to
        # the caller, and the unassigned ones the caller made.
        Index(
            "ix_tasks_org_id_assignee_id_status",
            "org_id",
            "assignee_id",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_tasks_org_id_created_by_status",
            "org_id",
            "created_by",
            "status",
            postgresql_where=text("assignee_id IS NULL AND deleted_at IS NULL"),
        ),
        # The purge reads the deleted ones by their delete; only they are in it.
        Index(
            "ix_tasks_org_id_deleted_at",
            "org_id",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
    )
    title: Mapped[str]
    notes: Mapped[str]
    status: Mapped[str]
    assignee_id: Mapped[UUID | None]
    position: Mapped[float]
    # The compare-and-set column. The server default is for a row an older
    # build inserts during a rollout; the object model always sends a value.
    version: Mapped[int] = mapped_column(server_default="1")
    due_on: Mapped[date | None]
    reminded_at: Mapped[datetime | None]
    archived_at: Mapped[datetime | None]
