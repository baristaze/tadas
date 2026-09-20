"""Wire types of the operator plane. The views a tenant's rows are read into
are the tenant's own (`OrgView`, `UserPageView`, `TaskPageView`,
`EventView`): an operator sees what the tenant sees, under the tenant named
in the path."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from tadas.om.opcontext import OperatorRole, Role
from tadas.services.api.types.common import RequestBody, View


class CreateOrgRequest(RequestBody):
    """An org with its owner, as `bootstrap` seeds one. The owner's identity
    is created with the password, or kept with its own when the email is
    known already."""

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100)
    owner_email: str = Field(min_length=1)
    owner_password: str = Field(min_length=1)
    owner_name: str = Field(min_length=1, max_length=200)


class AddMemberRequest(RequestBody):
    """A person in the org, as `add-member` seeds one; the owner and the
    service role are refused, since the one owner is the one the create
    minted."""

    email: str = Field(min_length=1)
    password: str = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=200)
    role: Role


class OperatorView(View):
    """Who the operator plane admitted: the identity and what its allowlist
    entry grants, so a skill checks it holds the entry it expects before it
    reads anything."""

    identity_id: UUID
    email: str
    operator_role: OperatorRole


class PlatformSizeView(View):
    """How big the platform is, what the first responder to an alarm reads
    before it escalates: live tenants and users, and the tasks created and
    events produced in the last twenty-four hours, a window that starts at
    `since` and ends at the read."""

    tenants: int
    users: int
    tasks_last_24h: int
    events_last_24h: int
    since: datetime
