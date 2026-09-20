"""One session over the fake edge: the steps in order, an idempotency key
on every creating call, the socket seeing its own change, the stream read
from where it stood, and the report at the end. Think time is zero and the
clock is the test's."""

import asyncio

import httpx
import pytest
from fake_api import FakeApi, connect_to

from tadas.client.client import ApiClient
from tadas.ops.environments import Environment, SeedPeople
from tadas.ops.profiles import LIGHT, Profile
from tadas.ops.report import Sample
from tadas.ops.traffic import (
    Clock,
    Person,
    RecordingTransport,
    Session,
    route_template,
    run_traffic,
)

PERSON = Person("owner@example.test", "tadas-local", "acme")


def quick_clock(seconds: float = 30.0) -> Clock:
    loop = asyncio.get_running_loop()
    return Clock(loop.time() + seconds, (0.0, 0.0), now=loop.time, uniform=lambda a, b: 0.0)


def client_over(api: FakeApi, samples: list[Sample]) -> tuple[ApiClient, RecordingTransport]:
    recording = RecordingTransport(httpx.MockTransport(api), also=samples)
    client = ApiClient("http://test", app="portal", app_version="ops@test", transport=recording)
    return client, recording


def test_ids_in_a_path_read_as_a_template() -> None:
    assert (
        route_template("/v1/tasks/0199a4c0-0000-7000-8000-000000000001/move")
        == "/v1/tasks/{id}/move"
    )
    assert route_template("/v1/tasks") == "/v1/tasks"


async def test_a_session_walks_every_step_in_order() -> None:
    api = FakeApi()
    samples: list[Sample] = []
    client, recording = client_over(api, samples)
    async with client:
        session = Session(
            client,
            PERSON,
            quick_clock(),
            recording=recording,
            connect=connect_to(api),
            task_count=lambda: 5,
        )
        outcome = await session.run()
    assert outcome.failure is None, outcome.failure
    assert outcome.completed and outcome.saw_own_change and not outcome.cut
    steps = [f"{r.method} {route_template(r.url.path)}" for r in api.requests]
    assert steps == [
        "POST /v1/auth/login",
        "POST /v1/auth/sessions",
        "POST /v1/realtime/tickets",
        "GET /v1/tasks",
        *["POST /v1/tasks"] * 5,
        "PATCH /v1/tasks/{id}",  # edit one
        "PATCH /v1/tasks/{id}",  # complete two
        "PATCH /v1/tasks/{id}",
        "PATCH /v1/tasks/{id}",  # reopen one
        "POST /v1/tasks/{id}/move",
        "GET /v1/tasks",  # the done list
        "DELETE /v1/tasks/{id}",
        "GET /v1/events",
        "POST /v1/auth/logout",
    ]
    creates = [r for r in api.requests if r.method == "POST" and r.url.path == "/v1/tasks"]
    keys = {r.headers["idempotency-key"] for r in creates}
    assert len(keys) == 5
    assert all(r.headers["x-app"] == "portal" for r in api.requests)
    lists = [r for r in api.requests if r.url.path == "/v1/tasks" and r.method == "GET"]
    assert [r.url.params["status"] for r in lists] == ["open", "done"]
    events = next(r for r in api.requests if r.url.path == "/v1/events")
    assert events.url.params["after_seq"] == "10"  # where the stream stood at the hello
    assert len(outcome.write_request_ids) == 5
    assert len(samples) == len(api.requests)
    assert {s.status for s in samples} == {200, 201}


async def test_a_retried_refusal_is_two_samples_and_a_completed_session() -> None:
    """A keyed creating call the API refused with a 503 is sent again by the
    client; both attempts are requests the report counts."""
    api = FakeApi(fail_on="POST /v1/tasks")
    samples: list[Sample] = []
    client, recording = client_over(api, samples)
    async with client:
        outcome = await Session(
            client,
            PERSON,
            quick_clock(),
            recording=recording,
            connect=connect_to(api),
            task_count=lambda: 5,
        ).run()
    assert outcome.completed and outcome.failure is None
    creates = [s.status for s in samples if s.route == "/v1/tasks" and s.method == "POST"]
    assert creates == [503, 201, 201, 201, 201, 201]
    assert len(outcome.write_request_ids) == 5


async def test_a_refusal_the_client_does_not_retry_fails_the_session() -> None:
    api = FakeApi(fail_on="POST /v1/auth/logout")
    samples: list[Sample] = []
    client, recording = client_over(api, samples)
    async with client:
        outcome = await Session(
            client, PERSON, quick_clock(), recording=recording, connect=connect_to(api)
        ).run()
    assert outcome.failure == "503 unavailable on the API"
    assert not outcome.completed and outcome.saw_own_change
    assert samples[-1].status == 503 and samples[-1].is_error


