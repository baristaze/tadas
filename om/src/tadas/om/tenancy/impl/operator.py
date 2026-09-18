from uuid import UUID

from tadas.om.base import Platform, utcnow
from tadas.om.exceptions import NotFound
from tadas.om.opcontext import AdminContext
from tadas.om.tenancy.operator import TenancyOperatorManagerInterface
from tadas.om.tenancy.storage import TenancyStorageInterface
from tadas.om.tenancy.types.org import Org


class TenancyOperatorOptions(Platform):
    max_limit: int = 200


class TenancyOperatorManagerImpl(TenancyOperatorManagerInterface):
    def __init__(self, storage: TenancyStorageInterface, options: TenancyOperatorOptions) -> None:
        self._storage = storage
        self._options = options

    async def get_orgs(self, admin: AdminContext, limit: int) -> list[Org]:
        return await self._storage.read_orgs(max(1, min(limit, self._options.max_limit)))

    async def delete_org(self, admin: AdminContext, org_id: UUID) -> Org:
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
        await self._storage.write_org(org_id, deleted)
        return deleted
