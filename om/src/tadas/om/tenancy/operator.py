"""The operator plane of the tenancy swimlane: what a platform operator may
do across every tenant. Every operation takes `OperatorContext` and nothing
else; the tenant manager takes `OpContext` and nothing else, so the type
system keeps the two planes apart. A read requires `OperatorPermission.READ`
and a write `OperatorPermission.WRITE`, which the allowlist entry grants."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

from tadas.om.tenancy.types.org import Org

if TYPE_CHECKING:
    from tadas.om.opcontext import OperatorContext


class TenancyOperatorManagerInterface(ABC):
    @abstractmethod
    async def get_orgs(self, admin: OperatorContext, limit: int) -> list[Org]:
        """Every org, deleted ones included, sorted by id."""
        ...

    @abstractmethod
    async def delete_org(self, admin: OperatorContext, org_id: UUID) -> Org:
        """Soft-deletes the org and announces it (`tenancy.org.deleted`), so its
        principals stop resolving at once and every socket of the tenant closes.
        Its users, credentials, and work stay for the sweep: queued work fails
        on its next claim, and the purge takes the tenant's rows once the
        retention has passed."""
        ...
