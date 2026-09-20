"""Every process boots the same way: settings, then logging, the trust store,
error reporting, and tracing, then storage, infra, the managers, and the services, in that
order. Routers resolve them per request from this one object."""

import logging
from datetime import timedelta

from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.observability import (
    configure_error_reporting,
    configure_logging,
    configure_tracing,
)
from tadas.infra.root import InfraInterface
from tadas.infra.trust import install_trust_store
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.postgres import StoragePostgresImpl
from tadas.om.storage.root import StorageInterface
from tadas.services.api.gateway.ratelimit import RateLimit, RateLimitOptions
from tadas.services.api.services import ServicesInterface
from tadas.services.api.services.impl.root import build_services
from tadas.services.api.settings import ApiSettings

log = logging.getLogger(__name__)

_booted = False


def boot(settings: ApiSettings) -> None:
    """Settings first, then logging, the trust store, error reporting, and
    tracing. Every entry
    point calls it before it builds a container; it runs once per process."""
    global _booted
    if _booted:
        return
    configure_logging(settings.log_level, settings.log_json)
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


def rate_limit_options(settings: ApiSettings) -> RateLimitOptions:
    return RateLimitOptions(
        login=RateLimit(
            limit=settings.login_rate_limit,
            window=timedelta(seconds=settings.login_rate_window_seconds),
        )
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
        storage = StoragePostgresImpl(settings.role_urls())
        infra = InfraConfiguredImpl(settings)
        return cls.over(settings, storage, infra)

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: ApiSettings | None = None,
    ) -> AppContainer:
        settings = settings or ApiSettings.model_validate({"environment": "test"})
        return cls.over(settings, storage, infra)

    @classmethod
    def over(
        cls, settings: ApiSettings, storage: StorageInterface, infra: InfraInterface
    ) -> AppContainer:
        """Managers, then services, over whichever roots the caller chose."""
        managers = build_managers(storage, infra)
        services = build_services(managers, infra)
        return cls(settings, storage, infra, managers, services, rate_limit_options(settings))

    async def start(self) -> None:
        await self.infra.start()
        log.info("%s started with %s", self.settings.service_name, ", ".join(self.infra.describe()))

    async def close(self) -> None:
        await self.infra.close()
        await self.storage.close()
