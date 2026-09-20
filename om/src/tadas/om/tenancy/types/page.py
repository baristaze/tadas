"""What a tenancy list answers with: one page, and whether another follows.
The manager asks storage for one row more than the page and keeps it out, so
`has_more` is a fact about the rows and not a guess about the count, the way
a task list answers."""

from tadas.om.base import Platform
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.user import User


class UserPage(Platform):
    items: list[User]
    has_more: bool


class ApiKeyPage(Platform):
    items: list[ApiKey]
    has_more: bool
