"""The settings the integrations read, mixed into a process's one settings
object; nothing below reads the environment."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tadas.infra.impl.settings import ENV_FILE


class IntegrationsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TADAS_", env_file=ENV_FILE, extra="ignore")

    # Which identity provider signs people in: WorkOS, its twin (local only,
    # refused at boot anywhere else), or none, which refuses every sign-in
    # through a provider and is what a process that signs nobody in holds.
    identity_provider: Literal["workos", "twin", "none"] = "none"
    # The Tadas App application's client id. Not a secret: it is in every
    # authorization URL a browser sees. Each environment names its own
    # application in its deployment config.
    workos_client_id: str = ""
    # The Tadas App application's API key, never the environment's: the
    # exchange's client secret and the management calls' key. A process
    # credential, injected at start from the secret store in a deployed
    # environment and read from the environment locally. Empty or "off"
    # means not set, and WorkOS is then not configured: the process starts,
    # says so, and every sign-in through it answers 503.
    workos_api_key: SecretStr | None = Field(default=None, repr=False)
    workos_base_url: str = "https://api.workos.com"
    workos_timeout_seconds: float = Field(default=10.0, gt=0)

    # The payment processor: Stripe, or its twin in memory (the tests, and
    # one process on a laptop), which is refused outside local and test.
    # Stripe with no key is unconfigured: every org keeps its plan.
    billing_backend: Literal["twin", "stripe"] = "stripe"
    # The account every call names in `Stripe-Context`. Not a secret: each
    # environment commits its own.
    stripe_account_id: str | None = None
    # The key, and the signing secret of the endpoint the processor delivers
    # to. Both are process credentials, injected at start; empty or "off"
    # leaves billing unconfigured, which answers 503 and keeps every org on
    # its plan.
    stripe_org_key: SecretStr | None = Field(default=None, repr=False)
    stripe_webhook_secret: SecretStr | None = Field(default=None, repr=False)
    stripe_timeout_seconds: float = Field(default=10.0, gt=0)

    @field_validator("workos_api_key")
    @classmethod
    def _key_off_is_none(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or value.get_secret_value().strip().lower() in ("", "off"):
            return None
        return value

    @field_validator("stripe_org_key", "stripe_webhook_secret", mode="before")
    @classmethod
    def _stripe_off_is_none(cls, value: object) -> object:
        """The cloud secret starts as "off", as the error tracker's DSN does."""
        if isinstance(value, str) and value.strip().lower() in ("", "off"):
            return None
        return value

    @field_validator("stripe_account_id", mode="before")
    @classmethod
    def _empty_account_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


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
    """Production takes a live key and every other environment a test key, so
    a laptop or staging never moves real money and production never answers
    with a sandbox."""
    return "live" if environment == "production" else "test"
