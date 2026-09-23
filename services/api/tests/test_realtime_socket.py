"""A refused ticket is a close with 4401 on an open socket, never a
handshake failure: the socket is accepted first, then the ticket is
redeemed. An admitted socket lives as long as the credential behind its
ticket and no longer."""

import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from api_support import OWNER, add_member, build_container, on_plan, run, seed_request, sign_in_as
from httpx import ASGITransport
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.types import Message, Scope
from starlette.websockets import WebSocketDisconnect
from uvicorn.protocols.utils import ClientDisconnected

from tadas.infra.exceptions import BackendFailed
from tadas.infra.topics import Topics
from tadas.om.base import utcnow
from tadas.om.billing.types.plan import Plan
from tadas.om.opcontext import OpContext, Role
from tadas.om.tenancy.rules import hash_token
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer
from tadas.services.api.gateway.auth import CLOSE_UNAUTHENTICATED
from tadas.services.api.realtime.envelopes import ErrorEnvelope
from tadas.services.api.realtime.send_buffer import SendBuffer
from tadas.services.api.services.realtime import CREDENTIAL_REVOKED, MEMBERSHIP_ENDED


def test_a_refused_ticket_closes_the_accepted_socket_with_4401(tmp_path: Path) -> None:
    with TestClient(create_app(build_container(tmp_path))) as tc:
        with tc.websocket_connect("/v1/realtime?ticket=wst_not_a_ticket") as ws:
            # The handshake succeeded; the refusal is the first thing received.
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == "not_authenticated"


def test_a_missing_ticket_closes_the_accepted_socket_with_4401(tmp_path: Path) -> None:
    """No ticket at all is the same refusal as a bad one, not a handshake
    failure the client cannot tell from any other."""
    with TestClient(create_app(build_container(tmp_path))) as tc:
        with tc.websocket_connect("/v1/realtime") as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == "not_authenticated"


def test_a_client_that_drops_mid_stream_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The drainer dies the way it does when the peer is gone; the teardown
    that follows is the normal end of a socket, not an unhandled exception."""
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
        )
    )

    async def dead_drain(self: SendBuffer, websocket: object) -> None:
        raise OSError("client gone")

    monkeypatch.setattr(SendBuffer, "drain", dead_drain)
    with TestClient(create_app(container)) as tc:
        login = tc.post("/v1/auth/dev-sign-in", json={"email": OWNER["email"]})
        session = tc.post(
            "/v1/auth/sessions",
            json={"org_id": str(org.id)},
            headers={"Authorization": f"Bearer {login.json()['token']}"},
        )
        headers = {"Authorization": f"Bearer {session.json()['token']}"}
        ticket = tc.post("/v1/realtime/tickets", headers=headers).json()["ticket"]
        with caplog.at_level(logging.ERROR):
            with tc.websocket_connect(f"/v1/realtime?ticket={ticket}"):
                pass  # the client leaves at once
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_the_close_after_the_peer_left_is_not_an_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The app driven the way uvicorn drives it: once the peer's disconnect
    has been read, every send raises the server's disconnect error, which
    Starlette turns into a 1006 disconnect. The handler's own close after
    that is the normal end of a socket: nothing escapes the app and nothing
    is logged as an error."""
    container = build_container(tmp_path)
    _, org = await container.managers.tenancy.bootstrap(
        seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
    )
    app = create_app(container)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = await sign_in_as(client, OWNER["email"], org.id)
            ticket = (await client.post("/v1/realtime/tickets", headers=headers)).json()["ticket"]
        inbound: asyncio.Queue[Message] = asyncio.Queue()
        outbound: list[Message] = []
        gone = False

        async def receive() -> Message:
            nonlocal gone
            message = await inbound.get()
            if message["type"] == "websocket.disconnect":
                gone = True
            return message

        async def send(message: Message) -> None:
            if gone:
                raise ClientDisconnected()
            outbound.append(message)

        await inbound.put({"type": "websocket.connect"})
        await inbound.put({"type": "websocket.disconnect", "code": 1001})
        with caplog.at_level(logging.ERROR):
            await app(socket_scope(ticket), receive, send)
    assert [m["type"] for m in outbound] == ["websocket.accept", "websocket.send"]
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


def socket_scope(ticket: str) -> Scope:
    """The ASGI scope of a socket handshake on the channel route."""
    return {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": "/v1/realtime",
        "raw_path": b"/v1/realtime",
        "root_path": "",
        "query_string": f"ticket={ticket}".encode(),
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 40000),
        "server": ("test", 80),
        "subprotocols": [],
    }


