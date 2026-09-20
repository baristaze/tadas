"""The one traffic generator. It drives the edge through the Python client,
never a manager: a session is what a person does in the portal, and a run is
many sessions at once, for a bounded time, at a profile.

A session: sign in, choose the org, open the socket, list the open tasks, add
five or six with an idempotency key each, edit one, complete two, reopen one,
move one, list the done ones, delete one, read the stream after where it
stood at the start, see one of its own changes arrive on the socket, sign
out. A person thinks between steps.

The tenants a run needs come from the operator plane (`POST /v1/admin/orgs`
and its members) with the read-write operator identity of the environment;
`orgs=0` drives the org and the two people `make seed` created instead, which
is how the local stack is exercised with nothing provisioned."""

import asyncio
import logging
import random
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from uuid import UUID, uuid4

import httpx

from tadas.client.client import REQUEST_ID_HEADER, ApiClient, ApiError, trust_store
from tadas.client.envelopes import EntityChanged
from tadas.client.realtime import Channel, Connect, State
from tadas.client.types import TaskStatus, TaskView
from tadas.ops.environments import Environment
from tadas.ops.profiles import Profile
from tadas.ops.report import Report, Sample, Sessions

log = logging.getLogger(__name__)

SESSION_APP = "portal"
"""What a session says it is: the app a person uses. `X-App` must name an
app the wire accepts (`AppType`), and the operator plane is driven as `admin`."""
OPERATOR_APP = "admin"
OWN_CHANGE_TIMEOUT_SECONDS = 10.0
"""How long a session waits for the socket to show it one of its own writes."""
CUT_GRACE_SECONDS = 5.0
"""Past the duration, how long a request already in flight may take to end
before the run stops waiting for it."""
FAILED_SESSION_PAUSE_SECONDS = 5.0
"""A person whose session failed does not sign in again at once. Without the
pause a refusal at sign-in is a tight loop of sign-ins, which is a flood and
not traffic."""
RATE_LIMITED_PAUSE_SECONDS = 15.0
"""A 429 names a window; the next sign-in from this worker waits a good part
of the login window out instead of adding to the count that closed it."""

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def app_version() -> str:
    try:
        return f"ops@{version('tadas-ops')}"
    except PackageNotFoundError:
        return "ops@0"


def route_template(path: str) -> str:
    """`/v1/tasks/<uuid>/move` reads `/v1/tasks/{id}/move`: the report groups
    by route, and an id per line would be a line per request."""
    return _UUID.sub("{id}", path)


