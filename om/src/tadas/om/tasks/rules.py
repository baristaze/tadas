"""Pure rules of the tasks namespace: which tasks a filter shows, where a
cursor cuts, the arithmetic of the open list's manual order, when a due
date's reminder goes out, what an import file and its rows may be, which
done tasks the cleanup archives, and which tasks a bulk change leaves alone.
Values in,
values out; no clock, no storage, no settings. The manager and both storage
impls call these; the relational impl spells the visibility, cursor, and
follows rules in SQL where one statement must decide, and names the rule it
mirrors."""

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tadas.om.base import Platform
from tadas.om.exceptions import ValidationFailed
from tadas.om.tasks.types.bulk import BulkAction, SkipReason
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus

Place = tuple[float, UUID]
"""Where an open task sits: its position and its id, the pair the open list is
ordered by. A position is not unique — two writers that read the same list
place two tasks at the same one — so every rule below compares the pair, the
way `is_after` and the storage's ordering do. Which place follows the anchor
is decided on the pair; whether there is room between them is decided on the
positions alone, so a placement never adds a tie of its own."""


def is_visible(task: Task, criterion: TaskFilter) -> bool:
    """`team` shows every task; `mine` shows a task assigned to the person, or
    unassigned and created by them."""
    if criterion.scope is TaskScope.TEAM:
        return True
    if task.assignee_id is not None:
        return task.assignee_id == criterion.user_id
    return task.created_by == criterion.user_id


def is_before(task: Task, cursor: TaskCursor) -> bool:
    """The done list is newest first; a task is on the next page when its
    (updated_at, id) sorts strictly before the cursor's."""
    return (task.updated_at, task.id) < (cursor.updated_at, cursor.id)


def is_after(task: Task, cursor: OpenTaskCursor) -> bool:
    """The open list is by position, top first; a task is on the next page
    when its (position, id) sorts strictly after the cursor's."""
    return (task.position, task.id) > (cursor.position, cursor.id)


def top_position(places: Sequence[Place]) -> float:
    """The position above every open task, given their places ascending:
    one below the smallest, or 0.0 when the list is empty. Only the first
    place is read, so the top place alone is enough."""
    return places[0][0] - 1.0 if places else 0.0


def follows(place: Place, anchor: Place) -> bool:
    """Whether `place` comes after `anchor` in the order the open list reads:
    the pair compared, so a place that ties with the anchor on position and
    follows it on id is after it."""
    return place > anchor


def _following(anchor: Place, places: Sequence[Place]) -> Place | None:
    """The open place right after `anchor` in the order the list reads. A place
    that ties with the anchor on position and follows it on id is after it;
    reading positions alone would skip over it to the next larger position and
    place a task the caller asked to follow the anchor behind its twin. The
    places may be every open place or only the first one after the anchor;
    the answer is the same."""
    after = [place for place in places if follows(place, anchor)]
    return min(after) if after else None


def position_after(anchor: Place, places: Sequence[Place]) -> float:
    """The position right after `anchor`, given the other open places: halfway
    to the one that follows it, or one past the anchor when it is last."""
    following = _following(anchor, places)
    return (anchor[0] + following[0]) / 2 if following is not None else anchor[0] + 1.0


def is_between(anchor: Place, position: float, places: Sequence[Place]) -> bool:
    """Whether `position` falls strictly after the anchor's and strictly before
    that of the place which follows it, so the order it was chosen for is the
    order the list reads back and no two open tasks share it. Halving a gap
    ends at float precision, and so does a position that already ties with its
    neighbour: once the midpoint equals either of them there is no room left
    and the list is renumbered."""
    following = _following(anchor, places)
    return anchor[0] < position and (following is None or position < following[0])


def renumbered(count: int) -> list[float]:
    """The positions of a renumbered open list, top first: whole numbers, so
    every gap is wide again."""
    return [float(index) for index in range(count)]


REMINDER_HOUR = time(9)
"""A due date has no hour, so its reminder takes one: nine in the morning of
the due date, in the time zone of the person the task is for."""