def test_a_binary_frame_is_a_bad_command_and_the_socket_stays_open(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
        )
    )
    with TestClient(create_app(container)) as tc:
        owner = sign_in(tc, OWNER["email"], org.id)
        with open_socket(tc, owner) as ws:
            assert ws.receive_json()["type"] == "hello"
            ws.send_bytes(b"\x00\x01")
            refused = ErrorEnvelope.model_validate(ws.receive_json())
            assert refused.code == "bad_command"
            ws.send_json({"op": "ping"})
            assert ws.receive_json()["type"] == "pong"


def session_token(container: AppContainer) -> str:
    """Signs the owner in and returns the session token."""
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
        )
    )
    tenancy = container.managers.tenancy

    async def issue() -> str:
        login = await tenancy.dev_sign_in(seed_request(), OWNER["email"])
        identity = await tenancy.authenticate_login(seed_request(), login.token)
        return (await tenancy.exchange_login(identity, org.id)).token

    return run(issue())


def expire_session_in(container: AppContainer, token: str, seconds: float) -> None:
    """Shortens the session behind the token in storage."""
    storage = container.storage.get_tenancy_storage()
    found = run(storage.read_session_by_digest(hash_token(token)))
    assert found is not None
    org_id, session = found
    shortened = session.model_copy(update={"expires_at": utcnow() + timedelta(seconds=seconds)})
    run(storage.write_session(org_id, shortened))


def test_a_socket_is_closed_with_4401_when_the_session_behind_it_expires(tmp_path: Path) -> None:
    """The client does nothing; the server closes at the session's expiry.
    The session is shortened once the app is up and the ticket issued, so a
    slow start does not spend the lifetime before the socket opens."""
    container = build_container(tmp_path)
    token = session_token(container)
    with TestClient(create_app(container)) as tc:
        headers = {"Authorization": f"Bearer {token}"}
        ticket = tc.post("/v1/realtime/tickets", headers=headers).json()["ticket"]
        expire_session_in(container, token, 1.0)
        with tc.websocket_connect(f"/v1/realtime?ticket={ticket}") as ws:
            assert ws.receive_json()["type"] == "hello"
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == "credential_expired"


def sign_in(tc: TestClient, email: str, org_id: UUID) -> dict[str, str]:
    login = tc.post("/v1/auth/dev-sign-in", json={"email": email})
    session = tc.post(
        "/v1/auth/sessions",
        json={"org_id": str(org_id)},
        headers={"Authorization": f"Bearer {login.json()['token']}"},
    )
    return {"Authorization": f"Bearer {session.json()['token']}"}


def open_socket(tc: TestClient, headers: dict[str, str]) -> WebSocketTestSession:
    ticket = tc.post("/v1/realtime/tickets", headers=headers).json()["ticket"]
    return tc.websocket_connect(f"/v1/realtime?ticket={ticket}")


def test_revoking_the_session_behind_a_socket_closes_it_and_no_other(tmp_path: Path) -> None:
    """The revocation travels the bus like any change: the socket of the
    session revoked closes with 4401, a socket of another session stays."""
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
        )
    )
    with TestClient(create_app(container)) as tc:
        first = sign_in(tc, OWNER["email"], org.id)
        second = sign_in(tc, OWNER["email"], org.id)
        with open_socket(tc, first) as ws:
            assert ws.receive_json()["type"] == "hello"
            assert tc.post("/v1/auth/logout", headers=second).status_code == 200
            ws.send_json({"op": "ping"})
            assert ws.receive_json()["type"] == "pong"  # still open: another session went
            assert tc.post("/v1/auth/logout", headers=first).status_code == 200
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == CREDENTIAL_REVOKED


def test_removing_a_member_closes_their_socket(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
        )
    )
    bob = run(add_member(container, org.id, "bob@example.test", Role.MEMBER))
    with TestClient(create_app(container)) as tc:
        owner = sign_in(tc, OWNER["email"], org.id)
        member = sign_in(tc, "bob@example.test", org.id)
        with open_socket(tc, member) as ws:
            assert ws.receive_json()["type"] == "hello"
            assert tc.delete(f"/v1/memberships/{bob.id}", headers=owner).status_code == 200
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == MEMBERSHIP_ENDED


def test_revoking_an_api_key_closes_the_socket_it_opened(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
        )
    )
    run(on_plan(container, org.id, Plan.TEAM))
    with TestClient(create_app(container)) as tc:
        owner = sign_in(tc, OWNER["email"], org.id)
        issued = tc.post("/v1/api-keys", headers=owner, json={"name": "ci", "role": "member"})
        key = {"Authorization": f"Bearer {issued.json()['key']}"}
        with open_socket(tc, key) as ws:
            assert ws.receive_json()["type"] == "hello"
            key_id = issued.json()["api_key"]["id"]
            assert tc.delete(f"/v1/api-keys/{key_id}", headers=owner).status_code == 200
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == CREDENTIAL_REVOKED


