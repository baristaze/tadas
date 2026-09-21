"""What a tenancy list answers with: one page, and whether another follows.
The manager asks storage for one row more than the page and keeps it out, so
`has_more` is a fact about the rows and not a guess about the count, the way
a task list answers."""

from tadas.om.base import Platform
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.user import User


class UserPage(Platform):
    items: tuple[User, ...]
    has_more: bool


class ApiKeyPage(Platform):
    items: tuple[ApiKey, ...]
    has_more: bool


class MembershipPage(Platform):
    items: tuple[Membership, ...]
    has_more: bool


class OrgPage(Platform):
    items: tuple[Org, ...]
    has_more: bool
