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
from tadas.om.root import Managers, TenancyOptions, build_managers
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


def tenancy_options(settings: ApiSettings) -> TenancyOptions:
    return TenancyOptions(
        login_ttl=timedelta(seconds=settings.login_lifetime_seconds),
        session_ttl=timedelta(seconds=settings.session_lifetime_seconds),
        sign_in_free_failures=settings.sign_in_free_failures,
        sign_in_delay_base=timedelta(seconds=settings.sign_in_delay_base_seconds),
        sign_in_delay_cap=timedelta(seconds=settings.sign_in_delay_cap_seconds),
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


class AppContainer:
    def __init__(
        self,
        settings: ApiSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        managers: Managers,
        services: ServicesInterface,
        rate_limits: RateLimitOptions,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.managers = managers
        self.services = services
        self.rate_limits = rate_limits

    @classmethod
    def build(cls, settings: ApiSettings) -> AppContainer:
        storage = StoragePostgresImpl(
            settings.role_urls(),
            settings.role_pools(),
            system_urls=settings.system_role_urls(),
        )
        infra = InfraConfiguredImpl(settings)
        return cls.over(settings, storage, infra)

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: ApiSettings | None = None,
    ) -> AppContainer:
        settings = settings or ApiSettings.model_validate(
            {"_env_file": None, "environment": "test"}
        )
        return cls.over(settings, storage, infra)

    @classmethod
    def over(
        cls, settings: ApiSettings, storage: StorageInterface, infra: InfraInterface
    ) -> AppContainer:
        """Managers, then services, over whichever roots the caller chose."""
        managers = build_managers(storage, infra, tenancy_options(settings))
        services = build_services(managers, infra)
        return cls(settings, storage, infra, managers, services, rate_limit_options(settings))

    async def start(self) -> None:
        await self.infra.start()
        log.info("%s started with %s", self.settings.service_name, ", ".join(self.infra.describe()))

    async def close(self) -> None:
        await self.infra.close()
        await self.storage.close()
