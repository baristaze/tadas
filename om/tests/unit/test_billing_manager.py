"""The billing manager over the memory roots and the payment processor's
twin: a checkout and the deliveries that follow it, each applied once and in
any order; a cancellation that holds the plan to its period's end; a
per-seat subscription that follows the members; an operator's grant; and
the levers of the tasks and tenancy managers that read the plan."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from contracts.second_factor import TOTP_KEY, SteppingClock, enrolled_operator

from tadas.infra.cache import CacheScope
from tadas.infra.impl.local import InfraLocalImpl
from tadas.integrations.identity.absent import IdentityProviderAbsentImpl
from tadas.integrations.impl.configured import IntegrationsOverImpl
from tadas.integrations.payments.deliveries import sign
from tadas.integrations.payments.twin import TWIN_WEBHOOK_SECRET, PaymentsTwinImpl
from tadas.om.base import new_id, utcnow
from tadas.om.billing.impl.manager import BillingManagerImpl, BillingOptions
from tadas.om.billing.impl.operator import BillingOperatorManagerImpl
from tadas.om.billing.types.account import SubscriptionStatus
from tadas.om.billing.types.plan import Plan
from tadas.om.exceptions import (
    InvalidCredential,
    NotAuthorized,
    NotFound,
    PlanLimitReached,
    SubscriptionExists,
    ValidationFailed,
)
from tadas.om.opcontext import (
    AppContext,
    AppType,
    OpContext,
    OperatorContext,
    OperatorRole,
    RequestContext,
    Role,
)
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.tasks.types.task import Task, TaskStatus
from tadas.om.tenancy.impl.manager import TenancyManagerImpl, TenancyOptions
from tadas.om.tenancy.impl.operator import TenancyOperatorManagerImpl, TenancyOperatorOptions
from tadas.om.work.types.work_item import WorkKind

APP = AppContext(type=AppType.PORTAL, version="portal@test")
SUCCESS, CANCEL = "http://portal.test/billing?done", "http://portal.test/billing?cancelled"


def request() -> RequestContext:
    return RequestContext(request_id=new_id(), app=APP)


class World:
    """One platform over the memory roots and the twin, with a clock the
    billing manager reads, so a period can pass."""

    def __init__(self, tmp_path: Path) -> None:
        self.storage = StorageMemoryImpl()
        self.twin = PaymentsTwinImpl(environment="test")
        self.now = utcnow()
        self.managers: Managers = build_managers(
            self.storage,
            InfraLocalImpl(tmp_path),
            TenancyOptions(totp_encryption_key=TOTP_KEY, dev_sign_in=True),
            integrations=IntegrationsOverImpl(IdentityProviderAbsentImpl(), self.twin),
        )
        self.billing = BillingManagerImpl(
            self.storage.get_billing_storage(),
            self.twin,
            self.managers.outbox,
            lambda: self.managers.tenancy,
            BillingOptions(),
            clock=lambda: self.now,
        )

    async def org(self, slug: str) -> OpContext:
        """A fresh org; the context is its owner's."""
        ctx, _ = await self.managers.tenancy.bootstrap(
            request(), slug.title(), slug, f"owner@{slug}.test", "Owner"
        )
        return ctx

    async def signed_in(self, email: str, org_id: UUID) -> OpContext:
        tenancy = self.managers.tenancy
        login = await tenancy.dev_sign_in(request(), email)
        identity = await tenancy.authenticate_login(request(), login.token)
        session = await tenancy.exchange_login(identity, org_id)
        return await tenancy.authenticate(request(), session.token)

    async def deliver(self, delivery: tuple[bytes, str]) -> bool:
        """What the webhook route and the worker do with one delivery."""
        verified = self.twin.verify_delivery(*delivery)
        org_id = await self.billing.org_of_delivery(request(), verified)
        assert org_id is not None
        ctx = await self.managers.tenancy.service_context(request(), org_id, new_id())
        return await self.billing.apply_delivery(ctx, verified)

    async def buy(self, ctx: OpContext, plan: Plan, seats: int = 1) -> str:
        """A checkout the customer completes; answers the subscription id."""
        start = await self.billing.start_checkout(ctx, plan, seats, "Acme", SUCCESS, CANCEL)
        assert await self.deliver(self.twin.complete_checkout(start.url))
        billing = await self.billing.get_billing(ctx)
        assert billing.account is not None and billing.account.subscription_id is not None
        return billing.account.subscription_id


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def make_task(ctx: OpContext, title: str) -> Task:
    now = utcnow()
    return Task(
        id=new_id(),
        created_at=now,
        updated_at=now,
        created_by=ctx.user_id,
        updated_by=ctx.user_id,
        title=title,
    )


