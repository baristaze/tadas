"""What a tenancy list answers with: one page, and whether another follows.
The manager asks storage for one row more than the page and keeps it out, so
`has_more` is a fact about the rows and not a guess about the count."""

from tadas.om.base import OmBase
from tadas.om.tenancy.types.api_key import ApiKey
from tadas.om.tenancy.types.auth_session import AuthSession
from tadas.om.tenancy.types.invitation import Invitation
from tadas.om.tenancy.types.issued import OrgMembership
from tadas.om.tenancy.types.membership import Membership
from tadas.om.tenancy.types.org import Org
from tadas.om.tenancy.types.user import User


class UserPage(OmBase):
    items: tuple[User, ...]
    has_more: bool


class ApiKeyPage(OmBase):
    items: tuple[ApiKey, ...]
    has_more: bool


class MembershipPage(OmBase):
    items: tuple[Membership, ...]
    has_more: bool


class OrgPage(OmBase):
    items: tuple[Org, ...]
    has_more: bool


class OrgMembershipPage(OmBase):
    """The memberships of one identity across tenants, by user id: what a
    sign-in lists, a page at a time for a person already signed in."""

    items: tuple[OrgMembership, ...]
    has_more: bool


class InvitationPage(OmBase):
    items: tuple[Invitation, ...]
    has_more: bool


class OperatorTokenPage(OmBase):
    """One operator's live tokens, newest first: rows of `auth_sessions` of kind
    `operator_token`, never the token itself, which is kept as its digest."""

    items: tuple[AuthSession, ...]
    has_more: bool