class RecordingTransport(httpx.AsyncBaseTransport):
    """Wraps the transport the client sends through and records every request
    as a sample: the route, the status, the time to the last byte, and the
    request id the answer carried. Retries the client makes are requests too,
    so they are recorded too."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        also: list[Sample] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._inner = inner
        self.samples: list[Sample] = []
        self._also = also
        self._clock = clock

    def _record(self, sample: Sample) -> None:
        self.samples.append(sample)
        if self._also is not None:
            self._also.append(sample)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started = self._clock()
        route = route_template(request.url.path)
        try:
            response = await self._inner.handle_async_request(request)
            await response.aread()
        except httpx.HTTPError as failure:
            elapsed = (self._clock() - started) * 1000
            self._record(Sample(route, request.method, 0, elapsed, failure=type(failure).__name__))
            raise
        elapsed = (self._clock() - started) * 1000
        self._record(
            Sample(
                route,
                request.method,
                response.status_code,
                elapsed,
                request_id=response.headers.get(REQUEST_ID_HEADER),
            )
        )
        return response

    async def aclose(self) -> None:
        # The inner transport is shared by every session of a run and closed by the run.
        return None


@dataclass(frozen=True)
class Person:
    """Someone a session runs as: the sign-in and the org to choose."""

    email: str
    password: str
    org_slug: str


class SessionFailed(Exception):
    """A step did not do what a person expects; the session is counted as failed."""


class SessionCut(Exception):
    """The duration ran out mid-session; neither a success nor a failure."""


@dataclass
class SessionOutcome:
    person: Person
    completed: bool = False
    cut: bool = False
    failure: str | None = None
    rate_limited: bool = False
    saw_own_change: bool = False
    write_request_ids: list[str] = field(default_factory=list)
    """The request ids of the creating calls, first to last, for a caller
    that reads the signals back by one of them."""


class Clock:
    """The run's deadline and think time, shared by every session of it."""

    def __init__(
        self,
        deadline: float,
        think_seconds: tuple[float, float],
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.deadline = deadline
        self.think_seconds = think_seconds
        self.now = now
        self.sleep = sleep
        self.uniform = uniform

    @property
    def remaining(self) -> float:
        return self.deadline - self.now()

    def check(self) -> None:
        if self.remaining <= 0:
            raise SessionCut

    async def think(self) -> None:
        """A pause between steps, never past the deadline."""
        self.check()
        low, high = self.think_seconds
        await self.sleep(min(self.uniform(low, high), self.remaining))
        self.check()


class Session:
    """One person's session over one client. `recording` is the transport the
    client sends through, for the request ids of the writes; `connect` opens
    the socket and is injected by tests; the default is the client's own."""

    def __init__(
        self,
        client: ApiClient,
        person: Person,
        clock: Clock,
        *,
        recording: RecordingTransport | None = None,
        connect: Connect | None = None,
        task_count: Callable[[], int] = lambda: random.randint(5, 6),
    ) -> None:
        self.client = client
        self.person = person
        self.clock = clock
        self.samples: list[Sample] = recording.samples if recording is not None else []
        self.connect = connect
        self.task_count = task_count
        self.outcome = SessionOutcome(person)
        self._changes: list[EntityChanged] = []
        self._own_change = asyncio.Event()
        self._opened = asyncio.Event()
        self._user_id: UUID | None = None
        self._start_seq: int | None = None
        self._channel: Channel | None = None

    async def run(self) -> SessionOutcome:
        channel_task: asyncio.Task[None] | None = None
        try:
            await self._sign_in()
            channel_task = asyncio.create_task(self._listen(), name=f"channel-{self.person.email}")
            await self._open_channel()
            await self._work()
            await self._sign_out()
            self.outcome.completed = True
        except SessionCut:
            self.outcome.cut = True
        except SessionFailed as failed:
            self.outcome.failure = str(failed)
        except ApiError as error:
            self.outcome.failure = f"{error.status} {error.code} on the API"
            self.outcome.rate_limited = error.status == 429
        except httpx.HTTPError as failure:
            self.outcome.failure = f"{type(failure).__name__} on the wire"
        finally:
            if channel_task is not None:
                channel_task.cancel()
                try:
                    await channel_task
                except asyncio.CancelledError, Exception:
                    pass
        return self.outcome

    # The steps

    async def _sign_in(self) -> None:
        self.clock.check()
        login = await self.client.login(self.person.email, self.person.password)
        choices = [m for m in login.memberships if m.org.slug == self.person.org_slug]
        if not choices:
            raise SessionFailed(f"{self.person.email} is not a member of {self.person.org_slug}")
        await self.clock.think()
        session = await self.client.exchange_session(login.token, choices[0].org.id)
        self.client.token = session.token
        self._user_id = session.user.id

    async def _listen(self) -> None:
        def on_state(state: State) -> None:
            if state == "open":
                self._opened.set()

        channel = Channel(self.client, on_state=on_state, connect=self.connect)
        self._channel = channel
        async for change in channel:
            self._changes.append(change)
            if change.actor_id == self._user_id:
                self._own_change.set()

    async def _open_channel(self) -> None:
        """Waits for the hello: where the stream stands is where the session
        started, and the read of the stream at the end is from there."""
        try:
            await asyncio.wait_for(self._opened.wait(), max(self.clock.remaining, 0.01))
        except TimeoutError:
            if self.clock.remaining <= 0:
                raise SessionCut from None
            raise SessionFailed("the socket did not open") from None
        assert self._channel is not None
        self._start_seq = self._channel.cursor

    async def _work(self) -> None:
        client = self.client
        await self.clock.think()
        await client.tasks(TaskStatus.open)

        created: list[TaskView] = []
        stamp = uuid4().hex[:8]
        for n in range(self.task_count()):
            await self.clock.think()
            key = str(uuid4())
            created.append(
                await client.create_task(f"ops {stamp} task {n + 1}", idempotency_key=key)
            )
        self.outcome.write_request_ids = [
            s.request_id
            for s in self.samples
            if s.method == "POST" and s.route == "/v1/tasks" and s.status == 201 and s.request_id
        ]

        await self.clock.think()
        edited = await client.update_task(
            created[0].id, version=created[0].version, title=f"{created[0].title} (edited)"
        )
        created[0] = edited

        done: list[TaskView] = []
        for task in created[1:3]:
            await self.clock.think()
            done.append(
                await client.update_task(task.id, version=task.version, status=TaskStatus.done)
            )
        created[1], created[2] = done

        await self.clock.think()
        created[1] = await client.update_task(
            created[1].id, version=created[1].version, status=TaskStatus.open
        )

        await self.clock.think()
        created[3] = await client.move_task(created[3].id, created[0].id, created[3].version)

        await self.clock.think()
        await client.tasks(TaskStatus.done)

        await self.clock.think()
        await client.delete_task(created[4].id, created[4].version)

        await self.clock.think()
        assert self._start_seq is not None
        events = await client.events_after(self._start_seq)
        if not any(e.actor_id == self._user_id for e in events):
            raise SessionFailed("the stream read back none of the session's own changes")

        try:
            await asyncio.wait_for(
                self._own_change.wait(),
                min(OWN_CHANGE_TIMEOUT_SECONDS, max(self.clock.remaining, 0.01)),
            )
        except TimeoutError:
            if self.clock.remaining <= 0:
                raise SessionCut from None
            raise SessionFailed("the socket showed none of the session's own changes") from None
        self.outcome.saw_own_change = True

    async def _sign_out(self) -> None:
        await self.clock.think()
        await self.client.logout()


# Tenants


@dataclass(frozen=True)
class Tenants:
    people: list[Person]
    orgs_created: list[UUID]
    notes: list[str] = field(default_factory=list)


async def seeded_people(env: Environment) -> Tenants:
    if env.seed is None:
        raise ValueError(f"environment {env.name!r} names no seeded people; provision with --orgs")
    seed = env.seed
    people = [
        Person(seed.owner_email, seed.password, seed.slug),
        Person(seed.member_email, seed.password, seed.slug),
    ]
    return Tenants(people, [], [f"orgs 0: the seeded org {seed.slug!r} and its two people"])


async def provision(
    env: Environment, profile: Profile, transport: httpx.AsyncBaseTransport | None = None
) -> Tenants:
    """Tenants for the run through the operator plane, as the read-write
    operator of the environment. The orgs are left behind, named
    `ops-<stamp>-<n>`, so a later run over the same environment can read what
    this one wrote; the operator plane deletes them."""
    if not env.operator_email or not env.operator_password:
        raise ValueError(
            f"environment {env.name!r} names no operator; set TADAS_OPERATOR_EMAIL and _PASSWORD"
        )
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    password = f"ops-{uuid4().hex}"
    people: list[Person] = []
    org_ids: list[UUID] = []
    async with ApiClient(
        env.api_url, app=OPERATOR_APP, app_version=app_version(), transport=transport
    ) as client:
        login = await client.login(env.operator_email, env.operator_password)
        client.token = login.token
        for n in range(profile.orgs):
            slug = f"ops-{stamp}-{n + 1}"
            owner = f"owner@{slug}.example.test"
            org = await client.admin_create_org(
                f"Ops {stamp} {n + 1}",
                slug,
                owner_email=owner,
                owner_password=password,
                owner_name="Ops Owner",
            )
            org_id = org.id
            org_ids.append(org_id)
            people.append(Person(owner, password, slug))
            for m in range(max(profile.members_per_org - 1, 0)):
                email = f"member{m + 1}@{slug}.example.test"
                await client.admin_add_member(
                    org_id,
                    email,
                    password=password,
                    display_name=f"Member {m + 1}",
                )
                people.append(Person(email, password, slug))
    return Tenants(people, org_ids, [f"provisioned {profile.orgs} org(s), {len(people)} people"])


# The run


@dataclass
class RunResult:
    report: Report
    samples: list[Sample]
    outcomes: list[SessionOutcome]


def network_transport() -> httpx.AsyncHTTPTransport:
    return httpx.AsyncHTTPTransport(verify=trust_store())


async def run_traffic(
    env: Environment,
    profile: Profile,
    *,
    duration_seconds: float | None = None,
    orgs: int | None = None,
    ramp_seconds: float = 0.0,
    max_sessions: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    connect: Connect | None = None,
    people: list[Person] | None = None,
    pause_after_failure: float = FAILED_SESSION_PAUSE_SECONDS,
) -> RunResult:
    """Sessions at `profile.concurrency` at once, each over a person of the
    profile's tenants in turn, until the duration is up. The duration is a
    hard bound: a session past it is cut at its next step, and a request in
    flight is given a short grace and then abandoned. The concurrency is a
    semaphore. A linear ramp starts the workers one after another across
    `ramp_seconds`. `max_sessions` bounds the run by count instead, which is
    how one session is driven for a test. A worker whose session failed
    pauses before the next one, longer after a 429, so a refusal never
    becomes a flood."""
    duration = profile.duration_seconds if duration_seconds is None else duration_seconds
    wanted_orgs = profile.orgs if orgs is None else orgs
    inner = transport or network_transport()
    notes: list[str] = []
    if people is None:
        tenants = (
            await seeded_people(env)
            if wanted_orgs == 0
            else await provision(
                env,
                profile
                if orgs is None
                else Profile(
                    profile.name,
                    wanted_orgs,
                    profile.members_per_org,
                    profile.concurrency,
                    profile.think_seconds,
                    profile.duration_seconds,
                ),
                inner,
            )
        )
        people = tenants.people
        notes.extend(tenants.notes)

    samples: list[Sample] = []
    outcomes: list[SessionOutcome] = []
    started_at = datetime.now(UTC)
    started = time.monotonic()
    clock = Clock(started + duration, profile.think_seconds)
    gate = asyncio.Semaphore(profile.concurrency)
    queue: AsyncIterator[Person] = _cycle(people)
    budget = {"left": max_sessions}

    async def worker(index: int) -> None:
        if ramp_seconds > 0 and profile.concurrency > 1:
            await asyncio.sleep(ramp_seconds * index / profile.concurrency)
        while clock.remaining > 0:
            if budget["left"] is not None:
                if budget["left"] <= 0:
                    return
                budget["left"] -= 1
            person = await anext(queue)
            async with gate:
                recording = RecordingTransport(inner, also=samples)
                async with ApiClient(
                    env.api_url, app=SESSION_APP, app_version=app_version(), transport=recording
                ) as client:
                    outcome = await Session(
                        client, person, clock, recording=recording, connect=connect
                    ).run()
                outcomes.append(outcome)
                if outcome.failure:
                    log.info("session as %s failed: %s", person.email, outcome.failure)
            if budget["left"] is not None and budget["left"] <= 0:
                return
            if outcome.failure:
                pause = RATE_LIMITED_PAUSE_SECONDS if outcome.rate_limited else pause_after_failure
                await asyncio.sleep(min(pause, max(clock.remaining, 0.0)))

    workers = [
        asyncio.create_task(worker(i), name=f"traffic-{i}") for i in range(profile.concurrency)
    ]
    try:
        await asyncio.wait_for(
            asyncio.gather(*workers), duration + CUT_GRACE_SECONDS + ramp_seconds
        )
    except TimeoutError:
        notes.append("a session was still in flight past the duration and its grace; abandoned")
        for task in workers:
            task.cancel()
    finally:
        if transport is None:
            await inner.aclose()
    sessions = Sessions(
        completed=sum(o.completed for o in outcomes),
        failed=sum(1 for o in outcomes if o.failure),
        cut=sum(o.cut for o in outcomes),
    )
    report = Report.of(
        samples,
        environment=env.name,
        profile=profile.name,
        started_at=started_at,
        duration_seconds=time.monotonic() - started,
        sessions=sessions,
        notes=notes,
    )
    return RunResult(report, samples, outcomes)


async def _cycle(people: list[Person]) -> AsyncIterator[Person]:
    while True:
        for person in people:
            yield person
