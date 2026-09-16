from pathlib import Path

import pytest
from contracts.factories import make_org, make_user

from tadas.infra.impl.local import InfraLocalImpl
from tadas.infra.topics import EntityChangedPayload, TopicPayload, Topics
from tadas.om.base import new_id, utcnow
from tadas.om.events.impl.manager import EventsManagerImpl, EventsOptions
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.exceptions import Conflict, NotAuthorized, NotFound, ValidationFailed
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext, Role, build_context
from tadas.om.tasks.impl.manager import TasksManagerImpl, TasksOptions
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl
from tadas.om.tasks.types.task import Task

APP = AppContext(type=AppType.PORTAL, version="portal@test")


def context(role: Role) -> OpContext:
    org = make_org()
    user = make_user(new_id())
    return build_context(
        user=user,
        org=org,
        role=role,
        credential_kind=CredentialKind.SESSION_TOKEN,
        app=APP,
        request_id=new_id(),
    )


def make_task(ctx: OpContext, title: str = "Ship it") -> Task:
    now = utcnow()
    return Task(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        title=title,
        notes="",
        status="open",
    )


@pytest.fixture
def infra(tmp_path: Path) -> InfraLocalImpl:
    return InfraLocalImpl(tmp_path)


@pytest.fixture
def events() -> EventsManagerImpl:
    return EventsManagerImpl(EventStorageMemoryImpl(), EventsOptions())


@pytest.fixture
def manager(infra: InfraLocalImpl, events: EventsManagerImpl) -> TasksManagerImpl:
    return TasksManagerImpl(TasksStorageMemoryImpl(), events, infra.get_topics(), TasksOptions())


async def test_the_five_operations(
    manager: TasksManagerImpl, events: EventsManagerImpl, infra: InfraLocalImpl
) -> None:
    seen: list[TopicPayload] = []

    async def record(payload: TopicPayload) -> None:
        seen.append(payload)

    infra.get_topics().subscribe(Topics.ENTITY_CHANGED, "test", record)
    ctx = context(Role.MEMBER)
    created = await manager.create_task(ctx, make_task(ctx))
    assert created.created_by == ctx.user_id
    assert await manager.get_task(ctx, created.id) == created
    assert await manager.get_tasks(ctx, limit=10) == [created]

    updated = await manager.update_task(ctx, created.model_copy(update={"status": "done"}))
    assert updated.status == "done" and updated.updated_at > created.updated_at
    assert await manager.get_task(ctx, created.id) == updated

    deleted = await manager.delete_task(ctx, created.id)
    assert deleted.deleted_at is not None and deleted.deleted_by == ctx.user_id
    assert await manager.get_tasks(ctx, limit=10) == []
    with pytest.raises(NotFound):
        await manager.get_task(ctx, created.id)
    assert [p.action for p in seen if isinstance(p, EntityChangedPayload)] == [
        "created",
        "updated",
        "deleted",
    ]
    assert all(isinstance(p, EntityChangedPayload) and p.entity == "task" for p in seen)
    # Every push is also a record: the payload carries the seq the stream assigned.
    assert [p.seq for p in seen if isinstance(p, EntityChangedPayload)] == [1, 2, 3]
    recorded = await events.get_events(ctx, after_seq=0, limit=10)
    assert [(e.seq, e.action, e.entity_id) for e in recorded] == [
        (1, "created", created.id),
        (2, "updated", created.id),
        (3, "deleted", created.id),
    ]
    assert {e.idempotency_key for e in recorded} == {p.idempotency_key for p in seen}
    assert all(e.actor_id == ctx.user_id for e in recorded)


async def test_authorize_then_verify(manager: TasksManagerImpl) -> None:
    viewer = context(Role.VIEWER)
    with pytest.raises(NotAuthorized):
        await manager.create_task(viewer, make_task(viewer))
    assert await manager.get_tasks(viewer, limit=10) == []

    member = context(Role.MEMBER)
    with pytest.raises(ValidationFailed):
        await manager.create_task(member, make_task(member, title="   "))
    task = await manager.create_task(member, make_task(member))
    with pytest.raises(Conflict):
        await manager.create_task(member, task)
    with pytest.raises(NotFound):
        await manager.update_task(member, make_task(member))
    with pytest.raises(NotFound):
        await manager.delete_task(member, new_id())


async def test_tenancy_holds_across_contexts(manager: TasksManagerImpl) -> None:
    ann, bob = context(Role.MEMBER), context(Role.MEMBER)
    task = await manager.create_task(ann, make_task(ann))
    with pytest.raises(NotFound):
        await manager.get_task(bob, task.id)
    assert await manager.get_tasks(bob, limit=10) == []


async def test_lists_are_clamped(infra: InfraLocalImpl) -> None:
    manager = TasksManagerImpl(
        TasksStorageMemoryImpl(),
        EventsManagerImpl(EventStorageMemoryImpl(), EventsOptions()),
        infra.get_topics(),
        TasksOptions(max_limit=2),
    )
    ctx = context(Role.MEMBER)
    for i in range(3):
        await manager.create_task(ctx, make_task(ctx, title=f"t{i}"))
    assert len(await manager.get_tasks(ctx, limit=1000)) == 2
