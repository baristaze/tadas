import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from tadas.integrations.payments import PaymentsInterface
from tadas.integrations.payments.types import ProviderDelivery, ProviderSubscription
from tadas.om.base import Platform, new_id, utcnow
from tadas.om.billing.manager import BillingManagerInterface
from tadas.om.billing.rules import (
    LIVE_STATUSES,
    PLAN_PRICES,
    effective_plan,
    ends_at,
    limits_of,
    paid_plan,
    seats_metered,
    should_mirror,
)
from tadas.om.billing.storage import BillingStorageInterface
from tadas.om.billing.types.account import BillingAccount, status_of
from tadas.om.billing.types.billing import Billing, CheckoutStart, Entitlements
from tadas.om.billing.types.delivery import BillingDelivery
from tadas.om.billing.types.plan import Plan
from tadas.om.exceptions import (
    NotAuthorized,
    NotFound,
    SubscriptionExists,
    TenantMismatch,
    ValidationFailed,
)
from tadas.om.opcontext import (
    CredentialKind,
    OpContext,
    Permission,
    ProvenanceScope,
    RequestContext,
    Role,
)
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import OutboxRow, outbox_row
from tadas.om.tenancy import TenancyManagerInterface

log = logging.getLogger(__name__)

ACCOUNT_UPDATED = "billing.account.updated"
ACCOUNT_CREATED = "billing.account.created"


class BillingOptions(Platform):
    retention: timedelta = timedelta(days=30)
    """A delivery's mark is kept this long: past every retry the processor
    makes of one event, which stops after three days."""


def billing_of(account: BillingAccount | None, now: datetime) -> Billing:
    """The answer every read and every write of this namespace gives."""
    plan = effective_plan(account, now)
    paid = paid_plan(account, now)
    comped = account.comped_plan if account else None
    ending = ends_at(account, now)
    return Billing(
        plan=plan,
        limits=limits_of(plan),
        paid_plan=paid,
        comped_plan=comped,
        ends_at=ending,
        plan_after=(comped or Plan.FREE) if ending is not None else None,
        account=account,
    )


def mirrored(
    account: BillingAccount, subscription: ProviderSubscription, actor: UUID, now: datetime
) -> BillingAccount:
    """The account with the subscription as the processor holds it now."""
    return account.model_copy(
        update={
            "subscription_id": subscription.id,
            "price_lookup_key": subscription.price_lookup_key,
            "status": status_of(subscription.status),
            "current_period_end": subscription.current_period_end,
            "cancel_at_period_end": subscription.cancel_at_period_end,
            "quantity": subscription.quantity,
            "synced_at": now,
            "updated_at": now,
            "updated_by": actor,
        }
    )