# The checkout and the mirror.


async def test_an_org_starts_on_free_and_a_checkout_makes_its_customer_once(world: World) -> None:
    ctx = await world.org("acme")
    billing = await world.billing.get_billing(ctx)
    assert (billing.plan, billing.account) == (Plan.FREE, None)
    first = await world.billing.start_checkout(ctx, Plan.PRO, 1, "Acme", SUCCESS, CANCEL)
    again = await world.billing.start_checkout(ctx, Plan.TEAM, 1, "Acme", SUCCESS, CANCEL)
    assert first.url != again.url
    assert len(world.twin.customers) == 1
    account = (await world.billing.get_billing(ctx)).account
    assert account is not None and account.customer_id in world.twin.customers
    sessions = list(world.twin.sessions.values())
    assert [s["lookup_key"] for s in sessions] == ["tadas.pro.monthly", "tadas.team.monthly"]
    assert all(s["org_id"] == ctx.org_id for s in sessions)


async def test_max_starts_at_the_active_member_count_and_every_other_plan_at_one(
    world: World,
) -> None:
    ctx = await world.org("acme")
    await world.billing.start_checkout(ctx, Plan.MAX, 7, "Acme", SUCCESS, CANCEL)
    await world.billing.start_checkout(ctx, Plan.TEAM, 7, "Acme", SUCCESS, CANCEL)
    assert [s["quantity"] for s in world.twin.sessions.values()] == [7, 1]


async def test_free_is_not_bought_and_only_a_billing_manager_starts_a_checkout(
    world: World,
) -> None:
    ctx = await world.org("acme")
    with pytest.raises(ValidationFailed):
        await world.billing.start_checkout(ctx, Plan.FREE, 1, "Acme", SUCCESS, CANCEL)
    await world.managers.tenancy.add_member(request(), "acme", "bob@acme.test", "Bob", Role.MEMBER)
    bob = await world.signed_in("bob@acme.test", ctx.org_id)
    with pytest.raises(NotAuthorized):
        await world.billing.start_checkout(bob, Plan.PRO, 1, "Acme", SUCCESS, CANCEL)
    with pytest.raises(NotAuthorized):
        await world.billing.open_portal(bob, SUCCESS)
    with pytest.raises(NotAuthorized):
        await world.billing.cancel(bob)
    # A member reads the plan like anyone in the org.
    assert (await world.billing.get_billing(bob)).plan is Plan.FREE


async def test_a_completed_checkout_puts_the_org_on_its_plan(world: World) -> None:
    ctx = await world.org("acme")
    subscription = await world.buy(ctx, Plan.PRO)
    billing = await world.billing.get_billing(ctx)
    assert billing.plan is Plan.PRO and billing.paid_plan is Plan.PRO
    assert billing.account is not None
    assert billing.account.status is SubscriptionStatus.ACTIVE
    assert billing.account.subscription_id == subscription
    with pytest.raises(SubscriptionExists):
        await world.billing.start_checkout(ctx, Plan.TEAM, 1, "Acme", SUCCESS, CANCEL)
    assert (await world.billing.open_portal(ctx, SUCCESS)).startswith("https://billing.twin")


