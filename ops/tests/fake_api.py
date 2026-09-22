"""A stateful stand-in for the API over `httpx.MockTransport`, and a socket
that pushes what the fake wrote: enough of the edge for a session to run end
to end in-process, with no server."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx

from tadas.ops.traffic import route_template

ORG_ID = UUID("0199a4c0-0000-7000-8000-00000000000a")
OWNER_ID = UUID("0199a4c0-0000-7000-8000-0000000000aa")
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC).isoformat()

ORG = {"id": str(ORG_ID), "name": "Acme", "slug": "acme", "created_at": NOW, "deleted_at": None}
USER = {
    "id": str(OWNER_ID),
    "email": "owner@example.test",
    "display_name": "Owner",
    "created_at": NOW,
}


class FakeApi:
    """Routes a session touches, with a task table and a stream. Every answer
    carries an `x-request-id`; a write appends an event and pushes it to any
    open socket."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.seq = 10
        self.requests: list[httpx.Request] = []
        self.sockets: list[FakeSocket] = []
        self.fail_on = fail_on
        """"METHOD path" answered 503 once; the path may be a route template
        (`DELETE /v1/tasks/{id}`), since a test knows no id in advance."""

    def _event(self, kind: str, target_id: str) -> None:
        self.seq += 1
        event = {
            "actor_id": str(OWNER_ID),
            "kind": kind,
            "produced_at": NOW,
            "seq": self.seq,
            "target_id": target_id,
        }
        self.events.append(event)
        for socket in self.sockets:
            socket.push(event)

    def _task(self, title: str) -> dict[str, Any]:
        task = {
            "id": str(uuid4()),
            "title": title,
            "notes": "",
            "status": "open",
            "assignee_id": None,
            "position": float(len(self.tasks)),
            "created_at": NOW,
            "updated_at": NOW,
            "created_by": str(OWNER_ID),
            "deleted_at": None,
            "version": 1,
        }
        self.tasks[task["id"]] = task
        return task

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.answer(request)
        response.headers["x-request-id"] = str(uuid4())
        return response

    def answer(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        if self.fail_on in (f"{method} {path}", f"{method} {route_template(path)}"):
            self.fail_on = None
            return httpx.Response(503, json={"error": {"code": "unavailable", "message": "no"}})
        if request.headers.get("x-app") not in ("portal", "admin", "cli", "api"):
            return httpx.Response(
                422, json={"error": {"code": "validation_failed", "message": "app"}}
            )
        body = json.loads(request.content) if request.content else {}
        if (method, path) == ("POST", "/v1/auth/login"):
            if body.get("password") != "tadas-local":
                return httpx.Response(
                    401, json={"error": {"code": "invalid_credential", "message": "no"}}
                )
            return httpx.Response(
                200,
                json={
                    "token": "lgn_1",
                    "expires_at": NOW,
                    "memberships": [{"org": ORG, "role": "owner", "user": USER}],
                },
            )
        if (method, path) == ("POST", "/v1/auth/sessions"):
            return httpx.Response(
                200,
                json={
                    "token": "ses_1",
                    "expires_at": NOW,
                    "org": ORG,
                    "role": "owner",
                    "user": USER,
                },
            )
        if request.headers.get("authorization") != "Bearer ses_1":
            return httpx.Response(
                401, json={"error": {"code": "not_authenticated", "message": "no"}}
            )
        if (method, path) == ("POST", "/v1/auth/logout"):
            return httpx.Response(
                200,
                json={
                    "id": str(uuid4()),
                    "credential_kind": "session_token",
                    "created_at": NOW,
                    "expires_at": NOW,
                    "revoked_at": NOW,
                },
            )
        if (method, path) == ("GET", "/v1/tasks"):
            status = request.url.params.get("status", "open")
            items = [
                t for t in self.tasks.values() if t["status"] == status and not t["deleted_at"]
            ]
            return httpx.Response(200, json={"items": items, "next_cursor": None})
        if (method, path) == ("POST", "/v1/tasks"):
            if not request.headers.get("idempotency-key"):
                return httpx.Response(
                    422, json={"error": {"code": "validation_failed", "message": "key"}}
                )
            task = self._task(body["title"])
            self._event("tasks.task.created", task["id"])
            return httpx.Response(201, json=task)
        if (method, path) == ("POST", "/v1/realtime/tickets"):
            return httpx.Response(200, json={"ticket": "wst_1", "expires_in_seconds": 30})
        if (method, path) == ("GET", "/v1/events"):
            after = int(request.url.params.get("after_seq", 0))
            return httpx.Response(200, json=[e for e in self.events if e["seq"] > after])
        parts = path.split("/")
        if len(parts) >= 4 and parts[2] == "tasks" and parts[3] in self.tasks:
            task = self.tasks[parts[3]]
            if method == "PATCH":
                if request.headers.get("if-match") != f'"{task["version"]}"':
                    return httpx.Response(
                        412, json={"error": {"code": "precondition_failed", "message": "stale"}}
                    )
                for key in ("title", "notes", "status"):
                    if key in body:
                        task[key] = body[key]
                task["version"] += 1
                self._event("tasks.task.updated", task["id"])
                return httpx.Response(200, json=task)
            if method == "POST" and len(parts) == 5 and parts[4] == "move":
                task["version"] += 1
                self._event("tasks.task.moved", task["id"])
                return httpx.Response(200, json=task)
            if method == "DELETE":
                task["deleted_at"] = NOW
                task["version"] += 1
                self._event("tasks.task.deleted", task["id"])
                return httpx.Response(200, json=task)
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})


class FakeSocket:
    def __init__(self, api: FakeApi) -> None:
        self.api = api
        self.frames: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[str] = []
        self.frames.put_nowait(
            json.dumps(
                {
                    "type": "hello",
                    "org_id": str(ORG_ID),
                    "user_id": str(OWNER_ID),
                    "seq": api.seq,
                    "ping_interval_seconds": 30,
                }
            )
        )

    def push(self, event: dict[str, Any]) -> None:
        payload = {k: event[k] for k in ("kind", "target_id", "seq", "actor_id")}
        self.frames.put_nowait(
            json.dumps({"type": "event", "topic": "entity_changed", "payload": payload})
        )

    async def recv(self) -> str | bytes:
        return await self.frames.get()

    async def send(self, message: str) -> None:
        self.sent.append(message)
        if '"subscribe"' in message:
            self.frames.put_nowait(json.dumps({"type": "subscribed", "topic": "entity_changed"}))


def connect_to(api: FakeApi):
    @asynccontextmanager
    async def connect(url: str, headers: dict[str, str]):
        socket = FakeSocket(api)
        api.sockets.append(socket)
        try:
            yield socket
        finally:
            api.sockets.remove(socket)

    return connect
