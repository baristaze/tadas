"""The identity provider's real client: WorkOS, through its Python SDK.

AuthKit is the hosted sign-in (an email code or link, Google, GitHub, and an
organization's single sign-on); the code it hands back is exchanged here,
server-side, with the PKCE verifier the sign-in started with. An AuthKit
application has a client secret of its own, which is not the environment's
API key; the exchange needs neither, so this process holds only the API
key, and uses it for the management calls (organizations, invitations, the
admin portal). A WorkOS organization stands for a Tadas org and carries its
id as `external_id`.

The SDK's own HTTP client is replaced by one this impl owns, with the
timeout from settings, so every call out carries it. The SDK's retries stay:
they retry a 429 and a server error with backoff. Every SDK error is
translated here; none crosses the boundary."""

from datetime import timedelta
from typing import Any, Literal, NoReturn

import httpx
from workos import AsyncWorkOSClient
from workos._errors import (
    APIError,
    BadRequestError,
    NotFoundError,
    RateLimitExceededError,
    ServerError,
    UnprocessableEntityError,
    WorkOSError,
)

from tadas.integrations.exceptions import (
    DeviceDenied,
    DeviceExpired,
    DevicePending,
    DeviceSlowDown,
    ProviderConflict,
    ProviderRefused,
    ProviderUnavailable,
)
from tadas.integrations.identity import (
    DeviceAuthorization,
    IdentityProviderInterface,
    InvitationState,
    PortalIntent,
    ProvidedInvitation,
    ProvidedOrganization,
    ProvidedSignIn,
    ProvidedUser,
)

WORKOS_API = "https://api.workos.com"
DEVICE_ERRORS: dict[str, type[Exception]] = {
    "authorization_pending": DevicePending,
    "slow_down": DeviceSlowDown,
    "access_denied": DeviceDenied,
    "expired_token": DeviceExpired,
}


def _value(field: Any) -> str:
    """An SDK enum or a plain string, as its string."""
    return str(getattr(field, "value", field))


def _translate(error: Exception, doing: str) -> NoReturn:
    """Every SDK error as an integration exception, naming what was being done."""
    if isinstance(error, BadRequestError) and error.error in DEVICE_ERRORS:
        raise DEVICE_ERRORS[error.error](f"{doing}: {error.error}") from None
    if isinstance(error, (ServerError, RateLimitExceededError)):
        raise ProviderUnavailable(f"{doing}: WorkOS answered {error.status_code}") from None
    if isinstance(error, UnprocessableEntityError):
        raise ProviderConflict(f"{doing}: {error.message}") from None
    if isinstance(error, (BadRequestError, NotFoundError, APIError)):
        detail = error.error_description or error.error or error.code or error.message
        raise ProviderRefused(f"{doing}: {detail}") from None
    if isinstance(error, (WorkOSError, httpx.HTTPError)):
        raise ProviderUnavailable(f"{doing}: {type(error).__name__}") from None
    raise error


def _user(user: Any) -> ProvidedUser:
    return ProvidedUser(
        id=user.id,
        email=user.email,
        email_verified=bool(user.email_verified),
        first_name=user.first_name,
        last_name=user.last_name,
    )


def _sign_in(response: Any) -> ProvidedSignIn:
    method = response.authentication_method
    return ProvidedSignIn(
        user=_user(response.user),
        organization_id=response.organization_id,
        via_sso=method is not None and _value(method) == "SSO",
    )


def _organization(org: Any) -> ProvidedOrganization:
    verified = tuple(
        domain.domain.lower()
        for domain in (org.domains or [])
        if domain.state is not None and _value(domain.state) == "verified"
    )
    return ProvidedOrganization(
        id=org.id, name=org.name, external_id=org.external_id, verified_domains=verified
    )


def _invitation(invitation: Any) -> ProvidedInvitation:
    return ProvidedInvitation(
        id=invitation.id,
        email=invitation.email,
        state=InvitationState(_value(invitation.state)),
        expires_at=invitation.expires_at,
        organization_id=invitation.organization_id,
        accepted_user_id=invitation.accepted_user_id,
    )


