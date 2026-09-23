"""The tasks storage contract. The cases named in `CROSS_TENANT_CASES` are the
tenant fence's evidence: each one presents another tenant's identifier and
asserts that nothing is found and nothing changes. The negative control that
says what they catch is in `docs/runbooks/tenant-isolation.md`."""

from datetime import timedelta
from uuid import UUID

import pytest

from tadas.om.base import new_id, utcnow
from tadas.om.exceptions import PreconditionFailed, TenantMismatch
from tadas.om.outbox.types.row import OutboxRow
from tadas.om.tasks.rules import follows
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskCursor, TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus

CROSS_TENANT_CASES: frozenset[str] = frozenset(
    {
        "count_open_tasks",
        "create_task",
        "mark_reminded",
        "purge_deleted",
        "purge_tenant",
        "read_done_tasks",
        "read_open_places",
        "read_open_tasks",
        "read_task",
        "update_task",
        "update_tasks",
    }
)
"""Every method of `TasksStorageInterface` that takes a tenant has a case in
this module that presents another tenant's. `test_storage_exceptions.py` holds
the two sets to each other, so a new method arrives with its case."""


def team() -> TaskFilter:
    return TaskFilter(scope=TaskScope.TEAM, user_id=new_id())


def mine(user_id: UUID) -> TaskFilter:
    return TaskFilter(scope=TaskScope.MINE, user_id=user_id)


def after(task: Task) -> TaskCursor:
    return TaskCursor(updated_at=task.updated_at, id=task.id)


def past(task: Task) -> OpenTaskCursor:
    return OpenTaskCursor(position=task.position, id=task.id)


def make_row(org_id: UUID, task: Task, action: str = "created") -> OutboxRow:
    """The outbox row a write lands with; the memory outbox the root wires
    receives it, the Postgres one inserts it in the same commit."""
    return OutboxRow(
        id=new_id(),
        created_at=utcnow(),
        org_id=org_id,
        kind=f"tasks.task.{action}",
        target_id=task.id,
        payload={"title": task.title},
        actor_id=task.created_by,
        request_id=new_id(),
        app="api",
    )


async def seed(storage: TasksStorageInterface, org_id: UUID, task: Task) -> None:
    """Lands a task the way the manager does: through the create primitive.
    An update never inserts, so there is no other way in."""
    assert await storage.create_task(org_id, task, (make_row(org_id, task),)) is True


async def bump(storage: TasksStorageInterface, org_id: UUID, task: Task, **changes: object) -> Task:
    """The manager's copy on update, at the storage: the next version, written
    against the one the task carries."""
    changed = task.model_copy(update={**changes, "version": task.version + 1})
    await storage.update_task(
        org_id, changed, task.version, (make_row(org_id, changed, "updated"),)
    )
    return changed


def make_task(
    title: str = "Write the contract",
    *,
    created_by: UUID | None = None,
    assignee_id: UUID | None = None,
    status: TaskStatus = TaskStatus.OPEN,
    position: float = 0.0,
    updated_ago: timedelta = timedelta(0),
) -> Task:
    now = utcnow()
    return Task(
        id=new_id(),
        created_at=now,
        updated_at=now - updated_ago,
        created_by=created_by or new_id(),
        updated_by=created_by or new_id(),
        title=title,
        status=status,
        assignee_id=assignee_id,
        position=position,
    )


