"""The facade over the generated schema: the names consumers import. Nothing
outside this package imports `schema` directly, so a regeneration that
renames a generated class is absorbed here."""

from tadas.client.schema import (
    ApiKeyPageView,
    ApiKeyView,
    EventView,
    IssuedApiKeyView,
    IssuedLoginView,
    IssuedSessionView,
    IssuedTicketView,
    MembershipChoiceView,
    MembershipView,
    MeView,
    OrgView,
    Permission,
    Role,
    SessionView,
    TaskPageView,
    TaskScope,
    TaskStatus,
    TaskView,
    UserPageView,
    UserView,
)

__all__ = [
    "ApiKeyPageView",
    "ApiKeyView",
    "EventView",
    "IssuedApiKeyView",
    "IssuedLoginView",
    "IssuedSessionView",
    "IssuedTicketView",
    "MeView",
    "MembershipChoiceView",
    "MembershipView",
    "OrgView",
    "Permission",
    "Role",
    "SessionView",
    "TaskPageView",
    "TaskScope",
    "TaskStatus",
    "TaskView",
    "UserPageView",
    "UserView",
]
