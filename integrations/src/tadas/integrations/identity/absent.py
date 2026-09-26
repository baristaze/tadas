"""The provider of a process that signs nobody in: every call is refused as
unavailable. The worker holds this one, and so does an API whose environment
names no provider."""

from typing import Literal, NoReturn

from tadas.integrations.exceptions import ProviderUnavailable
from tadas.integrations.identity import (
    DeviceAuthorization,
    IdentityProviderInterface,
    PortalIntent,
    ProvidedInvitation,
    ProvidedOrganization,
    ProvidedSignIn,
)


class IdentityProviderAbsentImpl(IdentityProviderInterface):
    def __init__(self, reason: str = "no identity provider is configured") -> None:
        self._reason = reason

    def _refuse(self) -> NoReturn:
        raise ProviderUnavailable(self._reason)

    @property
    def issuer(self) -> str:
        return "none"

    @property
    def configured(self) -> bool:
        return False

    def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        invitation_token: str | None = None,
        screen_hint: Literal["sign-in", "sign-up"] | None = None,
    ) -> str:
        self._refuse()

    async def authenticate_code(
        self, code: str, *, code_verifier: str | None, invitation_token: str | None = None
    ) -> ProvidedSignIn:
        self._refuse()

    def logout_url(self, *, session_id: str, return_to: str | None) -> str:
        self._refuse()

    async def start_device(self) -> DeviceAuthorization:
        self._refuse()

    async def authenticate_device(self, device_code: str) -> ProvidedSignIn:
        self._refuse()

    async def ensure_organization(self, *, external_id: str, name: str) -> ProvidedOrganization:
        self._refuse()

    async def get_organization(self, organization_id: str) -> ProvidedOrganization:
        self._refuse()

    async def send_invitation(
        self, *, email: str, organization_id: str, expires_in_days: int
    ) -> ProvidedInvitation:
        self._refuse()

    async def find_pending_invitation(
        self, *, email: str, organization_id: str
    ) -> ProvidedInvitation | None:
        self._refuse()

    async def resend_invitation(self, invitation_id: str) -> ProvidedInvitation:
        self._refuse()

    async def revoke_invitation(self, invitation_id: str) -> ProvidedInvitation:
        self._refuse()

    async def delete_user(self, user_id: str) -> None:
        self._refuse()

    async def accepted_invitation(
        self, *, organization_id: str, user_id: str
    ) -> ProvidedInvitation | None:
        self._refuse()

    async def portal_link(
        self, *, organization_id: str, intent: PortalIntent, return_url: str
    ) -> str:
        self._refuse()

    def describe(self) -> str:
        return f"identity provider: none ({self._reason})"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None
