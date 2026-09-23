"""The in-memory storage root: the default for unit tests and the fast gate."""

from tadas.om.billing.storage import BillingStorageInterface
from tadas.om.billing.storage.impl.memory import BillingStorageMemoryImpl
from tadas.om.events.storage import EventStorageInterface
from tadas.om.events.storage.impl.memory import EventStorageMemoryImpl
from tadas.om.idempotency.storage import IdempotencyStorageInterface
from tadas.om.idempotency.storage.impl.memory import IdempotencyStorageMemoryImpl
from tadas.om.media.storage import MediaStorageInterface
from tadas.om.media.storage.impl.memory import MediaStorageMemoryImpl
from tadas.om.outbox.storage import OutboxStorageInterface
from tadas.om.outbox.storage.impl.memory import OutboxStorageMemoryImpl
from tadas.om.slack.storage import SlackStorageInterface
from tadas.om.slack.storage.impl.memory import SlackStorageMemoryImpl
from tadas.om.storage.root import StorageInterface
from tadas.om.tasks.storage import TasksStorageInterface
from tadas.om.tasks.storage.impl.memory import TasksStorageMemoryImpl
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.storage.impl.memory import TenancyStorageMemoryImpl
from tadas.om.work.storage import WorkStorageInterface
from tadas.om.work.storage.impl.memory import WorkStorageMemoryImpl


class StorageMemoryImpl(StorageInterface):
    def __init__(self) -> None:
        # The outbox and the markers first: the core-role impls land their
        # outbox rows in the one and fence a re-mint on the other, which is
        # how each impl gets what its Postgres twin reads in its own statement.
        self._outbox = OutboxStorageMemoryImpl()
        self._idempotency = IdempotencyStorageMemoryImpl()
        self._tenancy = TenancyStorageMemoryImpl(self._outbox, self._idempotency)
        self._work = WorkStorageMemoryImpl()
        self._tasks = TasksStorageMemoryImpl(self._outbox)
        self._media = MediaStorageMemoryImpl(self._outbox)
        self._events = EventStorageMemoryImpl()
        self._billing = BillingStorageMemoryImpl(self._outbox)
        self._slack = SlackStorageMemoryImpl(self._outbox)

    def get_tenancy_storage(self) -> TenancyStorageInterface:
        return self._tenancy

    def get_work_storage(self) -> WorkStorageInterface:
        return self._work

    def get_tasks_storage(self) -> TasksStorageInterface:
        return self._tasks

    def get_media_storage(self) -> MediaStorageInterface:
        return self._media

    def get_idempotency_storage(self) -> IdempotencyStorageInterface:
        return self._idempotency

    def get_event_storage(self) -> EventStorageInterface:
        return self._events

    def get_outbox_storage(self) -> OutboxStorageInterface:
        return self._outbox

    def get_billing_storage(self) -> BillingStorageInterface:
        return self._billing

    def get_slack_storage(self) -> SlackStorageInterface:
        return self._slack

    async def healthcheck(self) -> bool:
        return True

    async def close(self) -> None:
        return None
