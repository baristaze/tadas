"""Storage implementations are assembled behind a single root."""

from abc import ABC, abstractmethod

from tadas.om.billing.storage import BillingStorageInterface
from tadas.om.events.storage import EventStorageInterface
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.media.storage import MediaStorageInterface
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.slack.storage import SlackStorageInterface
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.work.storage import WorkStorageInterface


class StorageInterface(ABC):
    @abstractmethod
    def get_tenancy_storage(self) -> TenancyStorageInterface: ...

    @abstractmethod
    def get_work_storage(self) -> WorkStorageInterface: ...

    @abstractmethod
    def get_tasks_storage(self) -> TasksStorageInterface: ...

    @abstractmethod
    def get_media_storage(self) -> MediaStorageInterface: ...

    @abstractmethod
    def get_idempotency_storage(self) -> IdempotencyStorageInterface: ...

    @abstractmethod
    def get_event_storage(self) -> EventStorageInterface: ...

    @abstractmethod
    def get_outbox_storage(self) -> OutboxStorageInterface: ...

    @abstractmethod
    def get_billing_storage(self) -> BillingStorageInterface: ...

    @abstractmethod
    def get_slack_storage(self) -> SlackStorageInterface: ...

    @abstractmethod
    async def healthcheck(self) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...
