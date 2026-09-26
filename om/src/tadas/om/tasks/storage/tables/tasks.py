from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Index, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column

from tadas.om.storage.tables.base import (
    Base,
    IdentifiableMixin,
    SoftDeletableMixin,
    TrackableMixin,
)
from tadas.om.tasks.rules import RANK_SCALE_BOUND


class Tasks(IdentifiableMixin, TrackableMixin, SoftDeletableMixin, Base):
    __tablename__ = "tasks"
    # Two lists per org: the open one in manual order, the done one newest
    # first; and the open one newest first, the short list Slack shows. Each
    # has its compound index, so org_id gets none of its own.
    __org_id_index__ = False
    __table_args__ = (
        Index("ix_tasks_org_id_status_rank", "org_id", "status", "rank"),
        # The release before orders the open list by position; the index goes
        # with the column (ADR 0050).
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
        # The sweep's respace finds a tenant's rank that grew too long. Only
        # such ranks are in it, so the read that finds none reads nothing.
        # The bound is a literal, the one tasks.rules.RANK_SCALE_BOUND names.
        Index(
            "ix_tasks_org_id_rank_long",
            "org_id",
            "rank",
            postgresql_where=text(f"scale(rank) > {RANK_SCALE_BOUND} AND deleted_at IS NULL"),
        ),
        # The sweep reads the deleted ones by their delete, across tenants;
        # only they are in it.
        Index("ix_tasks_deleted_at", "deleted_at", postgresql_where=text("deleted_at IS NOT NULL")),
    )
    title: Mapped[str]
    notes: Mapped[str]
    status: Mapped[str]
    assignee_id: Mapped[UUID | None]
    # The order of the open list: an exact decimal, compared exactly
    # (tasks.rules.spread).
    rank: Mapped[Decimal] = mapped_column(Numeric())
    # The rank as a float, for the release before, which orders by it. A
    # trigger gives a row that release writes a rank from it (migration
    # 202610120000). Both go with that release (ADR 0050).
    position: Mapped[float]
    # The compare-and-set column. The server default is for a row an older
    # build inserts during a rollout; the object model always sends a value.
    version: Mapped[int] = mapped_column(server_default="1")
    due_on: Mapped[date | None]
    reminded_at: Mapped[datetime | None]
    archived_at: Mapped[datetime | None]
