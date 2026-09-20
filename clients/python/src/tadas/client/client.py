"""One transport client: bearer, app header, the error envelope parsed into a
typed error carrying the request id, an idempotency key on every creating
call, and the operating system's trust store. The one module in the package
that sends a request; every operation is a method that returns a typed view."""

import ssl
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import httpx
import truststore

from tadas.client.types import (
    EventView,
    IssuedLoginView,
    IssuedSessionView,
    IssuedTicketView,
    MeView,
    SessionView,
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

AppName = Literal["portal", "admin", "cli", "api"]


class Unset:
    """Marks an argument the caller left out, where `None` is itself a value."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET = Unset()


class ApiError(Exception):
    """The API refused: the status and the stable code from the error envelope,
    and the request id to quote when asking why."""

    def __init__(self, status: int, code: str, message: str, request_id: str | None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id

    def __str__(self) -> str:
        suffix = f" (request {self.request_id})" if self.request_id else ""
        return f"{self.code}: {self.message}{suffix}"


def trust_store() -> ssl.SSLContext:
    """The operating system's certificates, for HTTPS and for the socket."""
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _error_of(response: httpx.Response) -> ApiError:
    request_id = response.headers.get(REQUEST_ID_HEADER)
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
        )
    return ApiError(response.status_code, "unknown_error", response.reason_phrase, request_id)


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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.app = app
        self.app_version = app_version
        self.token = token
        self.timeout = timeout  # seconds, per request; the socket's open shares it
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
    ) -> Any:
        """The one call every operation goes through. Raises `ApiError` on any
        non-2xx; a 401 clears the client's token, since it will not work again."""
        headers: dict[str, str] = {}
        bearer = self.token if isinstance(token, Unset) else token
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if idempotency_key:
            headers[IDEMPOTENCY_HEADER] = idempotency_key
        response = await self._http.request(method, path, json=json, params=params, headers=headers)
        if response.status_code == 401 and isinstance(token, Unset):
            self.token = None
        if response.is_error:
            raise _error_of(response)
        return response.json() if response.content else None

    # Tenancy

    async def login(self, email: str, password: str) -> IssuedLoginView:
        body = await self.request(
            "POST", "/v1/auth/login", json={"email": email, "password": password}, token=None
        )
        return IssuedLoginView.model_validate(body)

    async def exchange_session(self, login_token: str, org_id: UUID) -> IssuedSessionView:
        body = await self.request(
            "POST", "/v1/auth/sessions", json={"org_id": str(org_id)}, token=login_token
        )
        return IssuedSessionView.model_validate(body)

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
        the caller read it; the API refuses the update with 409 `version_mismatch`
        when the task changed since, and the caller reads again."""
        body: dict[str, Any] = {"version": version}
        if title is not None:
            body["title"] = title
        if notes is not None:
            body["notes"] = notes
        if status is not None:
            body["status"] = status.value
        if not isinstance(assignee_id, Unset):
            body["assignee_id"] = None if assignee_id is None else str(assignee_id)
        return TaskView.model_validate(
            await self.request("PATCH", f"/v1/tasks/{task_id}", json=body)
        )

    async def move_task(self, task_id: UUID, after_id: UUID | None, version: int) -> TaskView:
        """`version` is the moved task's, as on `update_task`."""
        body = {"after_id": None if after_id is None else str(after_id), "version": version}
        return TaskView.model_validate(
            await self.request("POST", f"/v1/tasks/{task_id}/move", json=body)
        )

    async def delete_task(self, task_id: UUID, version: int) -> TaskView:
        """`version` is the task's, as on `update_task`; a DELETE has no body,
        so it rides the query string."""
        return TaskView.model_validate(
            await self.request("DELETE", f"/v1/tasks/{task_id}", params={"version": version})
        )

    # Events and the channel

    async def events_after(self, after_seq: int, limit: int = LIMIT_MAX) -> list[EventView]:
        body = await self.request(
            "GET", "/v1/events", params={"after_seq": after_seq, "limit": limit}
        )
        return [EventView.model_validate(e) for e in cast(list[Any], body)]

    async def ticket(self) -> IssuedTicketView:
        return IssuedTicketView.model_validate(await self.request("POST", "/v1/realtime/tickets"))
