"""The identity provider's real client: WorkOS, through its Python SDK.

AuthKit is the hosted sign-in (an email code or link, Google, GitHub, and an
organization's single sign-on); the code it hands back is exchanged here,
server-side. This process holds one credential: the Tadas App application's
API key, made on that application's own API keys tab. It is the client
secret of the exchange, which is a confidential client's, and it
authenticates every management call (organizations, invitations, the admin
portal), so an invitation carries the application's context. The key of
another application, or of the environment, is not it: WorkOS answers the
exchange with `invalid_client`, and `start` refuses to boot on it.

The exchange also sends the PKCE verifier the sign-in started with. WorkOS
checks it when the secret is present too, so a code taken from the redirect
is worth nothing without the tab that started the sign-in (RFC 9700 asks for
PKCE on a confidential client as well). The device sign-in sends no secret:
WorkOS takes it as a public client's, and the SDK sends none with it.

A sign-in through AuthKit's hosted page leaves an AuthKit session in the
browser, and the next sign-in there goes through without a prompt until it
ends. The code exchange answers an access token whose `sid` claim names that
session; it is read here and kept by Tadas beside its own session, and the
sign-out sends the browser to WorkOS's logout with it. The token comes
straight from WorkOS over TLS, in the answer to this process's own request,
so the claim is read without checking the signature: nothing else of the
token is used, and Tadas never presents it anywhere. The device sign-in
records no session: the browser that confirmed it may be another machine's,
and a terminal has no browser to send.

A WorkOS organization stands for a Tadas org and carries its id as
`external_id`.

The SDK's own HTTP client is replaced by one this impl owns, with the
timeout from settings, so every call out carries it. The SDK's retries stay:
they retry a 429 and a server error with backoff. Every SDK error is
translated here; none crosses the boundary."""

import base64
import binascii
import json
import logging
from datetime import timedelta
from typing import Any, Literal, NoReturn

import httpx
from workos import AsyncWorkOSClient
from workos._errors import (
    APIError,
    AuthenticationError,
    AuthorizationError,
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
    UnsafeIntegration,
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

log = logging.getLogger(__name__)

WORKOS_API = "https://api.workos.com"
# A code WorkOS never issued. Exchanged at start with the key as the client
# secret, it answers `invalid_grant` when the key is the application's, and
# `invalid_client` when it is another application's, the environment's, or
# another environment's. Nothing is made either way.
CREDENTIAL_CHECK_CODE = "tadas-credential-check"
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
    if isinstance(error, BadRequestError) and error.error == "invalid_client":
        # The process's credential, not the person's request: revoked since
        # the start, or not the application's. It is a 503 until it is fixed.
        raise ProviderUnavailable(
            f"{doing}: WorkOS refused TADAS_WORKOS_API_KEY as the application's (invalid_client)"
        ) from None
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


def session_of(access_token: str | None) -> str | None:
    """The `sid` claim of an access token WorkOS just answered: the AuthKit
    session its logout ends. None when the token carries none or cannot be
    read, and the sign-in goes on: only the sign-out loses the provider's
    half."""
    try:
        payload = (access_token or "").split(".")[1]
        claims: Any = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except IndexError, ValueError, binascii.Error:
        log.warning("the WorkOS access token could not be read; no AuthKit session is kept")
        return None
    sid = claims.get("sid") if isinstance(claims, dict) else None
    return sid if isinstance(sid, str) and sid else None


def _sign_in(response: Any, *, session_id: str | None = None) -> ProvidedSignIn:
    method = response.authentication_method
    return ProvidedSignIn(
        user=_user(response.user),
        organization_id=response.organization_id,
        via_sso=method is not None and _value(method) == "SSO",
        session_id=session_id,
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
        # One client, one credential: the application's key is the exchange's
        # client secret and the management calls' bearer alike.
        self._workos = AsyncWorkOSClient(
            api_key=api_key,
            client_id=client_id,
            base_url=self._base_url,
            max_retries=max_retries,
            http_client=self._http,
        )

    @property
    def issuer(self) -> str:
        """The issuer Tadas files this application's subjects under. A WorkOS
        user id is the environment's, shared by its applications."""
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
            response = await self._workos.user_management.authenticate_with_code(
                code=code, code_verifier=code_verifier, invitation_token=invitation_token
            )
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "exchanging the sign-in code")
        return _sign_in(response, session_id=session_of(response.access_token))

    def logout_url(self, *, session_id: str, return_to: str | None) -> str:
        return self._workos.user_management.get_logout_url(
            session_id=session_id, return_to=return_to
        )

    async def start_device(self) -> DeviceAuthorization:
        try:
            started = await self._workos.user_management.create_device(client_id=self._client_id)
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
            response = await self._workos.user_management.authenticate_with_device_code(
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

    async def delete_user(self, user_id: str) -> None:
        try:
            await self._workos.user_management.delete_user(user_id)
        except NotFoundError:
            return  # deleted already: a rerun is one deletion
        except (AuthenticationError, AuthorizationError) as error:
            # The process's credential, not the call: revoked, or without the
            # permission. It is a 503 until a person fixes the key, as an
            # `invalid_client` is.
            raise ProviderUnavailable(
                f"deleting the user: WorkOS refused TADAS_WORKOS_API_KEY ({error.status_code})"
            ) from None
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "deleting the user")

    async def delete_organization(self, organization_id: str) -> None:
        try:
            await self._workos.organizations.delete_organization(id=organization_id)
        except NotFoundError:
            return  # deleted already: a rerun is one deletion
        except (AuthenticationError, AuthorizationError) as error:
            # The process's credential, not the call, as on a user's deletion.
            raise ProviderUnavailable(
                "deleting the organization: WorkOS refused TADAS_WORKOS_API_KEY "
                f"({error.status_code})"
            ) from None
        except (WorkOSError, httpx.HTTPError) as error:
            _translate(error, "deleting the organization")

    def describe(self) -> str:
        return f"identity provider: WorkOS ({self._base_url}, client {self._client_id})"

    async def start(self) -> None:
        """Proves the key is this application's before the process serves:
        refused on `invalid_client`, which only a key of another application
        or another environment earns. WorkOS out of reach is said and does
        not stop the start; the sign-ins say it again as a 503."""
        try:
            await self._workos.user_management.authenticate_with_code(code=CREDENTIAL_CHECK_CODE)
        except BadRequestError as error:
            if error.error == "invalid_client":
                raise UnsafeIntegration(
                    "TADAS_WORKOS_API_KEY is not the API key of the WorkOS application "
                    f"{self._client_id}: WorkOS answered invalid_client "
                    f"({error.error_description or 'no description'}). Make the key on "
                    "that application's own API keys tab (Applications, Tadas App, API "
                    "keys), not under the environment's API Keys"
                ) from None
            if error.error != "invalid_grant":
                log.warning(
                    "the WorkOS credential check answered %s; the key is not proven to be "
                    "application %s's",
                    error.error or error.status_code,
                    self._client_id,
                )
        except (WorkOSError, httpx.HTTPError) as error:
            log.warning(
                "the WorkOS credential check did not finish (%s); the key is not proven to "
                "be application %s's",
                type(error).__name__,
                self._client_id,
            )

    async def close(self) -> None:
        await self._http.aclose()
