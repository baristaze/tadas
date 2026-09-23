"""One transport client: bearer, app header, the error envelope parsed into a
typed error carrying the request id, an idempotency key on every creating
call, the one retry, and the operating system's trust store. The one module in
the package that sends a request; every operation is a method that returns a
typed view."""

import asyncio
import random
import ssl
from collections.abc import Callable
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import httpx
import truststore

from tadas.client.types import (
    DeviceSignInView,
    EventView,
    InvitationPageView,
    InvitationView,
    IssuedLoginView,
    IssuedSessionView,
    IssuedTicketView,
    MembershipChoicePageView,
    MembershipChoiceView,
    MeView,
    OperatorEventView,
    OperatorView,
    OrgView,
    PlatformSizeView,
    Role,
    SessionView,
    SignInStartView,
    SsoLinkView,
    TaskPageView,
    TaskScope,
    TaskStatus,
    TaskView,
    UserPageView,
    UserView,
)

APP_HEADER = "X-App"
APP_VERSION_HEADER = "X-App-Version"
IDEMPOTENCY_HEADER = "Idempotency-Key"
REQUEST_ID_HEADER = "x-request-id"
LIMIT_MAX = 200
DEFAULT_TIMEOUT_SECONDS = 30.0
"""Every call out carries a timeout: the caller's settings name one per
client, and a caller that names none gets this one, so no call goes out
without one."""
DEFAULT_RETRIES = 2
"""Extra attempts a retryable failure gets. The caller's settings name this
one per client too, beside the timeout, so no caller wraps this client in a
second retry; 0 sends every call exactly once."""
DEFAULT_BACKOFF_SECONDS = 0.25
"""The wait before the first extra attempt. It doubles per attempt."""
MAX_BACKOFF_SECONDS = 5.0
"""However far the doubling runs, no wait between attempts is longer."""

RETRYABLE_STATUSES = frozenset({502, 503, 504})
"""The answers that say the API could not serve this call and may serve the
next one: its own `unavailable`, and the two a proxy sends when the origin
refused the connection or did not answer in time. Every other status is a
decision, and a decision does not change because it is asked for again."""

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
"""Methods with no effect on the API, so a second attempt costs a read."""

RETRYABLE_FAILURES = (httpx.TimeoutException, httpx.NetworkError)
"""The wire failing before the API decided: the timeout, and a connection that
was refused, reset, or lost. Every other transport failure stands as it is."""

AppName = Literal["portal", "admin", "cli", "api"]


def may_retry(method: str, idempotency_key: str | None = None) -> bool:
    """Whether this request may be sent twice. A safe method may. A creating
    call under an idempotency key may, because the API records the outcome
    under the key and replays it, so the second attempt finds the row the
    first one made instead of making another. Everything else may not: a POST
    with no key, a PATCH, and a DELETE all carry an effect that a lost answer
    leaves in doubt, and a duplicate write costs more than the failure the
    caller is told about."""
    verb = method.upper()
    if verb in SAFE_METHODS:
        return True
    return verb == "POST" and bool(idempotency_key)


def retry_delay_seconds(
    attempt: int,
    base: float = DEFAULT_BACKOFF_SECONDS,
    jitter: Callable[[], float] = random.random,
) -> float:
    """The wait before attempt `attempt` (1 is the first retry): the base
    doubled per attempt and capped, then halved and topped up from `jitter`.
    Half the window is fixed and half is jitter, so callers that failed
    together do not return together, and the shortest wait of one attempt is
    still the longest wait of the one before it wherever the curve doubles,
    which is what makes the growth assertable. `jitter` is a function of no arguments answering
    between 0 and 1; a test hands one in and asserts both ends of the
    window."""
    full = min(base * 2 ** max(0, attempt - 1), MAX_BACKOFF_SECONDS)
    return full / 2 + (full / 2) * jitter()


class Unset:
    """Marks an argument the caller left out, where `None` is itself a value."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET = Unset()


class ApiError(Exception):
    """The API refused: the status and the stable code from the error envelope,
    and the request id to quote when asking why."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        request_id: str | None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        self.retry_after = retry_after
        """How long the server asked a retry to wait, its `Retry-After`, when it did."""

    def __str__(self) -> str:
        suffix = f" (request {self.request_id})" if self.request_id else ""
        return f"{self.code}: {self.message}{suffix}"


