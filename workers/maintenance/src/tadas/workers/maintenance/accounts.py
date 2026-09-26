"""The handlers of a deleted account: what its one commit could not do.

The account's own rows go in the request that deleted it, so the person is
gone the moment it answers and nothing below can bring them back. What is
left is outside the database, or in orgs the person no longer holds a place
in, and the queue carries it to the end.

`DELETE_ACCOUNT` runs in the person's personal org. It deletes the person at
the identity provider, ends the org's subscription and deletes its customer
at the payment processor, removes the org's Slack app, and deletes the org
last, which the sweep then purges whole. Every step is one a rerun finds
done, so a run that stopped halfway is finished by the next. A provider that
cannot be reached parks the item, spending no attempt: nothing has failed,
and the work waits for the provider to come back. A provider that refuses
fails it, which retries and then leaves a failed item for an operator to
read. The org stays until the providers are done: deleted first, it could
no longer run the work that names it.

`UNASSIGN_TASKS` runs in each org the person left, under their name: their
open tasks there go unassigned, each by the update a person makes to clear
an assignee. It runs on the service role, whatever role the person held:
the unassignment is what an account's deletion does, not a write the
person asks for (ADR 0041)."""

import logging
from datetime import timedelta
from typing import ClassVar

from tadas.infra.exceptions import InfraException
from tadas.integrations.identity import IdentityProviderInterface
from tadas.om.billing import BillingManagerInterface
from tadas.om.exceptions import PlatformException
from tadas.om.opcontext import OpContext, Permission
from tadas.om.slack import SlackManagerInterface
from tadas.om.tasks import TasksManagerInterface
from tadas.om.tasks.types.filter import OpenTaskCursor, TaskFilter
from tadas.om.tasks.types.task import TaskScope
from tadas.om.tenancy import TenancyManagerInterface
from tadas.om.work.types.handler import WorkHandlerInterface, WorkParked
from tadas.om.work.types.work_item import DeleteAccountPayload, WorkItem

log = logging.getLogger(__name__)

PROVIDER_WAIT = timedelta(minutes=1)
"""How long an item waits for a provider that did not answer before it asks
again. No attempt is spent, so it asks until the provider answers."""

UNAVAILABLE = 503
"""The status of every "not right now": a provider out of reach, or with no
credential in this process."""

TASKS_PAGE = 100
"""Open tasks read a page at a time while their assignee is cleared."""


class DeleteAccountHandlerImpl(WorkHandlerInterface):
    REQUIRES: ClassVar[tuple[Permission, ...]] = (Permission.MANAGE_MEMBERS,)
    """The processor's side, the Slack app's removal, and the org's deletion
    all manage members."""

    def __init__(
        self,
        tenancy: TenancyManagerInterface,
        billing: BillingManagerInterface,
        slack: SlackManagerInterface,
        identity: IdentityProviderInterface,
    ) -> None:
        self._tenancy = tenancy
        self._billing = billing
        self._slack = slack
        self._identity = identity

    async def handle(self, ctx: OpContext, item: WorkItem) -> None:
        payload = DeleteAccountPayload.model_validate(item.payload)
        try:
            if payload.provider_user_id is not None:
                await self._identity.delete_user(payload.provider_user_id)
            await self._billing.close_account(ctx)
        except (InfraException, PlatformException) as error:
            # Read by status, as every boundary reads an exception: 503 is
            # "not right now", a provider unreachable or not configured here.
            if error.http_status != UNAVAILABLE:
                raise
            raise WorkParked(f"a provider is out of reach: {error}", PROVIDER_WAIT) from None
        # Slack's side is best effort, as every removal of the app is: a Slack
        # that cannot be reached leaves the app in the workspace, and the
        # token goes from Tadas either way.
        await self._slack.uninstall(ctx)
        await self._tenancy.delete_personal_org(ctx)
        log.info("the personal org %s of a deleted account is deleted", ctx.org_id)


class UnassignTasksHandlerImpl(WorkHandlerInterface):
    REQUIRES: ClassVar[tuple[Permission, ...]] = (Permission.READ, Permission.WRITE)
    """`get_open_tasks` reads; `update_task` writes."""

    def __init__(self, tasks: TasksManagerInterface) -> None:
        self._tasks = tasks

    async def handle(self, ctx: OpContext, item: WorkItem) -> None:
        # The item runs as the person who left, so `mine` is their list: the
        # tasks assigned to them, and the unassigned ones they made.
        mine = TaskFilter(scope=TaskScope.MINE, user_id=item.target_id)
        after: OpenTaskCursor | None = None
        cleared = 0
        while True:
            page = await self._tasks.get_open_tasks(ctx, mine, after, TASKS_PAGE)
            for task in page.items:
                if task.assignee_id != item.target_id:
                    continue
                # A task edited meanwhile is refused as stale, and the item's
                # retry reads it again.
                released = task.model_copy(update={"assignee_id": None})
                await self._tasks.update_task(ctx, released, task.version)
                cleared += 1
            if not page.has_more or not page.items:
                break
            last = page.items[-1]
            after = OpenTaskCursor(position=last.position, id=last.id)
        log.info("unassigned %d open tasks of a person who left org %s", cleared, ctx.org_id)
