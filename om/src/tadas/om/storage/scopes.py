"""Every table belongs to exactly one tenancy scope; this map is the single
source of truth for the row-level security policy the table carries and for
what the funnel sets on the transaction that touches it.

The scope is the second fence. The first one is the predicate in the query,
which is what the business layer relies on; nothing above storage assumes a
policy exists. The policy is what catches the predicate that went missing.
"""

from dataclasses import dataclass
from enum import StrEnum

ORG_SETTING = "app.org_id"
USER_SETTING = "app.user_id"
IDENTITY_SETTING = "app.identity_id"
"""The three transaction settings a policy reads. They are set with
`set_config(name, value, true)` so they die with the transaction, and a
missing one reads as NULL, which makes every comparison false: fail closed."""

POLICY_NAME = "tenant_fence"
"""One policy per table, `FOR ALL`, `USING` and `WITH CHECK` the same."""


class ScopeKind(StrEnum):
    SYSTEM = "system"
    """A global table: no tenant, no person, no policy."""

    ORG = "org"
    """Rows belong to a tenant. The policy is on `org_id`."""

    IDENTITY = "identity"
    """Rows belong to an identity and to no tenant. The policy is on the
    declared identity column. No table here is identity-scoped today; the
    shape is declared so the first one has nowhere to improvise."""

    BOTH = "both"
    """Rows belong to a tenant and to a person in it. The policy is on
    `org_id`, narrowed when the transaction names the person and not narrowed
    when it does not: on the declared person column against `app.user_id`,
    or, for a row whose person is the identity behind it, on the declared
    identity column against `app.identity_id`."""


@dataclass(frozen=True)
class TableScope:
    kind: ScopeKind
    person_column: str | None = None
    identity_column: str | None = None

    def __post_init__(self) -> None:
        if self.kind is ScopeKind.BOTH and (self.person_column is None) == (
            self.identity_column is None
        ):
            raise ValueError("a both-scoped table declares its person or its identity column")
        if self.kind is ScopeKind.IDENTITY and (
            self.identity_column is None or self.person_column is not None
        ):
            raise ValueError("an identity-scoped table declares its identity column alone")
        if self.kind in (ScopeKind.SYSTEM, ScopeKind.ORG) and (
            self.person_column or self.identity_column
        ):
            raise ValueError(f"a {self.kind.value}-scoped table declares no column")

    @property
    def narrowing(self) -> tuple[str, str] | None:
        """The column the policy narrows on and the setting it compares with,
        or None for a table no person narrows."""
        if self.person_column is not None:
            return self.person_column, USER_SETTING
        if self.identity_column is not None:
            return self.identity_column, IDENTITY_SETTING
        return None


TABLE_SCOPES: dict[str, TableScope] = {
    # The global tables: an identity is a person across tenants, and a
    # sign-in delay is keyed on an email before any identity is known.
    "identities": TableScope(ScopeKind.SYSTEM),
    "sign_in_delays": TableScope(ScopeKind.SYSTEM),
    # A tenant's own rows. An org's `org_id` is its own id.
    "orgs": TableScope(ScopeKind.ORG),
    "invitations": TableScope(ScopeKind.ORG),
    "tasks": TableScope(ScopeKind.ORG),
    "files": TableScope(ScopeKind.ORG),
    "outbox_rows": TableScope(ScopeKind.ORG),
    "work_items": TableScope(ScopeKind.ORG),
    "events": TableScope(ScopeKind.ORG),
    "event_cursors": TableScope(ScopeKind.ORG),
    "billing_accounts": TableScope(ScopeKind.ORG),
    "billing_deliveries": TableScope(ScopeKind.ORG),
    "slack_installations": TableScope(ScopeKind.ORG),
    "slack_install_states": TableScope(ScopeKind.ORG),
    "slack_posts": TableScope(ScopeKind.ORG),
    # A tenant's rows that also belong to one person in it. A user's person
    # is the identity behind it, so it narrows on `app.identity_id`; every
    # other row here names the user and narrows on `app.user_id`.
    "users": TableScope(ScopeKind.BOTH, identity_column="identity_id"),
    "memberships": TableScope(ScopeKind.BOTH, person_column="user_id"),
    "sessions": TableScope(ScopeKind.BOTH, person_column="user_id"),
    "api_keys": TableScope(ScopeKind.BOTH, person_column="user_id"),
    "socket_tickets": TableScope(ScopeKind.BOTH, person_column="user_id"),
    "idempotency_records": TableScope(ScopeKind.BOTH, person_column="user_id"),
}


def scope_for(table_name: str) -> TableScope:
    try:
        return TABLE_SCOPES[table_name]
    except KeyError:
        raise LookupError(
            f"table {table_name!r} has no tenancy scope; add it to TABLE_SCOPES"
        ) from None