async def test_the_same_delivery_twice_changes_the_org_once(world: World) -> None:
    ctx = await world.org("acme")
    subscription = await world.buy(ctx, Plan.PRO)
    delivery = world.twin.subscription_event("customer.subscription.updated", subscription)
    world.twin.move(subscription, status="past_due")
    assert await world.deliver(delivery) is True
    once = await world.billing.get_billing(ctx)
    assert once.account is not None and once.account.status is SubscriptionStatus.PAST_DUE
    world.twin.move(subscription, status="unpaid")
    assert await world.deliver(delivery) is False
    twice = await world.billing.get_billing(ctx)
    assert twice.account == once.account


async def test_deliveries_out_of_order_converge_on_what_the_processor_holds(
    world: World,
) -> None:
    ctx = await world.org("acme")
    subscription = await world.buy(ctx, Plan.PRO)
    created = world.twin.subscription_event("customer.subscription.created", subscription)
    world.twin.move(subscription, cancel_at_period_end=True)
    updated = world.twin.subscription_event("customer.subscription.updated", subscription)
    # The later event arrives first, then the earlier one: both read the
    # subscription again, so the mirror ends where the processor is.
    assert await world.deliver(updated)
    assert await world.deliver(created)
    account = (await world.billing.get_billing(ctx)).account
    assert account is not None and account.cancel_at_period_end is True


async def test_an_invoice_that_failed_and_one_that_was_paid_move_the_status(
    world: World,
) -> None:
    ctx = await world.org("acme")
    subscription = await world.buy(ctx, Plan.TEAM)
    world.twin.move(subscription, status="past_due")
    assert await world.deliver(world.twin.invoice_event("invoice.payment_failed", subscription))
    failed = await world.billing.get_billing(ctx)
    assert failed.account is not None and failed.account.status is SubscriptionStatus.PAST_DUE
    assert failed.plan is Plan.TEAM  # the processor is still retrying
    world.twin.move(subscription, status="active")
    assert await world.deliver(world.twin.invoice_event("invoice.paid", subscription))
    paid = await world.billing.get_billing(ctx)
    assert paid.account is not None and paid.account.status is SubscriptionStatus.ACTIVE


async def test_a_delivery_that_names_another_orgs_customer_changes_nothing(
    world: World,
) -> None:
    acme, other = await world.org("acme"), await world.org("other")
    subscription = await world.buy(acme, Plan.PRO)
    await world.billing.start_checkout(other, Plan.PRO, 1, "Other", SUCCESS, CANCEL)
    payload, _ = world.twin.subscription_event("customer.subscription.updated", subscription)
    forged = payload.replace(str(acme.org_id).encode(), str(other.org_id).encode())
    await world.deliver((forged, sign(forged, TWIN_WEBHOOK_SECRET)))
    assert (await world.billing.get_billing(other)).plan is Plan.FREE


async def test_a_late_word_about_an_ended_subscription_leaves_the_new_one(world: World) -> None:
    ctx = await world.org("acme")
    old = await world.buy(ctx, Plan.PRO)
    world.twin.move(old, status="canceled")
    assert await world.deliver(world.twin.subscription_event("customer.subscription.deleted", old))
    assert (await world.billing.get_billing(ctx)).plan is Plan.FREE
    new = await world.buy(ctx, Plan.TEAM)
    late = world.twin.subscription_event("customer.subscription.updated", old)
    assert await world.deliver(late)
    billing = await world.billing.get_billing(ctx)
    assert billing.plan is Plan.TEAM
    assert billing.account is not None and billing.account.subscription_id == new


# Cancellation.


