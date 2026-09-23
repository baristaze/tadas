"""The providers' half of a process's settings, and the refusals a process
makes at boot: a twin outside a local environment, and a processor key
whose mode is not the environment's. Production takes a live key and
every other environment a test key, so a laptop or staging can never move
real money and production can never answer with a sandbox."""

from datetime import timedelta
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tadas.infra.impl.settings import ENV_FILE
from tadas.integrations.exceptions import UnsafeProviderConfiguration
from tadas.integrations.payments import PaymentsInterface
from tadas.integrations.payments.stripe import PaymentsStripeImpl
from tadas.integrations.payments.twin import TWIN_ENVIRONMENTS, PaymentsTwinImpl

LIVE_PREFIXES = ("sk_live_", "rk_live_", "sk_org_live_", "rk_org_live_")
TEST_PREFIXES = ("sk_test_", "rk_test_", "sk_org_test_", "rk_org_test_")


def key_mode(key: str) -> Literal["live", "test"] | None:
    """What a processor key's prefix says it moves: real money or none."""
    if key.startswith(LIVE_PREFIXES):
        return "live"
    if key.startswith(TEST_PREFIXES):
        return "test"
    return None


def mode_for(environment: str) -> Literal["live", "test"]:
    return "live" if environment == "production" else "test"


class IntegrationsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TADAS_", env_file=ENV_FILE, extra="ignore")

    environment: str = "local"

    # The payment processor: the twin in memory (tests, one process on a
    # laptop), or Stripe. The twin is refused outside local and test.
    billing_backend: Literal["twin", "stripe"] = "twin"
    # The account every call names in `Stripe-Context`. Not a secret: each
    # environment commits its own.
    stripe_account_id: str | None = None
    # The key, and the signing secret of the endpoint the processor delivers
    # to. Both are process credentials, injected at start; empty or "off"
    # leaves billing unconfigured, which answers 503 and keeps every org on
    # its plan.
    stripe_org_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_timeout_seconds: float = 10.0

    @field_validator("stripe_org_key", "stripe_webhook_secret", mode="before")
    @classmethod
    def _off_is_none(cls, value: object) -> object:
        """The cloud secret starts as "off", as the error tracker's DSN does."""
        if isinstance(value, str) and value.strip().lower() in ("", "off"):
            return None
        return value

    @field_validator("stripe_account_id", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


def refuse_unsafe_payments(settings: IntegrationsSettings) -> None:
    """The boot's refusals, each naming the setting."""
    if settings.billing_backend == "twin":
        if settings.environment not in TWIN_ENVIRONMENTS:
            raise UnsafeProviderConfiguration(
                "TADAS_BILLING_BACKEND=twin is refused "
                f"when TADAS_ENVIRONMENT={settings.environment}"
            )
        return
    key = settings.stripe_org_key
    if key is None:
        return
    expected = mode_for(settings.environment)
    found = key_mode(key.get_secret_value())
    if found != expected:
        raise UnsafeProviderConfiguration(
            f"TADAS_STRIPE_ORG_KEY is a {found or 'unrecognised'} key; "
            f"TADAS_ENVIRONMENT={settings.environment} takes a {expected} key"
        )


def build_payments(settings: IntegrationsSettings) -> PaymentsInterface:
    """The payments client the settings name, after the boot's refusals."""
    refuse_unsafe_payments(settings)
    if settings.billing_backend == "twin":
        return PaymentsTwinImpl(environment=settings.environment)
    return PaymentsStripeImpl(
        api_key=None
        if settings.stripe_org_key is None
        else settings.stripe_org_key.get_secret_value(),
        account_id=settings.stripe_account_id,
        webhook_secret=(
            None
            if settings.stripe_webhook_secret is None
            else settings.stripe_webhook_secret.get_secret_value()
        ),
        timeout=timedelta(seconds=settings.stripe_timeout_seconds),
    )
