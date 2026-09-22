"""The telemetry round trip: the API as a real process on port 8000 (the one
host target the devx collector scrapes and writes into Prometheus), with the
trace exporter and the error tracker set, one session of traffic through the
edge, and then every signal read back by request id through the local
reader: the log line that names it, the counter that moved, the trace that
exists, the error event that carries it.

The error leg is a second process of the same binary on a free port whose
database is unreachable: a route that raises past the gateway is answered
500 with the request id and reported to the tracker, which is the one path
that produces an ERROR without a code change and without harming the session
the other legs read. Needs the devx profile and a migrated, seeded stack;
skips, naming why, when it cannot run."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml

from tadas.ops.environments import Environment, load_environment, parse_env_file
from tadas.ops.profiles import LIGHT
from tadas.ops.signals.local import SignalsLocalImpl
from tadas.ops.traffic import run_traffic

pytestmark = pytest.mark.telemetry

REPO = Path(__file__).resolve().parents[2]
PORT = 8000
COLLECTOR_CONFIG = REPO / "deployment" / "local" / "otel-collector" / "collector.yml"
OTLP_ENDPOINT = "http://127.0.0.1:54318"
BOOT_SECONDS = 30
TRACE_WAIT_SECONDS = 30
ERROR_WAIT_SECONDS = 60
REQUESTS_COUNTER = "tadas_http_requests_total"
DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0}


def duration_seconds(text: str) -> float:
    """A collector duration (`15s`, `500ms`, `1m`) in seconds."""
    for unit in sorted(DURATION_UNITS, key=len, reverse=True):
        if text.endswith(unit):
            return float(text.removesuffix(unit)) * DURATION_UNITS[unit]
    raise ValueError(f"not a duration: {text!r}")


def scrape_wait_seconds() -> float:
    """How long a counter takes to reach Prometheus, from the collector's own
    config: a scrape that sees it comes within one scrape interval, and the
    batch that holds it goes out within the batch timeout. The deadline is
    three intervals and one flush, so a missed or slow scrape and a retried
    send still land inside it."""
    config = yaml.safe_load(COLLECTOR_CONFIG.read_text())
    interval = duration_seconds(
        config["receivers"]["prometheus"]["config"]["global"]["scrape_interval"]
    )
    flush = duration_seconds(config["processors"]["batch"]["timeout"])
    return 3 * interval + flush


SCRAPE_WAIT_SECONDS = scrape_wait_seconds()


def port_taken(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def reachable(url: str) -> bool:
    try:
        httpx.get(url, timeout=2.0)
    except httpx.HTTPError:
        return False
    return True


@dataclass
class Served:
    port: int
    log: Path
    process: subprocess.Popen[bytes]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def lines(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.is_file() else []

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(5)


def compose_knobs() -> dict[str, str]:
    """`.env.example`, and the developer's `.env` over it where one exists."""
    knobs: dict[str, str] = {}
    for name in (".env.example", ".env"):
        if (REPO / name).is_file():
            knobs.update(parse_env_file((REPO / name).read_text()))
    return knobs


def serve(port: int, log: Path, overrides: dict[str, str]) -> Served:
    """The API binary as a process, over the compose knobs and the overrides,
    its stderr (the log) to a file the reader is handed."""
    env = {**os.environ, **compose_knobs(), **overrides}
    handle = log.open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "tadas.services.api.entry", "serve", "--port", str(port)],
        cwd=REPO,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    served = Served(port, log, process)
    deadline = time.monotonic() + BOOT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        if reachable(f"{served.base_url}/healthz"):
            return served
        time.sleep(0.5)
    served.stop()
    pytest.fail(f"the API did not come up on {port}:\n" + "\n".join(served.lines()[-20:]))


@pytest.fixture(scope="module")
def env() -> Environment:
    return load_environment("local", root=REPO)


@pytest.fixture(scope="module")
def stores(env: Environment) -> None:
    for name, url in (
        ("Prometheus", f"{env.prometheus_url}/-/ready"),
        ("Jaeger", f"{env.jaeger_url}/api/v3/services"),
        ("GlitchTip", f"{env.error_tracker_url}/api/0/"),
    ):
        if not reachable(url):
            pytest.skip(f"{name} is not reachable at {url}: needs the devx profile (make devx-up)")


