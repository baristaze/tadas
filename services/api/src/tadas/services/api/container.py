"""Every process boots the same way: settings, then logging, the process name,
the trust store, error reporting, and tracing, then storage, infra, the managers,
and the services, in that order. Routers resolve them per request from this one
object."""

import logging
from datetime import timedelta

from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.observability import (
    configure_error_reporting,
    configure_logging,
    configure_tracing,
    name_process,
)
from tadas.infra.root import InfraInterface
from tadas.infra.trust import install_trust_store
from tadas.integrations.payments import PaymentsInterface
from tadas.integrations.settings import build_payments
from tadas.om.root import Managers, TenancyOperatorOptions, TenancyOptions, build_managers
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.om.storage.impl.postgres import StoragePostgresImpl
from tadas.om.storage.root import StorageInterface
from tadas.services.api.gateway.ratelimit import RateLimit, RateLimitOptions
from tadas.services.api.services import ServicesInterface
from tadas.services.api.services.impl.root import build_services
from tadas.services.api.settings import ApiSettings

log = logging.getLogger(__name__)

_booted = False


def boot(settings: ApiSettings) -> None:
    """Settings first, then logging, the process name, the trust store, error
    reporting, and tracing. Every entry point calls it before it builds a
    container; it runs once per process.

    Naming the process is a step of its own, second: every line this boot
    writes carries the service and the environment, and a boot that configures
    no error reporting still names them."""
    global _booted
    if _booted:
        return
    configure_logging(settings.log_level, settings.log_json)
    name_process(settings.service_name, settings.environment)
    install_trust_store()
    configure_error_reporting(
        settings.sentry_dsn, settings.environment, settings.service_name, settings.version
    )
    configure_tracing(
        settings.otel_endpoint,
        settings.service_name,
        timedelta(seconds=settings.otel_timeout_seconds),
    )
    _booted = True


def totp_key(settings: ApiSettings) -> str | None:
    key = settings.totp_encryption_key
    return None if key is None else key.get_secret_value()


def tenancy_options(settings: ApiSettings) -> TenancyOptions:
    return TenancyOptions(
        login_ttl=timedelta(seconds=settings.login_lifetime_seconds),
        session_ttl=timedelta(seconds=settings.session_lifetime_seconds),
        session_idle_ttl=timedelta(seconds=settings.session_idle_lifetime_seconds),
        sign_in_free_failures=settings.sign_in_free_failures,
        sign_in_delay_base=timedelta(seconds=settings.sign_in_delay_base_seconds),
        sign_in_delay_cap=timedelta(seconds=settings.sign_in_delay_cap_seconds),
        operator_token_ttl=timedelta(seconds=settings.operator_token_max_lifetime_seconds),
        totp_encryption_key=totp_key(settings),
    )


def operator_options(settings: ApiSettings) -> TenancyOperatorOptions:
    return TenancyOperatorOptions(
        operator_token_ttl=timedelta(seconds=settings.operator_token_max_lifetime_seconds),
        totp_encryption_key=totp_key(settings),
    )


def rate_limit_options(settings: ApiSettings) -> RateLimitOptions:
    return RateLimitOptions(
        login=RateLimit(
            limit=settings.login_rate_limit,
            window=timedelta(seconds=settings.login_rate_window_seconds),
        ),
        signup=RateLimit(
            limit=settings.signup_rate_limit,
            window=timedelta(seconds=settings.signup_rate_window_seconds),
        ),
    )


def postgres_storage(settings: ApiSettings) -> StorageInterface:
    """The storage root over the database the settings name: the one place a
    process of this service opens its pools."""
    return StoragePostgresImpl(
        settings.role_urls(),
        settings.role_pools(),
        system_urls=settings.system_role_urls(),
    )


def memory_storage() -> StorageInterface:
    """The storage root in memory, for a command that reads the app's shape
    and no data: the OpenAPI document is emitted over it."""
    return StorageMemoryImpl()


class AppContainer:
    def __init__(
        self,
        settings: ApiSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        managers: Managers,
        services: ServicesInterface,
        rate_limits: RateLimitOptions,
        payments: PaymentsInterface,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.payments = payments
        self.managers = managers
        self.services = services
        self.rate_limits = rate_limits

    @classmethod
    def build(cls, settings: ApiSettings) -> AppContainer:
        return cls.over(settings, postgres_storage(settings), InfraConfiguredImpl(settings))

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: ApiSettings | None = None,
        payments: PaymentsInterface | None = None,
    ) -> AppContainer:
        settings = settings or ApiSettings.model_validate(
            {"_env_file": None, "environment": "test"}
        )
        return cls.over(settings, storage, infra, payments)

    @classmethod
    def over(
        cls,
        settings: ApiSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        payments: PaymentsInterface | None = None,
    ) -> AppContainer:
        """Managers, then services, over whichever roots the caller chose. The
        payments client is the one the settings name unless the caller hands
        one in (a test that drives the twin)."""
        payments = payments or build_payments(settings)
        managers = build_managers(
            storage,
            infra,
            tenancy_options(settings),
            operator_options(settings),
            payments=payments,
        )
        services = build_services(managers, infra, payments, settings.cors_origins)
        return cls(
            settings,
            storage,
            infra,
            managers,
            services,
            rate_limit_options(settings),
            payments,
        )

    async def start(self) -> None:
        await self.infra.start()
        await self.payments.start()
        log.info(
            "%s started with %s",
            self.settings.service_name,
            ", ".join([*self.infra.describe(), self.payments.describe()]),
        )
        if self.settings.totp_encryption_key is None:
            log.warning(
                "no TOTP encryption key: the operator plane refuses every enrolment "
                "and every sign-in that presents a code"
            )

    async def close(self) -> None:
        await self.payments.close()
        await self.infra.close()
        await self.storage.close()
