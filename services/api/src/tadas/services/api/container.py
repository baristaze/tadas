"""Every process boots the same way: settings, then storage, then infra,
then the managers. Routers resolve them per request from this one object."""

import logging

from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.root import InfraInterface
from tadas.om.root import Managers, build_managers
from tadas.om.storage.impl.postgres import StoragePostgresImpl
from tadas.om.storage.root import StorageInterface
from tadas.services.api.settings import ApiSettings

log = logging.getLogger(__name__)


class AppContainer:
    def __init__(
        self,
        settings: ApiSettings,
        storage: StorageInterface,
        infra: InfraInterface,
        managers: Managers,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.infra = infra
        self.managers = managers

    @classmethod
    def build(cls, settings: ApiSettings) -> "AppContainer":
        storage = StoragePostgresImpl(settings.role_urls())
        infra = InfraConfiguredImpl(settings)
        managers = build_managers(storage, infra)
        return cls(settings, storage, infra, managers)

    @classmethod
    def for_tests(
        cls,
        storage: StorageInterface,
        infra: InfraInterface,
        settings: ApiSettings | None = None,
    ) -> "AppContainer":
        settings = settings or ApiSettings.model_validate({"environment": "test"})
        return cls(settings, storage, infra, build_managers(storage, infra))

    async def start(self) -> None:
        await self.infra.start()
        log.info("%s started with %s", self.settings.service_name, ", ".join(self.infra.describe()))

    async def close(self) -> None:
        await self.infra.close()
        await self.storage.close()