@pytest.fixture(scope="module")
def api(stores: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Served]:
    if port_taken(PORT):
        pytest.skip(
            f"port {PORT} is taken (the api container, or scripts/dev.sh); the collector scrapes "
            "only 8000 on the host, so the round trip needs it"
        )
    knobs = compose_knobs()
    served = serve(
        PORT,
        tmp_path_factory.mktemp("api") / "api.log",
        {
            "TADAS_ENVIRONMENT": "local",
            "TADAS_OTEL_ENDPOINT": OTLP_ENDPOINT,
            "TADAS_SENTRY_DSN": knobs["TADAS_SENTRY_DSN"],
            "TADAS_LOG_JSON": "true",
        },
    )
    yield served
    served.stop()


@pytest.fixture(scope="module")
def broken_api(stores: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Served]:
    """The same binary with no database behind it: every tenant route raises."""
    knobs = compose_knobs()
    served = serve(
        free_port(),
        tmp_path_factory.mktemp("broken") / "api.log",
        {
            "TADAS_ENVIRONMENT": "local",
            "TADAS_DATABASE_URL": "postgresql+asyncpg://tadas:tadas@127.0.0.1:1/tadas",
            "TADAS_CACHE_BACKEND": "memory",
            "TADAS_TOPICS_BACKEND": "memory",
            "TADAS_BUCKETS_BACKEND": "local",
            "TADAS_QUEUES_BACKEND": "memory",
            "TADAS_OTEL_ENDPOINT": OTLP_ENDPOINT,
            "TADAS_SENTRY_DSN": knobs["TADAS_SENTRY_DSN"],
            "TADAS_LOG_JSON": "true",
        },
    )
    yield served
    served.stop()


def reader(env: Environment, served: Served) -> SignalsLocalImpl:
    assert env.prometheus_url and env.jaeger_url and env.error_tracker_url
    return SignalsLocalImpl(
        prometheus_url=env.prometheus_url,
        jaeger_url=env.jaeger_url,
        error_tracker_url=env.error_tracker_url,
        error_tracker_token=env.error_tracker_token or "",
        error_tracker_org=env.error_tracker_org,
        logs=served.lines,
    )


async def poll[T](
    read: Callable[[], Awaitable[T | None]], seconds: float, every: float = 2.0
) -> T | None:
    deadline = time.monotonic() + seconds
    while True:
        found = await read()
        if found or time.monotonic() >= deadline:
            return found
        await asyncio.sleep(every)


async def test_every_signal_reads_back_by_the_request_id_of_a_write(
    env: Environment, api: Served
) -> None:
    since = datetime.now(UTC) - timedelta(seconds=5)
    result = await run_traffic(env, LIGHT, duration_seconds=90, orgs=0, max_sessions=1)
    outcome = result.outcomes[0]
    assert outcome.completed, outcome.failure or result.report.table()
    assert outcome.saw_own_change
    request_id = outcome.write_request_ids[0]
    signals = reader(env, api)
    writes = len(outcome.write_request_ids)

    # The log line that names it.
    lines = await signals.log_lines(request_id)
    assert lines, f"no log line carries {request_id}"
    assert any("POST /v1/tasks 201" in line for line in lines), lines

    # The counter that moved: the collector's scrape and its batch lag the run.
    labels = {"route": "/v1/tasks", "method": "POST", "status": "201"}

    async def counted() -> float | None:
        delta = await signals.metric_delta(REQUESTS_COUNTER, labels, since)
        return delta if delta and delta >= writes else None

    delta = await poll(counted, SCRAPE_WAIT_SECONDS, every=5.0)
    assert delta is not None, f"Prometheus did not count the {writes} creating calls"

    # The trace that exists: the batch exporter ships every few seconds.
    trace = await poll(lambda: signals.trace(request_id), TRACE_WAIT_SECONDS)
    assert trace is not None, f"Jaeger holds no trace with tadas.request_id={request_id}"
    assert "POST /v1/tasks" in trace.span_names, trace


async def test_an_error_event_carries_the_request_id(env: Environment, broken_api: Served) -> None:
    request_id = str(uuid4())
    async with httpx.AsyncClient(base_url=broken_api.base_url, timeout=15.0) as http:
        response = await http.get(
            "/v1/tasks",
            headers={
                "x-request-id": request_id,
                "Authorization": "Bearer ses_none",
                "X-App": "cli",
            },
        )
    assert response.status_code == 500, response.text
    assert response.headers["x-request-id"] == request_id
    signals = reader(env, broken_api)
    lines = await signals.log_lines(request_id)
    assert any('"level": "ERROR"' in line for line in lines), lines
    # The tag is the proof; the title is the exception's, as the tracker names it.
    event = await poll(lambda: signals.error_event(request_id), ERROR_WAIT_SECONDS, every=5.0)
    assert event is not None, f"GlitchTip holds no event tagged request_id={request_id}"
    assert event.title, event