async def test_a_cancelled_plan_holds_until_the_period_ends_then_the_org_is_on_free(
    world: World,
) -> None:
    ctx = await world.org("acme")
    subscription = await world.buy(ctx, Plan.PRO)
    cancelled = await world.billing.cancel(ctx)
    end = world.twin.subscriptions[subscription]["current_period_end"]
    assert world.twin.subscriptions[subscription]["cancel_at_period_end"] is True
    assert (cancelled.plan, cancelled.ends_at, cancelled.plan_after) == (Plan.PRO, end, Plan.FREE)
    world.now = end + timedelta(seconds=1)
    assert (await world.billing.get_billing(ctx)).plan is Plan.FREE
    # The processor says so too, a moment later; the mirror agrees.
    world.twin.end_period(subscription)
    assert await world.deliver(
        world.twin.subscription_event("customer.subscription.deleted", subscription)
    )
    ended = await world.billing.get_billing(ctx)
    assert ended.plan is Plan.FREE
    assert ended.account is not None and ended.account.status is SubscriptionStatus.CANCELED


async def test_a_cancellation_taken_back_renews(world: World) -> None:
    ctx = await world.org("acme")
    await world.buy(ctx, Plan.PRO)
    await world.billing.cancel(ctx)
    resumed = await world.billing.resume(ctx)
    assert (resumed.plan, resumed.ends_at, resumed.plan_after) == (Plan.PRO, None, None)


async def test_an_org_with_nothing_to_cancel_is_told_so(world: World) -> None:
    ctx = await world.org("acme")
    with pytest.raises(NotFound):
        await world.billing.cancel(ctx)
    with pytest.raises(NotFound):
        await world.billing.open_portal(ctx, SUCCESS)


# The seats of a per-seat plan.


async def test_a_max_subscription_follows_the_member_count_once_per_change(
    world: World,
) -> None:
    ctx = await world.org("acme")
    subscription = await world.buy(ctx, Plan.MAX, seats=1)
    await world.billing.sync_seats(ctx, 11, "item-1-11")
    await world.billing.sync_seats(ctx, 11, "item-1-11")
    await world.billing.sync_seats(ctx, 11, "item-2-11")  # already there: no change
    assert world.twin.quantity_changes == [(subscription, 11)]
    billing = await world.billing.get_billing(ctx)
    assert billing.account is not None and billing.account.quantity == 11


async def test_seats_on_a_plan_not_per_seat_change_nothing(world: World) -> None:
    ctx = await world.org("acme")
    await world.buy(ctx, Plan.TEAM)
    await world.billing.sync_seats(ctx, 4, "item-1-4")
    assert world.twin.quantity_changes == []


async def test_removing_a_member_of_a_max_org_asks_for_the_seat_count_in_its_commit(
    world: World,
) -> None:
    ctx = await world.org("acme")
    await world.buy(ctx, Plan.MAX)
    _, bob, _ = await world.managers.tenancy.add_member(
        request(), "acme", "bob@acme.test", "Bob", Role.MEMBER
    )
    await world.managers.tenancy.remove_member(ctx, bob.id)
    claimed = await world.storage.get_work_storage().claim_next(
        "default", [WorkKind.SYNC_SEATS], "w", timedelta(seconds=30)
    )
    assert claimed is not None
    org_id, item = claimed
    assert (org_id, item.kind, item.target_id) == (ctx.org_id, WorkKind.SYNC_SEATS, ctx.org_id)


async def test_removing_a_member_of_a_team_org_asks_for_nothing(world: World) -> None:
    ctx = await world.org("acme")
    await world.buy(ctx, Plan.TEAM)
    _, bob, _ = await world.managers.tenancy.add_member(
        request(), "acme", "bob@acme.test", "Bob", Role.MEMBER
    )
    await world.managers.tenancy.remove_member(ctx, bob.id)
    assert (
        await world.storage.get_work_storage().claim_next(
            "default", [WorkKind.SYNC_SEATS], "w", timedelta(seconds=30)
        )
        is None
    )