def trust_store() -> ssl.SSLContext:
    """The operating system's certificates, for HTTPS and for the socket."""
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def retry_after_seconds(header: str | None) -> float | None:
    """A `Retry-After` in seconds, as the gateway sends it; an HTTP date or
    anything unreadable is no ask at all."""
    if header is None or not header.strip().isdigit():
        return None
    return float(header.strip())


def retry_wait_seconds(curve: float, server_asked: float | None) -> float:
    """The wait before a retry: the curve's, or longer when the server asked
    for longer, and never past the cap."""
    return min(max(curve, server_asked or 0.0), MAX_BACKOFF_SECONDS)


def _error_of(response: httpx.Response) -> ApiError:
    request_id = response.headers.get(REQUEST_ID_HEADER)
    retry_after = retry_after_seconds(response.headers.get("retry-after"))
    try:
        body = response.json()
    except ValueError:
        body = None
    envelope = body.get("error") if isinstance(body, dict) else None
    if isinstance(envelope, dict) and "code" in envelope and "message" in envelope:
        return ApiError(
            response.status_code,
            str(envelope["code"]),
            str(envelope["message"]),
            str(envelope.get("request_id") or request_id)
            if (envelope.get("request_id") or request_id)
            else None,
            retry_after,
        )
    return ApiError(
        response.status_code, "unknown_error", response.reason_phrase, request_id, retry_after
    )


