from uuid import UUID

from tadas.om.base import Platform, new_id, utcnow
from tadas.om.exceptions import NotFound
from tadas.om.opcontext import OperatorContext
from tadas.om.outbox import OutboxRelayInterface
from tadas.om.outbox.types.row import OutboxRow, snapshot
from tadas.om.tenancy.operator import TenancyOperatorManagerInterface
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.types.org import Org


class TenancyOperatorOptions(Platform):
    max_limit: int = 200


class TenancyOperatorManagerImpl(TenancyOperatorManagerInterface):
    def __init__(
        self,
        storage: TenancyStorageInterface,
        relay: OutboxRelayInterface,
        options: TenancyOperatorOptions,
    ) -> None:
        self._storage = storage
        self._relay = relay
        self._options = options

    async def get_orgs(self, admin: OperatorContext, limit: int) -> list[Org]:
        return await self._storage.read_orgs(max(1, min(limit, self._options.max_limit)))

    async def delete_org(self, admin: OperatorContext, org_id: UUID) -> Org:
        org = await self._storage.read_org(org_id)
        if org is None or org.deleted_at is not None:
            raise NotFound(f"org {org_id} not found")
        now = utcnow()
        deleted = org.model_copy(
            update={
                "deleted_at": now,
                "deleted_by": admin.identity_id,
                "updated_at": now,
                "updated_by": admin.identity_id,
            }
        )
        # Announced like any change, into the tenant's own stream: the sockets
        # of the tenant, in whichever process holds them, close on the row the
        # relay publishes. An operator has no user in the tenant, so the actor
        # the row records is the operator's identity.
        row = OutboxRow(
            id=new_id(),
            created_at=now,
            kind="tenancy.org.deleted",
            target_id=org_id,
            payload=snapshot(deleted),
            actor_id=admin.identity_id,
            request_id=admin.request_id,
            app=admin.app.type.value,
        )
        await self._storage.write_org(org_id, deleted, (row,))
        await self._relay.relay(org_id, row)
        return deleted