AHEAD_OF_UTC_AT_MOST = timedelta(hours=14)
"""The furthest any time zone runs ahead of UTC (Pacific/Kiritimati): no
person's morning of a date comes before nine there."""


def reminder_zone(name: str | None) -> ZoneInfo:
    """The zone a reminder is timed in: the person's, by its IANA name, or UTC
    when they have none or the name is not one this process knows."""
    if name:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError, ValueError:
            pass
    return ZoneInfo("UTC")


def reminder_person(task: Task) -> UUID:
    """Whose morning the reminder keeps: the assignee's, or the creator's when
    the task is unassigned."""
    return task.assignee_id if task.assignee_id is not None else task.created_by


def reminder_time(due_on: date, time_zone: str | None) -> datetime:
    """When the reminder of `due_on` goes out: nine in the morning of that
    day in the zone named, in UTC. A day that skips or repeats nine (a
    daylight-saving change at that hour) takes the first reading."""
    local = datetime.combine(due_on, REMINDER_HOUR, tzinfo=reminder_zone(time_zone))
    return local.astimezone(UTC)


def earliest_reminder_time(due_on: date) -> datetime:
    """The first moment any person's reminder of `due_on` can go out: nine
    in the morning in the zone furthest ahead of UTC. The reminder's work
    item waits in the queue until then, and its handler waits the rest from
    the person's zone as it reads when it runs, so an assignee changed or a
    zone moved after the date was set is still met on their morning."""
    return datetime.combine(due_on, REMINDER_HOUR, tzinfo=UTC) - AHEAD_OF_UTC_AT_MOST


# The import of tasks from a CSV file, and the cleanup of old done tasks. The
# numbers are illustrative, like the plans': the shape is what holds.

IMPORT_COLUMNS = ("title", "notes", "due_on", "assignee_email")
"""The columns an import reads, by header name, in any order; `title` is the
one it needs. A column it does not know is ignored."""

IMPORT_MAX_ROWS = 5000
"""The most data rows one import reads. A file with more fails at once and
creates nothing: a bound, not a guard."""

IMPORT_BATCH = 100
"""The rows one step reads: one commit creates their tasks and moves the cursor."""

CLEANUP_BATCH = 500
"""The tasks one cleanup step archives, in one conditional write."""

BULK_BATCH = 100
"""The tasks one commit of a bulk change writes: a section of thousands is
many short transactions, never one long one."""

BULK_MAX_IDS = 1000
"""The most tasks a bulk change names by id. It is also the report's cap
(`BULK_REPORT_CAP`), so every change a report names in full can be undone by
naming its tasks back."""

BULK_REPORT_CAP = BULK_MAX_IDS
"""The most ids a bulk change's answer lists, of the tasks it changed and of
the ones it skipped; the counts beside the lists are whole."""


def bulk_positions(top: float, count: int) -> list[float]:
    """The places of `count` tasks a bulk reopen puts on top of the open list,
    given the place above the current top (`top_position`): each one above
    the one before, as if they were reopened one at a time in the order
    given, so the last one given is the top."""
    return [top - index for index in range(count)]


def bulk_skip(task: Task | None, action: BulkAction) -> SkipReason | None:
    """Why a bulk change leaves this task alone, or None when it changes it.
    The rules a single edit applies: a task that is gone is not found, and
    each action changes only a task in the status it starts from. A task
    in the other status was changed by someone first, and the change it asked
    for is already true."""
    if task is None or task.deleted_at is not None:
        return SkipReason.NOT_FOUND
    if action is BulkAction.COMPLETE and task.status is not TaskStatus.OPEN:
        return SkipReason.ALREADY_DONE
    if action is BulkAction.REOPEN and task.status is not TaskStatus.DONE:
        return SkipReason.ALREADY_OPEN
    return None


MAX_TITLE_LENGTH = 500


