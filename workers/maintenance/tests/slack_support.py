"""Helpers the reminder and Slack tests share: a container over the memory
roots and the Slack twin, orgs to act in, and the work a write queued."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

from worker_support import request

from tadas.infra.cache import CacheScope
from tadas.infra.impl.local import InfraLocalImpl
from tadas.integrations.identity.absent import IdentityProviderAbsentImpl
from tadas.integrations.slack.twin import SlackTwinImpl
from tadas.om.base import new_id, utcnow
from tadas.om.opcontext import AppContext, AppType, OpContext, Role
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.tasks.types.task import Task
from tadas.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from tadas.om.work.types.work_item import WorkItem, WorkKind
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.slack_inbound import (
    InboundDelivery,
    SlackInboundHandler,
    delivery_key,
)

TEAM = "TQSHA9YBT"
LEASE = timedelta(seconds=30)


def build(tmp_path: Path) -> tuple[WorkerContainer, SlackTwinImpl]:
    twin = SlackTwinImpl("test")
    container = WorkerContainer.for_tests(StorageMemoryImpl(), InfraLocalImpl(tmp_path), slack=twin)
    return container, twin


async def owner_of(container: WorkerContainer, slug: str) -> OpContext:
    ctx, _ = await container.managers.tenancy.bootstrap(
        request(), slug.title(), slug, f"owner@{slug}.test", "Owner"
    )
    return ctx


async def member_of(container: WorkerContainer, slug: str, email: str) -> OpContext:
    tenancy = container.managers.tenancy
    await tenancy.add_member(request(), slug, email, "Member", Role.MEMBER)
    # The worker signs nobody in, so the sign-in runs through a manager over
    # the same storage with the local sign-in on.
    signing = TenancyManagerImpl(
        container.storage.get_tenancy_storage(),
        container.managers.outbox,
        container.infra.get_cache(CacheScope.REALTIME_TICKET),
        TenancyOptions(dev_sign_in=True),
        identity_provider=IdentityProviderAbsentImpl(),
        entitlements=container.managers.billing,
    )
    login = await signing.dev_sign_in(request(), email)
    identity = await tenancy.authenticate_login(request(), login.token)
    memberships = await tenancy.get_identity_memberships(identity, None, 10)
    issued = await tenancy.exchange_login(identity, memberships.items[0].org.id)
    return await tenancy.authenticate(request(), issued.token)


def make_task(ctx: OpContext, title: str = "Water the plants", **fields: object) -> Task:
    now = utcnow()
    return Task(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        title=title,
        **fields,  # type: ignore[arg-type]
    )


async def queued(
    container: WorkerContainer, ctx: OpContext, kind: WorkKind, target_id: UUID | None = None
) -> list[WorkItem]:
    """The items of a kind the tenant's writes queued, oldest first, read off
    the memory queue without claiming anything."""
    storage = container.storage.get_work_storage()
    found: list[WorkItem] = []
    for _, (org_id, item) in sorted(storage._items.items()):  # type: ignore[attr-defined]
        if org_id == ctx.org_id and item.kind is kind:
            if target_id is None or item.target_id == target_id:
                found.append(item)
    return found


async def claim(container: WorkerContainer, kind: WorkKind) -> tuple[OpContext, WorkItem] | None:
    return await container.managers.work.claim(request(), "default", [kind], "test", LEASE)


def delivery(payload: dict[str, object], *, kind: str = "slash_commands") -> InboundDelivery:
    envelope = str(new_id())
    return InboundDelivery(
        key=delivery_key(kind, envelope, payload),
        received_at=utcnow(),
        type=kind,
        payload=payload,
    )


def command(text: str, channel: str = "C0SLACK", user: str = "U0PERSON") -> InboundDelivery:
    return delivery(
        {
            "command": "/tadas",
            "text": text,
            "team_id": TEAM,
            "channel_id": channel,
            "user_id": user,
            "response_url": "https://hooks.slack.com/commands/T/1/abc",
        }
    )


def inbound(container: WorkerContainer, twin: SlackTwinImpl) -> SlackInboundHandler:
    return SlackInboundHandler(
        container.managers.slack,
        container.managers.tasks,
        twin,
        AppContext(type=AppType.SLACK, version="slack@test"),
    )


async def connect(
    container: WorkerContainer, twin: SlackTwinImpl, owner: OpContext, channel: str = "C0SLACK"
) -> None:
    """Links a channel to the owner's org the way a person does: a code from
    the portal, typed into the channel."""
    issued = await container.managers.slack.issue_link_code(owner)
    await inbound(container, twin).handle(command(f"link {issued.code}", channel))