class ApiClient:
    """Async. `token` is the bearer every request carries; an operation that
    needs another credential (the sign-in flow) takes it as an argument."""

    def __init__(
        self,
        base_url: str,
        *,
        app: AppName,
        app_version: str,
        token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        retries: int = DEFAULT_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.app = app
        self.app_version = app_version
        self.token = token
        self.timeout = timeout  # seconds, per request; the socket's open shares it
        # The retry arrives with the rest, so it is one client's policy and no
        # caller adds a second round of attempts on top of it.
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            transport=transport,
            timeout=timeout,
            # An injected transport is a test double; the trust store is for the network.
            verify=True if transport is not None else trust_store(),
            headers={
                "Accept": "application/json",
                APP_HEADER: app,
                APP_VERSION_HEADER: app_version,
            },
        )

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def headers(self) -> dict[str, str]:
        """The app headers, for the socket handshake."""
        return {APP_HEADER: self.app, APP_VERSION_HEADER: self.app_version}

    def websocket_url(self, path: str) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        return f"{scheme}://{self.base_url.partition('://')[2]}{path}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        token: str | Unset | None = UNSET,
        idempotency_key: str | None = None,
        if_match: int | None = None,
    ) -> Any:
        """The one call every operation goes through, and the one place a
        request is sent again. Raises `ApiError` on any non-2xx; a 401 clears
        the client's token, since it will not work again.

        A request the API may see twice, and a failure that can differ on a
        second attempt, is retried up to `retries` times, spaced by a delay
        that grows and carries jitter. Anything else is raised as it is: a
        refusal is a decision the API made, and a write the API records no
        outcome for would be a second write."""
        bound = self.retries if may_retry(method, idempotency_key) else 0
        for attempt in range(bound + 1):
            server_asked: float | None = None
            try:
                return await self._attempt(
                    method,
                    path,
                    json=json,
                    params=params,
                    token=token,
                    idempotency_key=idempotency_key,
                    if_match=if_match,
                )
            except ApiError as error:
                if attempt == bound or error.status not in RETRYABLE_STATUSES:
                    raise
                server_asked = error.retry_after
            except RETRYABLE_FAILURES:
                if attempt == bound:
                    raise
            curve = retry_delay_seconds(attempt + 1, self.backoff_seconds)
            await asyncio.sleep(retry_wait_seconds(curve, server_asked))
        raise AssertionError("the loop returns or raises on its last attempt")

    async def _attempt(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        token: str | Unset | None = UNSET,
        idempotency_key: str | None = None,
        if_match: int | None = None,
    ) -> Any:
        """One attempt: the headers this client puts on every call, the send,
        and the answer turned into a view or a typed error. `if_match` is the
        version a write names, sent as the entity tag `If-Match` carries."""
        headers: dict[str, str] = {}
        bearer = self.token if isinstance(token, Unset) else token
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if idempotency_key:
            headers[IDEMPOTENCY_HEADER] = idempotency_key
        if if_match is not None:
            headers["If-Match"] = f'"{if_match}"'
        response = await self._http.request(method, path, json=json, params=params, headers=headers)
        # A delayed refusal belongs to the bearer sent, never a newer sign-in.
        if response.status_code == 401 and isinstance(token, Unset) and self.token == bearer:
            self.token = None
        if response.is_error:
            raise _error_of(response)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            # Something that is not the API answered (a proxy's page, the
            # portal's index.html): said as a refusal, not a traceback.
            raise ApiError(
                response.status_code,
                "not_json",
                f"{method} {path} answered with something other than JSON",
                response.headers.get(REQUEST_ID_HEADER),
            ) from None

    # Tenancy

    async def start_sign_in(
        self,
        redirect_uri: str,
        state: str,
        *,
        invitation_token: str | None = None,
        sign_up: bool = False,
    ) -> SignInStartView:
        """Where a browser goes to sign in at the identity provider; it comes
        back to `redirect_uri` with a code and `state`."""
        body: dict[str, object] = {"redirect_uri": redirect_uri, "state": state, "sign_up": sign_up}
        if invitation_token is not None:
            body["invitation_token"] = invitation_token
        answer = await self.request("POST", "/v1/auth/sign-in", json=body, token=None)
        return SignInStartView.model_validate(answer)

    async def finish_sign_in(
        self, code: str, code_verifier: str, invitation_token: str | None = None
    ) -> IssuedLoginView:
        """The code the browser brought back and the verifier `start_sign_in`
        answered with, exchanged by the API; answered as every sign-in is. A
        person nobody knew is signed up by it."""
        body: dict[str, object] = {"code": code, "code_verifier": code_verifier}
        if invitation_token is not None:
            body["invitation_token"] = invitation_token
        answer = await self.request("POST", "/v1/auth/callback", json=body, token=None)
        return IssuedLoginView.model_validate(answer)

    async def start_device_sign_in(self) -> DeviceSignInView:
        """A sign-in for a program with no browser of its own: the person
        confirms the code at the address the answer names, in any browser."""
        answer = await self.request("POST", "/v1/auth/device", token=None)
        return DeviceSignInView.model_validate(answer)

    async def finish_device_sign_in(self, device_code: str) -> IssuedLoginView:
        """Asks once whether the person confirmed the device sign-in. Before
        they do, an `ApiError` with status 400 and code `sign_in_pending` (or
        `sign_in_slow_down`); the caller asks again after the interval."""
        answer = await self.request(
            "POST", "/v1/auth/device/token", json={"device_code": device_code}, token=None
        )
        return IssuedLoginView.model_validate(answer)

    async def dev_sign_in(self, email: str, display_name: str = "") -> IssuedLoginView:
        """Local and test only: a sign-in by address alone, which a deployed
        environment answers with 404. A person nobody knew is made, with
        their personal org."""
        answer = await self.request(
            "POST",
            "/v1/auth/dev-sign-in",
            json={"email": email, "display_name": display_name},
            token=None,
        )
        return IssuedLoginView.model_validate(answer)

    async def verify_second_factor(self, login_token: str, totp_code: str) -> IssuedLoginView:
        """A sign-in's second factor: a new sign-in that records the verified
        code, which the operator plane asks of an enrolled operator."""
        answer = await self.request(
            "POST", "/v1/auth/second-factor", json={"totp_code": totp_code}, token=login_token
        )
        return IssuedLoginView.model_validate(answer)

    async def exchange_session(self, login_token: str, org_id: UUID) -> IssuedSessionView:
        body = await self.request(
            "POST", "/v1/auth/sessions", json={"org_id": str(org_id)}, token=login_token
        )
        return IssuedSessionView.model_validate(body)

    async def create_org(
        self, name: str, slug: str | None = None, *, idempotency_key: str | None = None
    ) -> MembershipChoiceView:
        """A team org the signed-in person makes and owns; the answer is their
        place in it, which `switch` takes. A creating call, so it always
        carries an idempotency key."""
        body: dict[str, object] = {"name": name}
        if slug is not None:
            body["slug"] = slug
        answer = await self.request(
            "POST", "/v1/orgs", json=body, idempotency_key=idempotency_key or str(uuid4())
        )
        return MembershipChoiceView.model_validate(answer)

    async def memberships(
        self, *, cursor: str | None = None, limit: int = LIMIT_MAX
    ) -> MembershipChoicePageView:
        """The signed-in person's places, with the session the client holds."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = await self.request("GET", "/v1/auth/memberships", params=params)
        return MembershipChoicePageView.model_validate(body)

    async def every_membership(self, limit: int = LIMIT_MAX) -> list[MembershipChoiceView]:
        """Every place, page after page, as `every_user` reads the members."""
        found: list[MembershipChoiceView] = []
        cursor: str | None = None
        while True:
            page = await self.memberships(cursor=cursor, limit=limit)
            found += page.items
            if page.next_cursor is None:
                return found
            cursor = page.next_cursor

    async def switch_session(self, org_id: UUID) -> IssuedSessionView:
        """The exchange presented with the session the client holds: the API
        ends that session in the same write, and the client carries the new
        one from here on, so it never holds two."""
        issued = await self.exchange_session(self._require_token(), org_id)
        self.token = issued.token
        return issued

    def _require_token(self) -> str:
        if not self.token:
            raise ApiError(401, "not_authenticated", "no session to switch from", None)
        return self.token

    async def invitations(
        self, *, cursor: str | None = None, limit: int = LIMIT_MAX
    ) -> InvitationPageView:
        params: dict[str, object] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        answer = await self.request("GET", "/v1/invitations", params=params)
        return InvitationPageView.model_validate(answer)

    async def invite_member(
        self, email: str, role: Role = Role.member, *, idempotency_key: str | None = None
    ) -> InvitationView:
        """The identity provider sends the person the email with the link; a
        creating call, so it always carries an idempotency key."""
        answer = await self.request(
            "POST",
            "/v1/invitations",
            json={"email": email, "role": role.value},
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return InvitationView.model_validate(answer)

    async def resend_invitation(self, invitation_id: UUID) -> InvitationView:
        answer = await self.request("POST", f"/v1/invitations/{invitation_id}/resend")
        return InvitationView.model_validate(answer)

    async def revoke_invitation(self, invitation_id: UUID) -> InvitationView:
        answer = await self.request("DELETE", f"/v1/invitations/{invitation_id}")
        return InvitationView.model_validate(answer)

    async def sso_link(
        self,
        return_url: str,
        intent: Literal["sso", "domain_verification"] = "sso",
    ) -> SsoLinkView:
        answer = await self.request(
            "POST",
            "/v1/orgs/current/sso-link",
            json={"intent": intent, "return_url": return_url},
        )
        return SsoLinkView.model_validate(answer)

    async def logout(self) -> SessionView:
        return SessionView.model_validate(await self.request("POST", "/v1/auth/logout"))

    async def me(self) -> MeView:
        return MeView.model_validate(await self.request("GET", "/v1/me"))

    async def users(self, *, cursor: str | None = None, limit: int = LIMIT_MAX) -> UserPageView:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = await self.request("GET", "/v1/users", params=params)
        return UserPageView.model_validate(body)

    async def every_user(self, limit: int = LIMIT_MAX) -> list[UserView]:
        """Every member, page after page until the API says there is no next
        one: a caller that names people needs the whole list, and a fixed
        limit would silently leave the rest unnamed."""
        users: list[UserView] = []
        cursor: str | None = None
        while True:
            page = await self.users(cursor=cursor, limit=limit)
            users += page.items
            cursor = page.next_cursor
            if cursor is None:
                return users

    # Tasks

    async def tasks(
        self,
        status: TaskStatus = TaskStatus.open,
        scope: TaskScope = TaskScope.team,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> TaskPageView:
        params: dict[str, Any] = {"status": status.value, "scope": scope.value, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return TaskPageView.model_validate(await self.request("GET", "/v1/tasks", params=params))

    async def task(self, task_id: UUID) -> TaskView:
        return TaskView.model_validate(await self.request("GET", f"/v1/tasks/{task_id}"))

    async def create_task(
        self,
        title: str,
        *,
        notes: str = "",
        assignee_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> TaskView:
        """A creating call always carries an idempotency key; a retry with the
        same key returns the task the first call created."""
        body: dict[str, Any] = {"title": title, "notes": notes}
        if assignee_id is not None:
            body["assignee_id"] = str(assignee_id)
        created = await self.request(
            "POST", "/v1/tasks", json=body, idempotency_key=idempotency_key or str(uuid4())
        )
        return TaskView.model_validate(created)

    async def update_task(
        self,
        task_id: UUID,
        *,
        version: int,
        title: str | None = None,
        notes: str | None = None,
        status: TaskStatus | None = None,
        assignee_id: UUID | Unset | None = UNSET,
    ) -> TaskView:
        """A partial update: only what the caller passes is sent. `assignee_id=None`
        unassigns; leaving it out keeps the assignee. `version` is the task's as
        the caller read it, sent in `If-Match`; the API refuses the update with
        412 `precondition_failed` when the task changed since, and the caller
        reads again."""
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if notes is not None:
            body["notes"] = notes
        if status is not None:
            body["status"] = status.value
        if not isinstance(assignee_id, Unset):
            body["assignee_id"] = None if assignee_id is None else str(assignee_id)
        return TaskView.model_validate(
            await self.request("PATCH", f"/v1/tasks/{task_id}", json=body, if_match=version)
        )

    async def move_task(self, task_id: UUID, after_id: UUID | None, version: int) -> TaskView:
        """`version` is the moved task's, as on `update_task`; a move is a POST,
        so it rides the body as `expected_version`."""
        body = {
            "after_id": None if after_id is None else str(after_id),
            "expected_version": version,
        }
        return TaskView.model_validate(
            await self.request("POST", f"/v1/tasks/{task_id}/move", json=body)
        )

    async def delete_task(self, task_id: UUID, version: int) -> TaskView:
        """`version` is the task's, as on `update_task`, in `If-Match`."""
        return TaskView.model_validate(
            await self.request("DELETE", f"/v1/tasks/{task_id}", if_match=version)
        )

    # Events and the channel

    async def events_after(self, after_seq: int, limit: int = LIMIT_MAX) -> list[EventView]:
        body = await self.request(
            "GET", "/v1/events", params={"after_seq": after_seq, "limit": limit}
        )
        return [EventView.model_validate(e) for e in cast(list[Any], body)]

    async def ticket(self) -> IssuedTicketView:
        return IssuedTicketView.model_validate(await self.request("POST", "/v1/realtime/tickets"))

    # The operator plane. The bearer is the operator's own sign-in (the login
    # token), never a tenant session; a caller sets `token` to it.

    async def admin_me(self) -> OperatorView:
        """Who the operator plane admitted and what the entry grants; the check a
        skill makes before its first read."""
        return OperatorView.model_validate(await self.request("GET", "/v1/admin/me"))

    async def admin_size(self) -> PlatformSizeView:
        return PlatformSizeView.model_validate(await self.request("GET", "/v1/admin/size"))

    async def admin_create_org(
        self,
        name: str,
        slug: str,
        *,
        owner_email: str,
        owner_name: str,
        idempotency_key: str | None = None,
    ) -> OrgView:
        """An org with its owner, as `bootstrap` seeds one; a creating call, so
        it always carries an idempotency key."""
        body = {
            "name": name,
            "slug": slug,
            "owner_email": owner_email,
            "owner_name": owner_name,
        }
        created = await self.request(
            "POST", "/v1/admin/orgs", json=body, idempotency_key=idempotency_key or str(uuid4())
        )
        return OrgView.model_validate(created)

    async def admin_add_member(
        self,
        org_id: UUID,
        email: str,
        *,
        display_name: str,
        role: Role = Role.member,
        idempotency_key: str | None = None,
    ) -> UserView:
        """A person in the org, as `add-member` seeds one; a creating call, so
        it always carries an idempotency key."""
        body = {
            "email": email,
            "display_name": display_name,
            "role": role.value,
        }
        added = await self.request(
            "POST",
            f"/v1/admin/orgs/{org_id}/members",
            json=body,
            idempotency_key=idempotency_key or str(uuid4()),
        )
        return UserView.model_validate(added)

    async def admin_org(self, org_id: UUID) -> OrgView:
        return OrgView.model_validate(await self.request("GET", f"/v1/admin/orgs/{org_id}"))

    async def admin_members(
        self, org_id: UUID, *, cursor: str | None = None, limit: int = LIMIT_MAX
    ) -> UserPageView:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = await self.request("GET", f"/v1/admin/orgs/{org_id}/members", params=params)
        return UserPageView.model_validate(body)

    async def admin_tasks(
        self,
        org_id: UUID,
        status: TaskStatus = TaskStatus.open,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> TaskPageView:
        params: dict[str, Any] = {"status": status.value, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = await self.request("GET", f"/v1/admin/orgs/{org_id}/tasks", params=params)
        return TaskPageView.model_validate(body)

    async def admin_events(
        self, org_id: UUID, after_seq: int = 0, limit: int = LIMIT_MAX
    ) -> list[OperatorEventView]:
        body = await self.request(
            "GET",
            f"/v1/admin/orgs/{org_id}/events",
            params={"after_seq": after_seq, "limit": limit},
        )
        return [OperatorEventView.model_validate(e) for e in cast(list[Any], body)]
