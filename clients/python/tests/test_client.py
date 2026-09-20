"""The transport client over a mock transport: what it sends and how it
turns a refusal into a typed error."""

from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from tadas.client.client import DEFAULT_TIMEOUT_SECONDS, UNSET, ApiClient, ApiError
from tadas.client.realtime import Channel
from tadas.client.types import TaskStatus

TASK = {
    "id": "0199a4c0-0000-7000-8000-000000000001",
    "title": "one",
    "notes": "",
    "status": "open",
    "assignee_id": None,
    "position": 0.0,
    "created_at": "2026-09-18T12:00:00Z",
    "updated_at": "2026-09-18T12:00:00Z",
    "created_by": "0199a4c0-0000-7000-8000-0000000000aa",
    "deleted_at": None,
    "version": 1,
}


class Recorder:
    def __init__(self, respond: dict[str, httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.respond = respond or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond.get(request.url.path, httpx.Response(200, json=TASK))


def client_over(recorder: Recorder, token: str | None = "ses_1") -> ApiClient:
    return ApiClient(
        "http://test/",
        app="cli",
        app_version="cli@test",
        token=token,
        transport=httpx.MockTransport(recorder),
    )


async def test_every_request_carries_bearer_and_app_headers() -> None:
    recorder = Recorder()
    async with client_over(recorder) as client:
        await client.task(UUID(TASK["id"]))
    sent = recorder.requests[0]
    assert sent.headers["authorization"] == "Bearer ses_1"
    assert sent.headers["x-app"] == "cli" and sent.headers["x-app-version"] == "cli@test"
    assert sent.headers["accept"] == "application/json"
    assert client.base_url == "http://test"


async def test_a_creating_call_always_sends_an_idempotency_key() -> None:
    recorder = Recorder()
    async with client_over(recorder) as client:
        await client.create_task("one")
        await client.create_task("two", idempotency_key="given")
    minted, given = recorder.requests
    UUID(minted.headers["idempotency-key"])  # a fresh uuid when none is given
    assert given.headers["idempotency-key"] == "given"
    assert minted.read() == b'{"title":"one","notes":""}'


async def test_update_sends_only_what_was_passed_and_null_unassigns() -> None:
    recorder = Recorder()
    async with client_over(recorder) as client:
        task_id = UUID(TASK["id"])
        await client.update_task(task_id, version=1, status=TaskStatus.done)
        await client.update_task(task_id, version=2, assignee_id=None)
        assignee = uuid4()
        await client.update_task(task_id, version=3, title="t", assignee_id=assignee)
    bodies = [r.read() for r in recorder.requests]
    assert bodies[0] == b'{"version":1,"status":"done"}'
    assert bodies[1] == b'{"version":2,"assignee_id":null}'
    assert bodies[2] == f'{{"version":3,"title":"t","assignee_id":"{assignee}"}}'.encode()
    assert repr(UNSET) == "UNSET"


async def test_every_write_carries_the_version_it_was_given() -> None:
    # The move says it in its body; the delete, which has none, in the query.
    recorder = Recorder()
    async with client_over(recorder) as client:
        task_id, anchor = UUID(TASK["id"]), uuid4()
        await client.move_task(task_id, anchor, version=4)
        await client.move_task(task_id, None, version=5)
        await client.delete_task(task_id, version=6)
    moved, topped, deleted = recorder.requests
    assert moved.read() == f'{{"after_id":"{anchor}","version":4}}'.encode()
    assert topped.read() == b'{"after_id":null,"version":5}'
    assert deleted.method == "DELETE" and deleted.url.params["version"] == "6"


async def test_the_sign_in_flow_uses_the_credential_it_is_given() -> None:
    login = {
        "token": "lgn_1",
        "expires_at": "2026-09-18T13:00:00Z",
        "memberships": [
            {
                "org": {
                    "id": str(uuid4()),
                    "name": "Acme",
                    "slug": "acme",
                    "created_at": "2026-09-18T12:00:00Z",
                    "deleted_at": None,
                },
                "user": {
                    "id": str(uuid4()),
                    "email": "ann@example.test",
                    "display_name": "Ann",
                    "created_at": "2026-09-18T12:00:00Z",
                },
                "role": "owner",
            }
        ],
    }
    session = {
        "token": "ses_2",
        "expires_at": "2026-09-19T12:00:00Z",
        "org": login["memberships"][0]["org"],
        "user": login["memberships"][0]["user"],
        "role": "owner",
    }
    recorder = Recorder(
        {
            "/v1/auth/login": httpx.Response(200, json=login),
            "/v1/auth/sessions": httpx.Response(200, json=session),
        }
    )
    async with client_over(recorder, token=None) as client:
        issued = await client.login("ann@example.test", "pw")
        exchanged = await client.exchange_session(issued.token, issued.memberships[0].org.id)
    assert exchanged.token == "ses_2" and exchanged.org.slug == "acme"
    assert "authorization" not in recorder.requests[0].headers
    assert recorder.requests[1].headers["authorization"] == "Bearer lgn_1"


async def test_a_refusal_is_a_typed_error_with_the_request_id() -> None:
    refusal = httpx.Response(
        404,
        json={"error": {"code": "not_found", "message": "task x not found", "request_id": "r-1"}},
        headers={"x-request-id": "r-1"},
    )
    recorder = Recorder({"/v1/tasks/" + TASK["id"]: refusal})
    async with client_over(recorder) as client:
        with pytest.raises(ApiError) as raised:
            await client.task(UUID(TASK["id"]))
    error = raised.value
    assert (error.status, error.code, error.request_id) == (404, "not_found", "r-1")
    assert str(error) == "not_found: task x not found (request r-1)"


async def test_a_401_clears_the_token_and_a_bare_error_still_types() -> None:
    recorder = Recorder({"/v1/me": httpx.Response(401, text="nope")})
    async with client_over(recorder) as client:
        with pytest.raises(ApiError) as raised:
            await client.me()
        assert client.token is None
    assert raised.value.code == "unknown_error" and raised.value.status == 401


def test_websocket_url_follows_the_scheme() -> None:
    plain = ApiClient("http://127.0.0.1:8000", app="cli", app_version="v")
    secure = ApiClient("https://api.tadas.fyi/", app="cli", app_version="v")
    assert plain.websocket_url("/v1/realtime") == "ws://127.0.0.1:8000/v1/realtime"
    assert secure.websocket_url("/v1/realtime") == "wss://api.tadas.fyi/v1/realtime"
    assert plain.headers == {"X-App": "cli", "X-App-Version": "v"}


def test_every_call_and_the_socket_open_carry_the_timeout() -> None:
    given = ApiClient("http://test", app="cli", app_version="v", timeout=4.5)
    assert given.timeout == 4.5 and given._http.timeout == httpx.Timeout(4.5)
    opening = cast(Any, Channel(given)._connect_default("ws://127.0.0.1:1/v1/realtime", {}))
    assert opening.open_timeout == 4.5  # built, not entered: nothing connects
    default = ApiClient("http://test", app="cli", app_version="v")
    assert default.timeout == DEFAULT_TIMEOUT_SECONDS
    assert default._http.timeout == httpx.Timeout(DEFAULT_TIMEOUT_SECONDS)


async def test_a_401_from_an_old_request_keeps_the_replacement_token() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ses_old"
        client.token = "ses_new"  # another sign-in completed while this request was in flight
        return httpx.Response(401, text="nope")

    async with ApiClient(
        "http://test",
        app="cli",
        app_version="cli@test",
        token="ses_old",
        transport=httpx.MockTransport(respond),
    ) as client:
        with pytest.raises(ApiError):
            await client.me()
        assert client.token == "ses_new"