class TaskStorageContract:
    @pytest.fixture
    def storage(self) -> TasksStorageInterface:
        raise NotImplementedError("the concrete test class provides the storage")

    async def test_round_trip_and_update_by_copy(self, storage: TasksStorageInterface) -> None:
        org = new_id()
        task = make_task(assignee_id=new_id(), position=-2.5)
        await seed(storage, org, task)
        assert await storage.read_task(org, task.id) == task
        done = await bump(storage, org, task, status=TaskStatus.DONE, updated_at=utcnow())
        assert await storage.read_task(org, task.id) == done
        assert await storage.read_open_tasks(org, team(), None, limit=10) == []
        assert await storage.read_done_tasks(org, team(), None, limit=10) == [done]

    async def test_create_reports_an_existing_id_and_changes_nothing(
        self, storage: TasksStorageInterface
    ) -> None:
        # The create primitive: a retry presents the id it minted the first time;
        # the insert reports it, and neither the row nor the outbox is touched.
        org_id = new_id()
        task = make_task("Once")
        assert await storage.create_task(org_id, task, (make_row(org_id, task),)) is True
        again = task.model_copy(update={"title": "Twice"})
        assert await storage.create_task(org_id, again, (make_row(org_id, again),)) is False
        stored = await storage.read_task(org_id, task.id)
        assert stored is not None and stored.title == "Once"

    async def test_reads_are_tenant_scoped(self, storage: TasksStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        task = make_task()
        await seed(storage, org_a, task)
        assert await storage.read_task(org_b, task.id) is None
        assert await storage.read_open_tasks(org_b, team(), None, limit=10) == []
        assert await storage.read_open_places(org_b, exclude=None, after=None, limit=10) == []

    async def test_the_open_count_is_the_tenants_live_open_tasks(
        self, storage: TasksStorageInterface
    ) -> None:
        """The active tasks a plan bounds: open and not deleted, in this
        tenant; a done one, a deleted one, and another tenant's are not."""
        org_a, org_b = new_id(), new_id()
        open_task, done, gone = make_task("Open"), make_task("Done"), make_task("Gone")
        for task in (open_task, done, gone):
            await seed(storage, org_a, task)
        await bump(storage, org_a, done, status=TaskStatus.DONE)
        await bump(storage, org_a, gone, deleted_at=utcnow(), deleted_by=new_id())
        assert await storage.count_open_tasks(org_a, team()) == 1
        assert await storage.count_open_tasks(org_b, team()) == 0

    async def test_write_refuses_another_tenant(self, storage: TasksStorageInterface) -> None:
        org_a, org_b = new_id(), new_id()
        task = make_task()
        await seed(storage, org_a, task)
        with pytest.raises(TenantMismatch):
            await bump(storage, org_b, task, title="Stolen")
        assert await storage.read_task(org_a, task.id) == task

    async def test_the_done_list_is_tenant_scoped_on_its_own(
        self, storage: TasksStorageInterface
    ) -> None:
        """`read_done_tasks` writes its own `where`, so the open list's case
        says nothing about it: a predicate dropped here is invisible there.
        The filter travels with the tenant, so neither scope reaches across."""
        org_a, org_b = new_id(), new_id()
        author = new_id()
        theirs = [
            make_task(
                f"theirs{i}",
                created_by=author,
                status=TaskStatus.DONE,
                updated_ago=timedelta(minutes=i),
            )
            for i in range(3)
        ]
        for task in theirs:
            await seed(storage, org_a, task)
        assert await storage.read_done_tasks(org_b, team(), None, limit=10) == []
        assert await storage.read_done_tasks(org_b, mine(author), None, limit=10) == []
        assert len(await storage.read_done_tasks(org_a, team(), None, limit=10)) == 3

    async def test_the_open_count_is_the_open_list_of_one_tenant(
        self, storage: TasksStorageInterface
    ) -> None:
        """The open count counts what the open list shows: not a done task, not
        a deleted one, not another tenant's, and under `mine` not a task that
        is someone else's."""
        org_a, org_b = new_id(), new_id()
        author = new_id()
        for i in range(3):
            await seed(storage, org_a, make_task(f"open{i}", created_by=author))
        await seed(storage, org_a, make_task("theirs"))
        await seed(storage, org_a, make_task("done", status=TaskStatus.DONE))
        gone = make_task("deleted")
        await seed(storage, org_a, gone)
        await storage.update_task(
            org_a, gone.model_copy(update={"deleted_at": utcnow(), "version": 2}), 1, ()
        )
        assert await storage.count_open_tasks(org_a, team()) == 4
        assert await storage.count_open_tasks(org_a, mine(author)) == 3
        assert await storage.count_open_tasks(org_b, team()) == 0
        assert await storage.count_open_tasks(org_b, mine(author)) == 0

    async def test_the_created_count_spans_every_tenant_and_every_state(
        self, storage: TasksStorageInterface
    ) -> None:
        """The traffic figure the platform's size reads: tasks created at or
        after the cut, in whichever tenant and whatever became of them since;
        a task created before the cut is not traffic of the window."""
        cut = utcnow()
        assert await storage.count_created_since(cut) == 0
        org_a, org_b = new_id(), new_id()
        old = make_task("before the cut").model_copy(update={"created_at": cut - timedelta(days=2)})
        await seed(storage, org_a, old)
        done = make_task("done since", status=TaskStatus.DONE)
        await seed(storage, org_a, done)
        gone = make_task("deleted since")
        await seed(storage, org_b, gone)
        await storage.update_task(
            org_b, gone.model_copy(update={"deleted_at": utcnow(), "version": 2}), 1, ()
        )
        assert await storage.count_created_since(cut) == 2
        assert await storage.count_created_since(cut - timedelta(days=3)) == 3

    async def test_a_cursor_of_another_tenant_pages_nothing(
        self, storage: TasksStorageInterface
    ) -> None:
        """A cursor is a position in one tenant's order. Presented to another
        tenant it pages that tenant's own rows and never reaches across, on
        the open list and on the done list alike."""
        org_a, org_b = new_id(), new_id()
        theirs_open = make_task("theirs open", position=1.0)
        theirs_done = make_task("theirs done", status=TaskStatus.DONE)
        await seed(storage, org_a, theirs_open)
        await seed(storage, org_a, theirs_done)
        mine_open = make_task("mine open", position=2.0)
        mine_done = make_task("mine done", status=TaskStatus.DONE, updated_ago=timedelta(hours=1))
        await seed(storage, org_b, mine_open)
        await seed(storage, org_b, mine_done)
        paged_open = await storage.read_open_tasks(org_b, team(), past(theirs_open), limit=10)
        assert [t.title for t in paged_open] == ["mine open"]
        paged_done = await storage.read_done_tasks(org_b, team(), after(theirs_done), limit=10)
        assert [t.title for t in paged_done] == ["mine done"]
        # And the empty tenant stays empty however the cursor is placed.
        assert await storage.read_open_tasks(new_id(), team(), past(theirs_open), limit=10) == []
        assert await storage.read_done_tasks(new_id(), team(), after(theirs_done), limit=10) == []

    async def test_create_reports_another_tenants_id_and_lands_nothing(
        self, storage: TasksStorageInterface
    ) -> None:
        """The create primitive answers an id it cannot have the way it
        answers one of its own: it reports the id and writes nothing, so a
        caller presenting another tenant's id neither takes the row nor
        learns what stands on the other side."""
        org_a, org_b = new_id(), new_id()
        task = make_task("theirs")
        await seed(storage, org_a, task)
        stolen = task.model_copy(update={"title": "stolen"})
        assert await storage.create_task(org_b, stolen, (make_row(org_b, stolen),)) is False
        assert await storage.read_task(org_b, task.id) is None
        assert await storage.read_task(org_a, task.id) == task
        assert await storage.read_open_tasks(org_b, team(), None, limit=10) == []

    async def test_a_bulk_update_refuses_a_row_of_another_tenant_and_lands_none(
        self, storage: TasksStorageInterface
    ) -> None:
        """The one bulk write. Its all-or-nothing case tests versions; this one
        tests the tenant, and puts the foreign row second so the row before it
        would have landed had the statement not been fenced."""
        org_a, org_b = new_id(), new_id()
        mine = make_task("mine", position=0.5)
        theirs = make_task("theirs", position=0.75)
        await seed(storage, org_b, mine)
        await seed(storage, org_a, theirs)

        def placed(task: Task, position: float) -> Task:
            return task.model_copy(update={"position": position, "version": task.version + 1})

        with pytest.raises(TenantMismatch):
            await storage.update_tasks(
                org_b,
                [
                    (placed(mine, 0.0), mine.version, (make_row(org_b, mine, "updated"),)),
                    (placed(theirs, 1.0), theirs.version, (make_row(org_b, theirs, "updated"),)),
                ],
            )
        assert await storage.read_task(org_b, mine.id) == mine
        assert await storage.read_task(org_a, theirs.id) == theirs
        assert await storage.read_open_places(org_b, exclude=None, after=None, limit=10) == [
            (0.5, mine.id)
        ]

    async def test_update_is_a_compare_and_set_on_the_version(
        self, storage: TasksStorageInterface
    ) -> None:
        # Two writers read the task at version 1. The first lands at version 2;
        # the second still names version 1, so the row has moved under it and
        # the write is refused with nothing changed, not merged over the first.
        org = new_id()
        task = make_task("as read")
        await seed(storage, org, task)
        first = await bump(storage, org, task, title="first writer")
        with pytest.raises(PreconditionFailed):
            await bump(storage, org, task, title="second writer")
        assert await storage.read_task(org, task.id) == first
        assert first.version == 2
        # The winner's snapshot is current, so the next write from it lands.
        second = await bump(storage, org, first, title="first writer again")
        assert (await storage.read_task(org, task.id)) == second and second.version == 3

    async def test_update_never_inserts_a_missing_row(self, storage: TasksStorageInterface) -> None:
        # A row that is gone (purged between the read and the write) has moved
        # too: the update reports it and leaves nothing behind.
        org = new_id()
        task = make_task("never stored")
        with pytest.raises(PreconditionFailed):
            await bump(storage, org, task, title="conjured")
        assert await storage.read_task(org, task.id) is None

    async def test_open_list_sorts_by_position_hides_deleted_and_clamps(
        self, storage: TasksStorageInterface
    ) -> None:
        org = new_id()
        tasks = [make_task(f"t{i}", position=float(p)) for i, p in enumerate([3, -1, 2])]
        for task in tasks:
            await seed(storage, org, task)
        listed = await storage.read_open_tasks(org, team(), None, limit=10)
        assert [t.title for t in listed] == ["t1", "t2", "t0"]
        assert len(await storage.read_open_tasks(org, team(), None, limit=2)) == 2
        assert await storage.read_open_places(org, exclude=None, after=None, limit=10) == [
            (-1.0, tasks[1].id),
            (2.0, tasks[2].id),
            (3.0, tasks[0].id),
        ]
        assert await storage.read_open_places(org, exclude=tasks[1].id, after=None, limit=10) == [
            (2.0, tasks[2].id),
            (3.0, tasks[0].id),
        ]
        gone = await bump(storage, org, tasks[1], deleted_at=utcnow(), deleted_by=new_id())
        assert [t.title for t in await storage.read_open_tasks(org, team(), None, limit=10)] == [
            "t2",
            "t0",
        ]
        assert await storage.read_task(org, gone.id) == gone

    async def test_open_places_are_bounded_and_follow_the_rule(
        self, storage: TasksStorageInterface
    ) -> None:
        # The statement spells tasks.rules.follows and the open list's order;
        # this case holds both impls to the function. Two tasks share a
        # position, so the pair decides which follows the anchor.
        org = new_id()
        tasks = [make_task(f"p{i}", position=float(p)) for i, p in enumerate([1, 2, 2, 3, 4])]
        for task in tasks:
            await seed(storage, org, task)
        every = sorted((t.position, t.id) for t in tasks)
        assert await storage.read_open_places(org, None, None, limit=10) == every
        assert await storage.read_open_places(org, None, None, limit=1) == every[:1]
        assert await storage.read_open_places(org, None, None, limit=3) == every[:3]
        for index, anchor in enumerate(every):
            expected = [place for place in every if follows(place, anchor)]
            assert expected == every[index + 1 :]
            assert await storage.read_open_places(org, None, anchor, limit=10) == expected
            assert await storage.read_open_places(org, None, anchor, limit=1) == expected[:1]
        # Excluding the place that follows the anchor reads the one after it.
        first, second, third = every[0], every[1], every[2]
        assert await storage.read_open_places(org, second[1], first, limit=1) == [third]
        # An anchor that is no task's place still cuts by the pair.
        assert await storage.read_open_places(org, None, (2.5, new_id()), limit=1) == [every[3]]

    async def test_open_list_pages_by_position_cursor(self, storage: TasksStorageInterface) -> None:
        # Two tasks share a position (a seed, or a float that met its limit):
        # the id breaks the tie, in the list and in the cursor alike.
        org = new_id()
        tasks = [make_task(f"o{i}", position=float(p)) for i, p in enumerate([1, 2, 2, 3, 4])]
        for task in tasks:
            await seed(storage, org, task)
        first = await storage.read_open_tasks(org, team(), None, limit=2)
        second = await storage.read_open_tasks(org, team(), past(first[-1]), limit=2)
        third = await storage.read_open_tasks(org, team(), past(second[-1]), limit=2)
        assert [t.id for t in [*first, *second, *third]] == [
            t.id for t in sorted(tasks, key=lambda t: (t.position, t.id))
        ]
        assert await storage.read_open_tasks(org, team(), past(third[-1]), limit=2) == []

    async def test_done_list_is_newest_first_and_pages_by_cursor(
        self, storage: TasksStorageInterface
    ) -> None:
        org = new_id()
        tasks = [
            make_task(f"d{i}", status=TaskStatus.DONE, updated_ago=timedelta(minutes=i))
            for i in range(5)
        ]
        for task in reversed(tasks):
            await seed(storage, org, task)
        first = await storage.read_done_tasks(org, team(), None, limit=2)
        assert [t.title for t in first] == ["d0", "d1"]
        second = await storage.read_done_tasks(org, team(), after(first[-1]), limit=2)
        assert [t.title for t in second] == ["d2", "d3"]
        third = await storage.read_done_tasks(org, team(), after(second[-1]), limit=2)
        assert [t.title for t in third] == ["d4"]

    async def test_mine_is_assigned_to_me_or_unassigned_and_created_by_me(
        self, storage: TasksStorageInterface
    ) -> None:
        org, me, other = new_id(), new_id(), new_id()
        mine_created = make_task("created by me", created_by=me, position=1)
        mine_assigned = make_task("assigned to me", created_by=other, assignee_id=me, position=2)
        given_away = make_task("created by me, assigned away", created_by=me, assignee_id=other)
        theirs = make_task("theirs", created_by=other, position=3)
        mine_done = make_task("mine, done", created_by=me, status=TaskStatus.DONE)
        for task in (mine_created, mine_assigned, given_away, theirs, mine_done):
            await seed(storage, org, task)
        assert [t.title for t in await storage.read_open_tasks(org, mine(me), None, limit=10)] == [
            "created by me",
            "assigned to me",
        ]
        assert len(await storage.read_open_tasks(org, team(), None, limit=10)) == 4
        assert [t.title for t in await storage.read_done_tasks(org, mine(me), None, limit=10)] == [
            "mine, done"
        ]
        assert await storage.read_done_tasks(org, mine(other), None, limit=10) == []

    async def test_purge_removes_only_tasks_deleted_before_the_cut(
        self, storage: TasksStorageInterface
    ) -> None:
        org, elsewhere = new_id(), new_id()
        old, recent, live = make_task("old"), make_task("recent"), make_task("live")
        cut = utcnow()
        await seed(
            storage,
            org,
            old.model_copy(update={"deleted_at": cut - timedelta(days=1), "deleted_by": org}),
        )
        await seed(storage, org, recent.model_copy(update={"deleted_at": cut, "deleted_by": org}))
        await seed(storage, org, live)
        other = make_task("other")
        await seed(
            storage, elsewhere, other.model_copy(update={"deleted_at": cut - timedelta(days=1)})
        )
        assert await storage.purge_deleted(org, cut) == 1
        assert await storage.read_task(org, old.id) is None
        assert await storage.read_task(org, recent.id) is not None
        assert await storage.read_task(org, live.id) == live
        assert await storage.read_task(elsewhere, other.id) is not None, "per tenant"
        assert await storage.purge_deleted(org, cut) == 0, "idempotent"

    async def test_purge_tenant_takes_every_task_of_the_tenant(
        self, storage: TasksStorageInterface
    ) -> None:
        org, elsewhere = new_id(), new_id()
        live = make_task("open")
        done = make_task("done", status=TaskStatus.DONE)
        gone = make_task("deleted")
        await seed(storage, org, live)
        await seed(storage, org, done)
        await seed(
            storage, org, gone.model_copy(update={"deleted_at": utcnow(), "deleted_by": org})
        )
        other = make_task("other")
        await seed(storage, elsewhere, other)
        assert await storage.purge_tenant(org) == 3, "whatever its state"
        assert await storage.read_task(org, live.id) is None
        assert await storage.read_task(org, done.id) is None
        assert await storage.read_task(org, gone.id) is None
        assert await storage.read_task(elsewhere, other.id) is not None, "per tenant"
        assert await storage.purge_tenant(org) == 0, "idempotent"

    async def test_many_updates_land_together_or_not_at_all(
        self, storage: TasksStorageInterface
    ) -> None:
        # The renumbering of an open list: every row against its own version, in
        # one commit. One stale version refuses the whole write, so a list is
        # never renumbered halfway; from current versions every row lands.
        org = new_id()
        first, second = make_task("first", position=0.5), make_task("second", position=0.75)
        await seed(storage, org, first)
        await seed(storage, org, second)
        moved_second = await bump(storage, org, second, title="moved")  # now at version 2

        def placed(task: Task, position: float) -> Task:
            return task.model_copy(update={"position": position, "version": task.version + 1})

        with pytest.raises(PreconditionFailed):
            await storage.update_tasks(
                org,
                [
                    (placed(first, 0.0), first.version, (make_row(org, first, "updated"),)),
                    (placed(second, 1.0), second.version, (make_row(org, second, "updated"),)),
                ],
            )
        assert await storage.read_task(org, first.id) == first
        assert await storage.read_task(org, second.id) == moved_second
        renumbered = [placed(first, 0.0), placed(moved_second, 1.0)]
        await storage.update_tasks(
            org,
            [
                (renumbered[0], first.version, (make_row(org, first, "updated"),)),
                (renumbered[1], moved_second.version, (make_row(org, second, "updated"),)),
            ],
        )
        assert await storage.read_task(org, first.id) == renumbered[0]
        assert await storage.read_task(org, second.id) == renumbered[1]
        assert await storage.read_open_places(org, exclude=None, after=None, limit=10) == [
            (0.0, first.id),
            (1.0, second.id),
        ]

    async def test_a_reminder_is_marked_once_and_only_while_it_is_due(
        self, storage: TasksStorageInterface
    ) -> None:
        """The reminder's compare-and-set: it lands while the task is open,
        living, due at the time the reminder carries, and not yet reminded,
        and never for another tenant; a second run of it lands nothing."""
        org, other = new_id(), new_id()
        due = utcnow().replace(microsecond=0)
        task = make_task().model_copy(update={"remind_at": due})
        await storage.create_task(org, task, (make_row(org, task),))
        assert await storage.mark_reminded(other, task.id, due, utcnow(), ()) is None
        moved = due + timedelta(minutes=5)
        assert await storage.mark_reminded(org, task.id, moved, utcnow(), ()) is None
        now = utcnow()
        marked = await storage.mark_reminded(
            org, task.id, due, now, (make_row(org, task, "reminded"),)
        )
        assert marked is not None
        assert marked.reminded_at == now and marked.version == task.version + 1
        assert await storage.read_task(org, task.id) == marked
        assert await storage.mark_reminded(org, task.id, due, utcnow(), ()) is None
        done = make_task(status=TaskStatus.DONE).model_copy(update={"remind_at": due})
        await storage.create_task(org, done, (make_row(org, done),))
        assert await storage.mark_reminded(org, done.id, due, utcnow(), ()) is None