class IdentityProviderWorkOSImpl(IdentityProviderInterface):
    def __init__(
        self,
        *,
        client_id: str,
        api_key: str,
        timeout: timedelta,
        base_url: str = WORKOS_API,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not client_id or not api_key:
            # The SDK falls back to the process environment for a missing
            # key; this impl never lets it choose a credential of its own.
            raise ValueError("WorkOS needs its client id and its API key")
        self._client_id = client_id
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout.total_seconds(), transport=transport)
        self._workos = AsyncWorkOSClient(
            api_key=api_key,
            client_id=client_id,
            base_url=self._base_url,
            max_retries=max_retries,
            http_client=self._http,
        )
        # The sign-in exchanges, as the application's public client: no
        # secret goes with them, the PKCE verifier and the device code do.
        self._public = AsyncWorkOSClient(
            client_id=client_id,
            base_url=self._base_url,
            max_retries=max_retries,
            is_public=True,
            http_client=self._http,
        )

    @property
    def issuer(self) -> str:
        """The issuer of the access tokens this application's sign-ins mint."""
        return f"{self._base_url}/user_management/{self._client_id}"

    @property
    def configured(self) -> bool:
        return True

    def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        invitation_token: str | None = None,
        screen_hint: Literal["sign-in", "sign-up"] | None = None,
    ) -> str:
        return self._workos.user_management.get_authorization_url(
            provider="authkit",
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method="S256",
            invitation_token=invitation_token,
            screen_hint=screen_hint,
        )

    async def authenticate_code(
        self, code: str, *, code_verifier: str | None, invitation_token: str | None = None
    ) -> ProvidedSignIn:
        try:
            response = await self._public.user_management.authenticate_with_code(
                code=code, code_verifier=code_verifier, invitation_token=invitation_token
            )
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "exchanging the sign-in code")
        return _sign_in(response)

    async def start_device(self) -> DeviceAuthorization:
        try:
            started = await self._public.user_management.create_device(client_id=self._client_id)
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "starting a device sign-in")
        return DeviceAuthorization(
            device_code=started.device_code,
            user_code=started.user_code,
            verification_uri=started.verification_uri,
            verification_uri_complete=started.verification_uri_complete or started.verification_uri,
            expires_in=int(started.expires_in),
            interval=int(started.interval or 5),
        )

    async def authenticate_device(self, device_code: str) -> ProvidedSignIn:
        try:
            response = await self._public.user_management.authenticate_with_device_code(
                device_code=device_code
            )
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "asking for the device sign-in")
        return _sign_in(response)

    async def ensure_organization(self, *, external_id: str, name: str) -> ProvidedOrganization:
        organizations = self._workos.organizations
        try:
            return _organization(
                await organizations.get_organization_by_external_id(external_id=external_id)
            )
        except NotFoundError:
            pass
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "reading the organization")
        try:
            created = await organizations.create_organization(name=name, external_id=external_id)
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "creating the organization")
        return _organization(created)

    async def get_organization(self, organization_id: str) -> ProvidedOrganization:
        try:
            org = await self._workos.organizations.get_organization(id=organization_id)
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "reading the organization")
        return _organization(org)

    async def send_invitation(
        self, *, email: str, organization_id: str, expires_in_days: int
    ) -> ProvidedInvitation:
        try:
            sent = await self._workos.user_management.send_invitation(
                email=email, organization_id=organization_id, expires_in_days=expires_in_days
            )
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "sending the invitation")
        return _invitation(sent)

    async def find_pending_invitation(
        self, *, email: str, organization_id: str
    ) -> ProvidedInvitation | None:
        try:
            page = await self._workos.user_management.list_invitations(
                organization_id=organization_id, email=email, limit=100
            )
            async for invitation in page.auto_paging_iter():
                if _value(invitation.state) == InvitationState.PENDING.value:
                    return _invitation(invitation)
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "listing the invitations")
        return None

    async def resend_invitation(self, invitation_id: str) -> ProvidedInvitation:
        try:
            resent = await self._workos.user_management.resend_invitation(id=invitation_id)
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "resending the invitation")
        return _invitation(resent)

    async def revoke_invitation(self, invitation_id: str) -> ProvidedInvitation:
        try:
            revoked = await self._workos.user_management.revoke_invitation(id=invitation_id)
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "revoking the invitation")
        return _invitation(revoked)

    async def accepted_invitation(
        self, *, organization_id: str, user_id: str
    ) -> ProvidedInvitation | None:
        try:
            page = await self._workos.user_management.list_invitations(
                organization_id=organization_id, limit=100
            )
            async for invitation in page.auto_paging_iter():
                if (
                    invitation.accepted_user_id == user_id
                    and _value(invitation.state) == InvitationState.ACCEPTED.value
                ):
                    return _invitation(invitation)
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "listing the invitations")
        return None

    async def portal_link(
        self, *, organization_id: str, intent: PortalIntent, return_url: str
    ) -> str:
        try:
            link = await self._workos.admin_portal.generate_link(
                organization=organization_id, intent=intent, return_url=return_url
            )
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "making the admin portal link")
        return link.link

    def describe(self) -> str:
        return f"identity provider: WorkOS ({self._base_url}, client {self._client_id})"

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        await self._http.aclose()
