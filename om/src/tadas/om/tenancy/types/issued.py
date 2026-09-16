"""Read models that carry a freshly minted secret in the clear, exactly once."""

from datetime import datetime

from tadas.om.base import Platform
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.role import Role
from tadas.om.tenancy.types.user import User


class OrgMembership(Platform):
    org: Org
    user: User
    role: Role


class IssuedLogin(Platform):
    token: str
    expires_at: datetime
    memberships: tuple[OrgMembership, ...]


class IssuedSession(Platform):
    token: str
    expires_at: datetime
    org: Org
    user: User
    role: Role


class IssuedApiKey(Platform):
    key: str
    api_key: ApiKey