class BillingManagerImpl(BillingManagerInterface):
    def __init__(
        self,
        storage: BillingStorageInterface,
        payments: PaymentsInterface,
        relay: OutboxRelayInterface,
        tenancy: Callable[[], TenancyManagerInterface],
        options: BillingOptions,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        """`tenancy` is a provider and not the manager itself: the tenancy
        manager asks this one for an org's entitlements, and this one asks it
        whether a tenant is past its retention, so the root binds the edge at
        call time."""
        self._storage = storage
        self._payments = payments
        self._relay = relay
        self._tenancy = tenancy
        self._options = options
        self._clock = clock

    async def get_entitlements(self, ctx: OpContext) -> Entitlements:
        ctx.require(Permission.READ)
        plan = effective_plan(await self._storage.read_account(ctx.org_id), self._clock())
        return Entitlements(plan=plan, limits=limits_of(plan))

    async def get_billing(self, ctx: OpContext) -> Billing:
        ctx.require(Permission.READ)
        return billing_of(await self._storage.read_account(ctx.org_id), self._clock())

    async def start_checkout(
        self,
        ctx: OpContext,
        plan: Plan,
        seats: int,
        org_name: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutStart:
        ctx.require(Permission.MANAGE_BILLING)
        lookup_key = PLAN_PRICES[plan].lookup_key
        if lookup_key is None:
            raise ValidationFailed(f"the {plan.value} plan is not bought")
        account = await self._storage.read_account(ctx.org_id)
        paid = paid_plan(account, self._clock())
        if paid is not None:
            raise SubscriptionExists(
                f"the org pays for {paid.value}; change the plan in the billing portal"
            )
        if account is None or account.customer_id is None:
            customer_id = await self._payments.create_customer(ctx.org_id, org_name)
            account = await self._with_customer(ctx, account, customer_id)
        assert account.customer_id is not None
        url = await self._payments.create_checkout(
            customer_id=account.customer_id,
            org_id=ctx.org_id,
            lookup_key=lookup_key,
            quantity=max(1, seats) if seats_metered(plan) else 1,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        log.info("org %s started a checkout for %s", ctx.org_id, plan.value)
        return CheckoutStart(url=url)

    async def open_portal(self, ctx: OpContext, return_url: str) -> str:
        ctx.require(Permission.MANAGE_BILLING)
        account = await self._storage.read_account(ctx.org_id)
        if account is None or account.customer_id is None:
            raise NotFound("the org has no billing account yet; choose a plan first")
        return await self._payments.create_portal_session(account.customer_id, return_url)

    async def cancel(self, ctx: OpContext) -> Billing:
        return await self._set_cancel(ctx, True)

    async def resume(self, ctx: OpContext) -> Billing:
        return await self._set_cancel(ctx, False)

    async def _set_cancel(self, ctx: OpContext, cancel: bool) -> Billing:
        ctx.require(Permission.MANAGE_BILLING)
        account = await self._storage.read_account(ctx.org_id)
        now = self._clock()
        if account is None or account.subscription_id is None or paid_plan(account, now) is None:
            raise NotFound("the org has no paid plan to change")
        subscription = await self._payments.set_cancel_at_period_end(
            account.subscription_id, cancel
        )
        updated = mirrored(account, subscription, ctx.user_id, now)
        await self._write(ctx, updated)
        log.info("org %s set its plan to %s", ctx.org_id, "end" if cancel else "renew")
        return billing_of(updated, now)

    async def org_of_delivery(
        self, rctx: RequestContext, delivery: ProviderDelivery
    ) -> UUID | None:
        if delivery.org_hint is not None:
            return delivery.org_hint
        if delivery.customer_id is not None:
            return await self._payments.read_customer_org(delivery.customer_id)
        return None

    async def apply_delivery(self, ctx: OpContext, delivery: ProviderDelivery) -> bool:
        ctx.require(Permission.WRITE)
        mark = BillingDelivery(
            id=delivery.idempotency_key,
            created_at=self._clock(),
            event_id=delivery.event_id,
            event_type=delivery.event_type,
        )
        if await self._storage.read_delivery(ctx.org_id, mark.id) is not None:
            return False
        account = await self._storage.read_account(ctx.org_id)
        now = self._clock()
        if account is None or account.customer_id is None:
            log.warning(
                "delivery %s names org %s, which has no customer here; nothing to mirror",
                delivery.event_id,
                ctx.org_id,
            )
            return False
        if delivery.customer_id is not None and delivery.customer_id != account.customer_id:
            log.warning(
                "delivery %s names customer %s, not org %s's; nothing to mirror",
                delivery.event_id,
                delivery.customer_id,
                ctx.org_id,
            )
            return await self._storage.write_account(ctx.org_id, account, (), mark)
        updated = account
        if delivery.subscription_id is not None:
            subscription = await self._payments.read_subscription(delivery.subscription_id)
            if subscription is not None and self._follows(account, subscription):
                updated = mirrored(account, subscription, ctx.user_id, now)
        rows = self._rows(ctx, updated) if updated is not account else ()
        applied = await self._storage.write_account(ctx.org_id, updated, rows, mark)
        if applied:
            for row in rows:
                await self._relay.relay(ctx.org_id, row)
            log.info(
                "applied %s %s to org %s",
                delivery.event_type,
                delivery.event_id,
                ctx.org_id,
            )
        return applied

    @staticmethod
    def _follows(account: BillingAccount, subscription: ProviderSubscription) -> bool:
        """The subscription is the org's own, and the one the mirror follows."""
        if subscription.customer_id != account.customer_id:
            log.warning(
                "subscription %s is not customer %s's; not mirrored",
                subscription.id,
                account.customer_id,
            )
            return False
        live = status_of(subscription.status) in LIVE_STATUSES
        return should_mirror(account, subscription.id, live)

    async def sync_seats(self, ctx: OpContext, seats: int, idempotency_key: str) -> Billing:
        ctx.require(Permission.MANAGE_MEMBERS)
        account = await self._storage.read_account(ctx.org_id)
        now = self._clock()
        paid = paid_plan(account, now)
        if account is None or account.subscription_id is None or paid is None:
            return billing_of(account, now)
        if not seats_metered(paid):
            return billing_of(account, now)
        wanted = max(1, seats)
        current = await self._payments.read_subscription(account.subscription_id)
        if current is None:
            return billing_of(account, now)
        if current.quantity != wanted:
            current = await self._payments.set_quantity(current.id, wanted, idempotency_key)
            log.info("org %s now pays for %d seats", ctx.org_id, wanted)
        updated = mirrored(account, current, ctx.user_id, now)
        await self._write(ctx, updated)
        return billing_of(updated, now)

    async def grant_seeded_plan(self, ctx: OpContext, plan: Plan) -> Billing:
        ctx.require(Permission.MANAGE_BILLING)
        if ctx.credential_kind is not CredentialKind.INTERNAL or ctx.role is not Role.OWNER:
            raise NotAuthorized("a plan is granted by an operator; the seed grants its own org")
        now = self._clock()
        account = await self._storage.read_account(ctx.org_id)
        grant = None if plan is Plan.FREE else plan
        if account is None:
            created = BillingAccount(
                id=new_id(),
                created_at=now,
                updated_at=now,
                created_by=ctx.user_id,
                updated_by=ctx.user_id,
                comped_plan=grant,
            )
            rows = (outbox_row(ctx, ACCOUNT_CREATED, created.id, {}),)
            if await self._storage.create_account(ctx.org_id, created, rows):
                for row in rows:
                    await self._relay.relay(ctx.org_id, row)
                return billing_of(created, now)
            account = await self._storage.read_account(ctx.org_id)
            if account is None:
                raise TenantMismatch(f"billing_accounts {created.id} is not in {ctx.org_id}")
        updated = account.model_copy(
            update={"comped_plan": grant, "updated_at": now, "updated_by": ctx.user_id}
        )
        await self._write(ctx, updated)
        return billing_of(updated, now)

    async def purge_deleted(self, ctx: OpContext) -> int:
        ctx.require(Permission.WRITE)
        if await self._tenancy().tenant_expired(ctx):
            return await self._storage.purge_tenant(ctx.org_id)
        return await self._storage.purge_deliveries(
            ctx.org_id, self._clock() - self._options.retention
        )

    async def _with_customer(
        self, ctx: OpContext, account: BillingAccount | None, customer_id: str
    ) -> BillingAccount:
        """The org's account, now naming its customer: created the first time,
        or, when a grant made the account first, updated with it."""
        now = self._clock()
        if account is not None:
            updated = account.model_copy(
                update={"customer_id": customer_id, "updated_at": now, "updated_by": ctx.user_id}
            )
            await self._write(ctx, updated)
            return updated
        created = BillingAccount(
            id=new_id(),
            created_at=now,
            updated_at=now,
            created_by=ctx.user_id,
            updated_by=ctx.user_id,
            customer_id=customer_id,
        )
        rows = (outbox_row(ctx, ACCOUNT_CREATED, created.id, {}),)
        if await self._storage.create_account(ctx.org_id, created, rows):
            for row in rows:
                await self._relay.relay(ctx.org_id, row)
            return created
        # Another start raced this one and made the account first; the
        # processor's idempotency key made them one customer.
        stored = await self._storage.read_account(ctx.org_id)
        if stored is None:
            raise TenantMismatch(f"billing_accounts {created.id} is not in {ctx.org_id}")
        if stored.customer_id is None:
            return await self._with_customer(ctx, stored, customer_id)
        return stored

    @staticmethod
    def _rows(ctx: ProvenanceScope, account: BillingAccount) -> tuple[OutboxRow, ...]:
        return (outbox_row(ctx, ACCOUNT_UPDATED, account.id, {}),)

    async def _write(self, ctx: OpContext, account: BillingAccount) -> None:
        rows = self._rows(ctx, account)
        await self._storage.write_account(ctx.org_id, account, rows)
        for row in rows:
            await self._relay.relay(ctx.org_id, row)