async def test_the_sweep_purges_old_delivery_marks(world: World) -> None:
    ctx = await world.org("acme")
    await world.buy(ctx, Plan.PRO)
    sweep = await world.managers.tenancy.service_context(request(), ctx.org_id, new_id())
    assert await world.billing.purge_deleted(sweep) == 0
    world.now += timedelta(days=31)
    assert await world.billing.purge_deleted(sweep) == 1


# The levers.


async def test_the_eleventh_active_task_on_free_is_refused_and_pro_has_no_bound(
    world: World,
) -> None:
    ctx = await world.org("acme")
    tasks = world.managers.tasks
    made = [await tasks.create_task(ctx, make_task(ctx, f"task {n}")) for n in range(10)]
    with pytest.raises(PlanLimitReached) as refused:
        await tasks.create_task(ctx, make_task(ctx, "one too many"))
    assert (refused.value.lever, refused.value.limit, refused.value.suggested_plan) == (
        "active_tasks",
        10,
        "pro",
    )
    # Done or deleted, a task is not active: the room comes back.
    first = made[0]
    await tasks.update_task(
        ctx, first.model_copy(update={"status": TaskStatus.DONE}), first.version
    )
    done = await tasks.get_task(ctx, first.id)
    another = await tasks.create_task(ctx, make_task(ctx, "in its place"))
    # Reopening the done one would take the org past its bound again.
    with pytest.raises(PlanLimitReached):
        await tasks.update_task(ctx, done.model_copy(update={"status": TaskStatus.OPEN}), 2)
    await tasks.delete_task(ctx, another.id, another.version)
    assert await tasks.count_active_tasks(ctx) == 9
    await world.buy(ctx, Plan.PRO)
    for n in range(5):
        await tasks.create_task(ctx, make_task(ctx, f"more {n}"))
    assert await tasks.count_active_tasks(ctx) == 14


async def test_the_first_api_key_on_free_is_refused_and_a_kept_key_is_refused_after_a_downgrade(
    world: World,
) -> None:
    ctx = await world.org("acme")
    owner = await world.signed_in("owner@acme.test", ctx.org_id)
    tenancy = world.managers.tenancy
    with pytest.raises(PlanLimitReached) as refused:
        await tenancy.create_api_key(owner, "ci", Role.MEMBER)
    assert (refused.value.lever, refused.value.suggested_plan) == ("api_keys", "pro")
    subscription = await world.buy(ctx, Plan.PRO)
    issued = await tenancy.create_api_key(owner, "ci", Role.MEMBER)
    assert (await tenancy.authenticate(request(), issued.key)).org_id == ctx.org_id
    world.twin.move(subscription, status="canceled")
    await world.deliver(
        world.twin.subscription_event("customer.subscription.deleted", subscription)
    )
    # Kept, and refused while the org is on a plan without keys.
    with pytest.raises(PlanLimitReached):
        await tenancy.authenticate(request(), issued.key)
    listed = await tenancy.get_api_keys(owner, None, 10)
    assert [k.id for k in listed.items] == [issued.api_key.id]
    await world.buy(ctx, Plan.TEAM)
    assert (await tenancy.authenticate(request(), issued.key)).org_id == ctx.org_id
    with pytest.raises(InvalidCredential):
        await tenancy.authenticate(request(), "not-a-key")


# The operator plane.


