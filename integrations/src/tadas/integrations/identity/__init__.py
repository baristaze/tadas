"""The identity provider: the hosted service that proves who a person is.
It hands Tadas an issuer, a subject, and a verified email; the identity row,
the sessions, and every id stay Tadas's own. It also holds the provider's
side of an org (its organization, its single sign-on, its invitations),
which the tenancy manager creates lazily and names by the Tadas org's id.

One interface, a real client (`workos.py`), a deterministic twin
(`twin.py`), and the absent provider (`absent.py`) of a process that signs
nobody in, such as the worker."""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class ProvidedUser(_Frozen):
    """The person as the provider knows them. `id` is the subject."""

    id: str
    email: str
    email_verified: bool
    first_name: str | None = None
    last_name: str | None = None

    @property
    def display_name(self) -> str:
        """The name the provider holds, first and last, or empty."""
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip()


class ProvidedSignIn(_Frozen):
    """A completed sign-in: who, and, when the provider signed them in to one
    of its organizations (an invitation accepted, a single sign-on), which.
    `via_sso` is True only when the person's own identity provider, through
    the organization's connection, vouched for them."""

    user: ProvidedUser
    organization_id: str | None = None
    via_sso: bool = False


class DeviceAuthorization(_Frozen):
    """The start of a device sign-in: the code the device polls with, which
    it keeps to itself, and the code and address the person confirms."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class ProvidedOrganization(_Frozen):
    id: str
    name: str
    external_id: str | None
    verified_domains: tuple[str, ...] = ()


class InvitationState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ProvidedInvitation(_Frozen):
    id: str
    email: str
    state: InvitationState
    expires_at: datetime
    organization_id: str | None
    accepted_user_id: str | None = None


PortalIntent = Literal["sso", "domain_verification"]
"""What an admin portal link opens on: the single sign-on connection, or the
verification of the organization's domains."""


class IdentityProviderInterface(ABC):
    @property
    @abstractmethod
    def issuer(self) -> str:
        """The issuer every subject this provider returns is unique under."""
        ...

    @property
    @abstractmethod
    def configured(self) -> bool:
        """False when this process cannot sign anyone in through it."""
        ...

    @abstractmethod
    def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        invitation_token: str | None = None,
        screen_hint: Literal["sign-in", "sign-up"] | None = None,
    ) -> str:
        """Where the browser goes to sign in; it comes back to `redirect_uri`
        with a code and `state` as it was handed. `code_challenge` is the
        S256 digest of the verifier the exchange presents (PKCE), so a code
        is worth nothing to anyone who does not hold the verifier. No
        network call."""
        ...

    @abstractmethod
    async def authenticate_code(
        self, code: str, *, code_verifier: str | None, invitation_token: str | None = None
    ) -> ProvidedSignIn:
        """Exchanges the code the browser brought back, server-side, with the
        verifier the sign-in started with. ProviderRefused for a code that is
        spent, expired, or never issued, or a verifier that does not match."""
        ...

    @abstractmethod
    async def start_device(self) -> DeviceAuthorization:
        """Starts a sign-in for a device with no browser of its own."""
        ...

    @abstractmethod
    async def authenticate_device(self, device_code: str) -> ProvidedSignIn:
        """Asks whether the person confirmed the device sign-in: the sign-in
        when they did, DevicePending or DeviceSlowDown while they have not,
        DeviceDenied or DeviceExpired when it will never come."""
        ...

    @abstractmethod
    async def ensure_organization(self, *, external_id: str, name: str) -> ProvidedOrganization:
        """The provider's organization for a Tadas org: the one that carries
        `external_id` when there is one, else a new one. Rerun, it creates
        nothing."""
        ...

    @abstractmethod
    async def get_organization(self, organization_id: str) -> ProvidedOrganization:
        """ProviderRefused for an id the provider does not hold."""
        ...

    @abstractmethod
    async def send_invitation(
        self, *, email: str, organization_id: str, expires_in_days: int
    ) -> ProvidedInvitation:
        """The provider sends the email with the sign-in link. ProviderConflict
        when an invitation for the address is pending in the organization."""
        ...

    @abstractmethod
    async def find_pending_invitation(
        self, *, email: str, organization_id: str
    ) -> ProvidedInvitation | None:
        """The pending invitation for the address in the organization."""
        ...

    @abstractmethod
    async def resend_invitation(self, invitation_id: str) -> ProvidedInvitation: ...

    @abstractmethod
    async def revoke_invitation(self, invitation_id: str) -> ProvidedInvitation: ...

    @abstractmethod
    async def accepted_invitation(
        self, *, organization_id: str, user_id: str
    ) -> ProvidedInvitation | None:
        """The invitation of the organization the person accepted, when one
        is: the provider's record of who accepted it, which a sign-in reads
        rather than the address the invitation was sent to, since an
        invitation to a company's domain may be accepted with another address
        of the same domain."""
        ...

    @abstractmethod
    async def portal_link(
        self, *, organization_id: str, intent: PortalIntent, return_url: str
    ) -> str:
        """A short-lived link to the provider's admin portal for the
        organization, where its admin sets up single sign-on themselves."""
        ...

    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