async def test_the_deadline_cuts_a_session_between_steps() -> None:
    api = FakeApi()
    samples: list[Sample] = []
    client, _ = client_over(api, samples)
    async with client:
        outcome = await Session(client, PERSON, quick_clock(0.0), connect=connect_to(api)).run()
    assert outcome.cut and not outcome.completed and outcome.failure is None
    assert api.requests == []


async def test_a_wrong_password_is_a_failed_session_not_a_crash() -> None:
    api = FakeApi()
    samples: list[Sample] = []
    client, _ = client_over(api, samples)
    async with client:
        outcome = await Session(
            client,
            Person("owner@example.test", "wrong", "acme"),
            quick_clock(),
            connect=connect_to(api),
        ).run()
    assert outcome.failure == "401 invalid_credential on the API"


async def test_a_run_over_the_seeded_org_bounds_sessions_and_reports() -> None:
    api = FakeApi()
    env = Environment(
        name="local",
        api_url="http://test",
        operator_email=None,
        operator_password=None,
        error_tracker_url=None,
        error_tracker_token=None,
        error_tracker_org="tadas",
        error_tracker_project="tadas",
        prometheus_url=None,
        jaeger_url=None,
        aws_profile=None,
        aws_region=None,
        seed=SeedPeople("acme", "owner@example.test", "owner@example.test", "tadas-local"),
    )
    profile = Profile("light", 1, 2, 2, (0.0, 0.0), 60)
    result = await run_traffic(
        env,
        profile,
        duration_seconds=20,
        orgs=0,
        max_sessions=3,
        transport=httpx.MockTransport(api),
        connect=connect_to(api),
    )
    report = result.report
    assert report.sessions.completed == 3 and report.sessions.failed == 0
    assert report.profile == "light" and report.environment == "local"
    assert report.errors == 0 and report.requests == len(api.requests)
    assert any(
        r.route == "/v1/tasks" and r.method == "POST" and r.status == 201 for r in report.routes
    )
    assert report.notes == ["orgs 0: the seeded org 'acme' and its two people"]
    assert len(result.outcomes) == 3 and all(o.write_request_ids for o in result.outcomes)


async def test_a_failed_session_pauses_the_worker_and_a_429_pauses_it_longer() -> None:
    """A refusal at sign-in must not loop into a flood of sign-ins: a worker
    whose session failed waits before the next one, and waits the rate
    limit's window out after a 429."""
    env = Environment(
        name="local",
        api_url="http://test",
        operator_email=None,
        operator_password=None,
        error_tracker_url=None,
        error_tracker_token=None,
        error_tracker_org="tadas",
        error_tracker_project="tadas",
        prometheus_url=None,
        jaeger_url=None,
        aws_profile=None,
        aws_region=None,
        seed=SeedPeople("acme", "owner@example.test", "owner@example.test", "wrong"),
    )
    api = FakeApi()
    profile = Profile("light", 1, 1, 1, (0.0, 0.0), 60)
    result = await run_traffic(
        env,
        profile,
        duration_seconds=0.6,
        orgs=0,
        transport=httpx.MockTransport(api),
        connect=connect_to(api),
        pause_after_failure=0.25,
    )
    assert result.report.sessions.failed in (2, 3)  # not hundreds
    assert all(o.failure == "401 invalid_credential on the API" for o in result.outcomes)

    refused = FakeApi()
    refused.answer = lambda request: httpx.Response(  # type: ignore[method-assign]
        429, json={"error": {"code": "rate_limited", "message": "slow down"}}
    )
    result = await run_traffic(
        env,
        profile,
        duration_seconds=0.6,
        orgs=0,
        transport=httpx.MockTransport(refused),
        connect=connect_to(refused),
        pause_after_failure=0.0,
    )
    assert result.report.sessions.failed == 1  # the 429 pause outlasts the run
    assert result.outcomes[0].rate_limited


async def test_a_run_needs_seeded_people_or_an_operator() -> None:
    env = Environment(
        name="staging",
        api_url="http://test",
        operator_email=None,
        operator_password=None,
        error_tracker_url=None,
        error_tracker_token=None,
        error_tracker_org="t",
        error_tracker_project="t",
        prometheus_url=None,
        jaeger_url=None,
        aws_profile=None,
        aws_region=None,
        seed=None,
    )
    with pytest.raises(ValueError, match="seeded people"):
        await run_traffic(
            env, LIGHT, duration_seconds=1, orgs=0, transport=httpx.MockTransport(FakeApi())
        )
    with pytest.raises(ValueError, match="operator"):
        await run_traffic(
            env, LIGHT, duration_seconds=1, orgs=1, transport=httpx.MockTransport(FakeApi())
        )
