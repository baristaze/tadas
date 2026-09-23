"""The integrations root that picks each provider from settings, and the
root over providers a caller already built. A twin is refused in a
deployed environment, the way the infra root refuses a local backend; the
caller says whether the environment is one, from the settings it booted
with."""

from datetime import timedelta

from tadas.integrations.exceptions import UnsafeIntegration
from tadas.integrations.identity import IdentityProviderInterface
from tadas.integrations.identity.absent import IdentityProviderAbsentImpl
from tadas.integrations.identity.twin import IdentityProviderTwinImpl
from tadas.integrations.identity.workos import IdentityProviderWorkOSImpl
from tadas.integrations.payments import PaymentsInterface
from tadas.integrations.payments.stripe import PaymentsStripeImpl
from tadas.integrations.payments.twin import TWIN_ENVIRONMENTS, PaymentsTwinImpl
from tadas.integrations.root import IntegrationsInterface
from tadas.integrations.settings import IntegrationsSettings, key_mode, mode_for


def refuse_unsafe(settings: IntegrationsSettings, environment: str, deployed: bool) -> None:
    """A twin in a deployed environment is refused at boot, naming the setting,
    and so is a payment processor's key whose mode is not the environment's."""
    if deployed and settings.identity_provider == "twin":
        raise UnsafeIntegration(
            f"TADAS_IDENTITY_PROVIDER=twin is refused when TADAS_ENVIRONMENT={environment}"
        )
    refuse_unsafe_payments(settings, environment)


def refuse_unsafe_payments(settings: IntegrationsSettings, environment: str) -> None:
    """The payment processor's twin anywhere but local and test, and a key
    whose mode is not the environment's: production takes a live key, every
    other environment a test key."""
    if settings.billing_backend == "twin":
        if environment not in TWIN_ENVIRONMENTS:
            raise UnsafeIntegration(
                f"TADAS_BILLING_BACKEND=twin is refused when TADAS_ENVIRONMENT={environment}"
            )
        return
    key = settings.stripe_org_key
    if key is None:
        return
    expected = mode_for(environment)
    found = key_mode(key.get_secret_value())
    if found != expected:
        raise UnsafeIntegration(
            f"TADAS_STRIPE_ORG_KEY is a {found or 'unrecognised'} key; "
            f"TADAS_ENVIRONMENT={environment} takes a {expected} key"
        )


def payments_for(settings: IntegrationsSettings, environment: str) -> PaymentsInterface:
    """The payment processor the settings name, after the boot's refusals."""
    refuse_unsafe_payments(settings, environment)
    if settings.billing_backend == "twin":
        return PaymentsTwinImpl(environment=environment)
    key, secret = settings.stripe_org_key, settings.stripe_webhook_secret
    return PaymentsStripeImpl(
        api_key=None if key is None else key.get_secret_value(),
        account_id=settings.stripe_account_id,
        webhook_secret=None if secret is None else secret.get_secret_value(),
        timeout=timedelta(seconds=settings.stripe_timeout_seconds),
    )


def absent_payments() -> PaymentsInterface:
    """The payment processor of a process that holds none: every call answers
    `billing_unavailable`, and every org keeps its plan."""
    return PaymentsStripeImpl(
        api_key=None, account_id=None, webhook_secret=None, timeout=timedelta(seconds=10)
    )


def identity_provider_for(settings: IntegrationsSettings) -> IdentityProviderInterface:
    if settings.identity_provider == "twin":
        return IdentityProviderTwinImpl()
    if settings.identity_provider == "workos":
        if not settings.workos_client_id:
            return IdentityProviderAbsentImpl("TADAS_WORKOS_CLIENT_ID is not set")
        if settings.workos_api_key is None:
            return IdentityProviderAbsentImpl("TADAS_WORKOS_API_KEY is not set")
        return IdentityProviderWorkOSImpl(
            client_id=settings.workos_client_id,
            api_key=settings.workos_api_key.get_secret_value(),
            base_url=settings.workos_base_url,
            timeout=timedelta(seconds=settings.workos_timeout_seconds),
        )
    return IdentityProviderAbsentImpl()


class IntegrationsOverImpl(IntegrationsInterface):
    """The root over providers already built: a test's twin, or the absent
    provider of a process that signs nobody in."""

    def __init__(
        self, identity: IdentityProviderInterface, payments: PaymentsInterface | None = None
    ) -> None:
        self._identity = identity
        self._payments = payments or absent_payments()

    def get_identity_provider(self) -> IdentityProviderInterface:
        return self._identity

    def get_payments(self) -> PaymentsInterface:
        return self._payments

    def describe(self) -> list[str]:
        return [self._identity.describe(), self._payments.describe()]

    async def start(self) -> None:
        await self._identity.start()
        await self._payments.start()

    async def close(self) -> None:
        await self._payments.close()
        await self._identity.close()


def absent_integrations(payments: PaymentsInterface | None = None) -> IntegrationsInterface:
    """The root of a process that signs nobody in; it holds no payment
    processor either unless the caller hands one in."""
    return IntegrationsOverImpl(IdentityProviderAbsentImpl(), payments)


class IntegrationsConfiguredImpl(IntegrationsOverImpl):
    def __init__(self, settings: IntegrationsSettings, environment: str, deployed: bool) -> None:
        refuse_unsafe(settings, environment, deployed)
        super().__init__(identity_provider_for(settings), payments_for(settings, environment))