def test_a_hello_that_cannot_read_the_head_leaves_no_task_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The head read is the socket's first I/O and it can fail: a database out
    of reach is exactly when every client reconnects at once. The drainer must
    not exist yet when it does, or each of those reconnects leaves a task
    waiting on its buffer for the life of the process."""
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
        )
    )

    async def unreachable(self: object, ctx: object) -> int:
        raise BackendFailed("postgres", "read_head", "connection refused")

    monkeypatch.setattr(type(container.services.get_realtime_service()), "head", unreachable)

    drains: list[str] = []
    real_drain = SendBuffer.drain

    async def counted_drain(self: SendBuffer, websocket: object) -> None:
        drains.append("started")
        await real_drain(self, websocket)  # type: ignore[arg-type]

    monkeypatch.setattr(SendBuffer, "drain", counted_drain)
    with TestClient(create_app(container)) as tc:
        headers = sign_in(tc, OWNER["email"], org.id)
        with pytest.raises(WebSocketDisconnect) as closed:
            with open_socket(tc, headers) as ws:
                ws.receive_json()  # the hello that the failed read never built
    assert drains == [], "the drainer was created before the read that failed"
    # The socket was accepted before the route ran, so the failure is a close
    # frame and not an HTTP response the server would refuse as a protocol error.
    assert closed.value.code == 1011
    assert closed.value.reason == "internal_error"


def test_a_revocation_during_the_hello_still_closes_the_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ticket was good when it was redeemed, and the session is revoked
    while the socket reads its head: the socket is attached before that read,
    so the revocation finds it and it closes with 4401 instead of living until
    the session would have expired."""
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
        )
    )
    service = container.services.get_realtime_service()
    working = service.head
    revoked: list[bool] = []

    async def head_while_revoked(ctx: OpContext) -> int:
        if not revoked:
            revoked.append(True)
            assert ctx.credential_id is not None
            await container.managers.tenancy.revoke_session(ctx, ctx.credential_id)
        return await working(ctx)

    monkeypatch.setattr(service, "head", head_while_revoked)
    with TestClient(create_app(container)) as tc:
        headers = sign_in(tc, OWNER["email"], org.id)
        with open_socket(tc, headers) as ws:
            # The hello may or may not go out before the close does.
            with pytest.raises(WebSocketDisconnect) as closed:
                while True:
                    assert ws.receive_json()["type"] == "hello"
    assert revoked == [True]
    assert closed.value.code == CLOSE_UNAUTHENTICATED
    assert closed.value.reason == CREDENTIAL_REVOKED


def socket_handlers(container: AppContainer) -> int:
    """The topic handlers this process holds for sockets. One per open socket
    that subscribed; a socket that ended and left one behind is a leak."""
    topics = container.infra.get_topics()
    subscribers = topics._subscribers._handlers.get(Topics.ENTITY_CHANGED, {})  # type: ignore[attr-defined]
    return sum(1 for consumer, _ in subscribers.values() if consumer.startswith("socket:"))


def test_a_command_that_fails_closes_the_socket_and_leaves_no_subscription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every client pings, and a ping reads the stream head: a database blip
    during one ends the command loop with a backend error. The socket is
    accepted, so there is no HTTP response left to answer with; it closes with
    1011 and its subscription and drainer go with it. Before, the error
    escaped the teardown and the handler stayed in the dispatcher forever."""
    container = build_container(tmp_path)
    _, org = run(
        container.managers.tenancy.bootstrap(
            seed_request(), "Acme", "acme", OWNER["email"], OWNER["name"]
        )
    )
    service = type(container.services.get_realtime_service())
    working = service.head
    failing = {"now": False}

    async def head(self: object, ctx: object) -> int:
        if failing["now"]:
            raise BackendFailed("postgres", "read_head", "connection refused")
        return await working(self, ctx)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "head", head)
    with TestClient(create_app(container)) as tc:
        headers = sign_in(tc, OWNER["email"], org.id)
        with open_socket(tc, headers) as ws:
            assert ws.receive_json()["type"] == "hello"
            ws.send_json({"op": "subscribe", "topic": "entity_changed"})
            assert ws.receive_json()["type"] == "subscribed"
            assert socket_handlers(container) == 1
            failing["now"] = True
            ws.send_json({"op": "ping"})
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == 1011
    assert closed.value.reason == "internal_error"
    assert socket_handlers(container) == 0, "the socket's subscription outlived it"
