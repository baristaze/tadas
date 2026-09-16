from uuid import UUID

from tadas.om.base import Identifiable, Trackable
from tadas.om.tenancy.types.role import Role


class Membership(Identifiable, Trackable):
    user_id: UUID
    role: Role
    teams: tuple[UUID, ...] = ()