class Plane:
    """The operator's side over the same storage as the world's."""

    def __init__(self, world: World, tmp_path: Path) -> None:
        self.clock = SteppingClock()
        storage = world.storage
        self.tenancy = TenancyManagerImpl(
            storage.get_tenancy_storage(),
            world.managers.outbox,
            InfraLocalImpl(tmp_path / "plane").get_cache(CacheScope.REALTIME_TICKET),
            TenancyOptions(totp_encryption_key=TOTP_KEY, dev_sign_in=True),
            self.clock,
            identity_provider=IdentityProviderAbsentImpl(),
            entitlements=world.managers.billing,
        )
        self.operator = TenancyOperatorManagerImpl(
            storage.get_tenancy_storage(),
            storage.get_tasks_storage(),
            storage.get_event_storage(),
            world.managers.outbox,
            TenancyOperatorOptions(totp_encryption_key=TOTP_KEY),
            self.clock,
            billing=storage.get_billing_storage(),
        )
        self.billing = BillingOperatorManagerImpl(
            storage.get_billing_storage(), storage.get_tenancy_storage(), world.managers.outbox
        )

    async def admit(self, role: OperatorRole, email: str) -> OperatorContext:
        await self.tenancy.bootstrap(
            request(), email, email.split("@")[0], email, "Op", operator_role=role
        )
        admin, _ = await enrolled_operator(self.tenancy, self.operator, self.clock, email)
        return admin


async def test_an_operator_grants_a_plan_and_takes_it_back(world: World, tmp_path: Path) -> None:
    plane = Plane(world, tmp_path)
    writer = await plane.admit(OperatorRole.WRITE, "root@example.test")
    reader = await plane.admit(OperatorRole.READ, "sup@example.test")
    ctx = await world.org("acme")
    with pytest.raises(NotAuthorized):
        await plane.billing.comp_plan(reader, ctx.org_id, Plan.MAX)
    granted = await plane.billing.comp_plan(writer, ctx.org_id, Plan.MAX)
    assert (granted.plan, granted.comped_plan, granted.paid_plan) == (Plan.MAX, Plan.MAX, None)
    assert (await world.billing.get_billing(ctx)).plan is Plan.MAX
    assert (await plane.billing.get_billing(reader, ctx.org_id)).plan is Plan.MAX
    taken = await plane.billing.comp_plan(writer, ctx.org_id, None)
    assert taken.plan is Plan.FREE


async def test_an_operator_adding_a_member_past_the_seats_is_refused(
    world: World, tmp_path: Path
) -> None:
    plane = Plane(world, tmp_path)
    writer = await plane.admit(OperatorRole.WRITE, "root@example.test")
    org = await plane.operator.create_org(writer, "Team", "team", "ann@team.test", "Ann")

    async def add(n: int) -> None:
        await plane.operator.add_member(writer, org.id, f"m{n}@team.test", f"M{n}", Role.MEMBER)

    with pytest.raises(PlanLimitReached) as refused:
        await add(1)
    assert (refused.value.plan, refused.value.limit, refused.value.suggested_plan) == (
        "free",
        1,
        "team",
    )
    await plane.billing.comp_plan(writer, org.id, Plan.TEAM)
    for n in range(1, 5):
        await add(n)
    with pytest.raises(PlanLimitReached) as sixth:
        await add(5)
    assert (sixth.value.limit, sixth.value.suggested_plan) == (5, "max")
    await plane.billing.comp_plan(writer, org.id, Plan.MAX)
    await add(5)
    # On a per-seat plan the add asks for the seat count in its commit; a
    # grant has no subscription, so the handler will find nothing to change.
    claimed = await world.storage.get_work_storage().claim_next(
        "default", [WorkKind.SYNC_SEATS], "w", timedelta(seconds=30)
    )
    assert claimed is not None and claimed[0] == org.id


async def test_the_seed_grants_its_own_team_a_plan_and_a_tenants_credential_cannot(
    world: World,
) -> None:
    seeded = await world.org("acme")  # the context `bootstrap` produced: internal, the owner
    granted = await world.billing.grant_seeded_plan(seeded, Plan.TEAM)
    assert (granted.plan, granted.comped_plan, granted.paid_plan) == (Plan.TEAM, Plan.TEAM, None)
    owner = await world.signed_in("owner@acme.test", seeded.org_id)
    with pytest.raises(NotAuthorized):
        await world.billing.grant_seeded_plan(owner, Plan.MAX)
    assert (await world.billing.get_billing(owner)).plan is Plan.TEAM