class ImportFileRefused(ValidationFailed):
    """The file is past a bound of the import; `reason` names which one,
    as `orchestrations.types.FailReason` spells it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ImportRow(Platform):
    """One data row, as the file holds it; every field a string."""

    number: int  # the first data row is 1
    title: str = ""
    notes: str = ""
    due_on: str = ""
    assignee_email: str = ""


class ImportedTask(Platform):
    """A row that makes a task: its fields checked and typed."""

    number: int
    title: str
    notes: str
    due_on: date | None
    assignee_id: UUID | None


def parse_import(data: bytes, max_bytes: int, max_rows: int = IMPORT_MAX_ROWS) -> list[ImportRow]:
    """The file's data rows, or `ImportFileRefused` when the file is past a
    bound: larger than `max_bytes` (`file_too_large`), not text a CSV reader
    reads (`not_csv`), without a `title` header (`no_title_column`), or with
    more than `max_rows` rows (`too_many_rows`). A row that is empty in every
    column is not a row. The whole file is read every step: it is bounded,
    and a stateless worker holds nothing between two."""
    if len(data) > max_bytes:
        raise ImportFileRefused("file_too_large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportFileRefused("not_csv") from None
    if "\x00" in text:
        raise ImportFileRefused("not_csv")
    try:
        lines = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error:
        raise ImportFileRefused("not_csv") from None
    if not lines:
        raise ImportFileRefused("no_title_column")
    header = [name.strip().lower() for name in lines[0]]
    if "title" not in header:
        raise ImportFileRefused("no_title_column")
    columns = {name: index for index, name in enumerate(header) if name in IMPORT_COLUMNS}
    rows: list[ImportRow] = []
    for cells in lines[1:]:
        if not any(cell.strip() for cell in cells):
            continue
        if len(rows) == max_rows:
            raise ImportFileRefused("too_many_rows")
        fields = {
            name: cells[index].strip() if index < len(cells) else ""
            for name, index in columns.items()
        }
        rows.append(ImportRow(number=len(rows) + 1, **fields))
    return rows


def import_refusal(row: ImportRow, members: Mapping[str, UUID]) -> str | None:
    """Why a row makes no task, or None when it makes one: a title it lacks
    or one too long, a due date that is not `YYYY-MM-DD`, an assignee who is
    not a member of the org. `members` maps a member's address, lower-cased,
    to the member."""
    if not row.title:
        return "no title"
    if len(row.title) > MAX_TITLE_LENGTH:
        return f"a title is at most {MAX_TITLE_LENGTH} characters"
    if row.due_on and _date(row.due_on) is None:
        return f"due_on {row.due_on!r} is not a date (YYYY-MM-DD)"
    if row.assignee_email and row.assignee_email.lower() not in members:
        return f"{row.assignee_email} is not a member of this org"
    return None


def imported(row: ImportRow, members: Mapping[str, UUID]) -> ImportedTask:
    """The task a row makes, once `import_refusal` found nothing wrong."""
    return ImportedTask(
        number=row.number,
        title=row.title,
        notes=row.notes,
        due_on=_date(row.due_on) if row.due_on else None,
        assignee_id=members[row.assignee_email.lower()] if row.assignee_email else None,
    )


def _date(value: str) -> date | None:
    if len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def room_for(bound: int | None, active: int) -> int | None:
    """How many more tasks the plan lets the org open: None when it has no
    bound, and never below zero (an org over its bound after a downgrade has
    no room, and keeps what it has)."""
    return None if bound is None else max(0, bound - active)


def cleanup_period(now: datetime) -> str:
    """The day a cleanup record is for: the UTC date, which with the org and
    the kind is the record's unique key, and from which its id is derived."""
    return now.astimezone(UTC).date().isoformat()


def import_row_part(number: int) -> str:
    """What an imported row's task id is derived from beside the import's id
    (`base.derived_id`): the same row stepped twice presents the same id."""
    return f"row:{number}"


def cleanup_part(period: str) -> str:
    """What the day's cleanup record id is derived from beside the org's id."""
    return f"task_cleanup:{period}"


def is_archivable(task: Task, before: datetime) -> bool:
    """A task the cleanup archives: done, not deleted, not archived yet, and
    unchanged since before `before`. A task reopened, edited, or deleted
    meanwhile no longer is, and the conditional write leaves it alone."""
    return (
        task.status is TaskStatus.DONE
        and task.deleted_at is None
        and task.archived_at is None
        and task.updated_at < before
    )
