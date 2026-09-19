"""The operator plane of the tenancy swimlane: what a platform operator may
do across every tenant. Every operation takes `AdminContext` and nothing
else; the tenant manager takes `OpContext` and nothing else, so the type
system keeps the two planes apart."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

from tadas.om.tenancy.types.org import Org

if TYPE_CHECKING:
    from tadas.om.opcontext import AdminContext


class TenancyOperatorManagerInterface(ABC):
    @abstractmethod
    async def get_orgs(self, admin: AdminContext, limit: int) -> list[Org]:
        """Every org, deleted ones included, sorted by id."""
        ...

    @abstractmethod
    async def delete_org(self, admin: AdminContext, org_id: UUID) -> Org:
        """Soft-deletes the org; its principals stop resolving at once."""
        ...
