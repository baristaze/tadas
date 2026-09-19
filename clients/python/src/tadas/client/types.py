"""The facade over the generated schema: the names consumers import. Nothing
outside this package imports `schema` directly, so a regeneration that
renames a generated class is absorbed here."""

from tadas.client.schema import (
    ApiKeyView,
    EventView,
    IssuedApiKeyView,
    IssuedLoginView,
    IssuedSessionView,
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
    TicketView,
    UserView,
)

__all__ = [
    "ApiKeyView",
    "EventView",
    "IssuedApiKeyView",
    "IssuedLoginView",
    "IssuedSessionView",
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
    "TicketView",
    "UserView",
]
