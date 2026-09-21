"""The worker binary: settings, container, stop handlers, `serve`, and the
`health` probe, which asks the serving process's `/healthz`."""

import argparse
import asyncio
import logging
import signal
import sys
import urllib.error
import urllib.request
from datetime import timedelta

from tadas.infra.cache import CacheScope
from tadas.infra.observability import (
    configure_error_reporting,
    configure_logging,
    configure_tracing,
    name_process,
)
from tadas.infra.trust import install_trust_store
from tadas.om.base import EMPTY_UUID
from tadas.om.work.types.work_item import WorkKind
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.handler import NoopHandlerImpl
from tadas.workers.maintenance.health import Probe, WorkerHttpServer
from tadas.workers.maintenance.loop import LoopOptions, WorkerLoop
from tadas.workers.maintenance.settings import MaintenanceSettings

log = logging.getLogger(__name__)


def loop_options(settings: MaintenanceSettings, lane: str | None = None) -> LoopOptions:
    return LoopOptions(
        worker_id=settings.worker_id,
        lane=lane or settings.worker_lane,
        capacity=settings.worker_capacity,
        lease=timedelta(seconds=settings.worker_lease_seconds),
        heartbeat_interval=timedelta(seconds=settings.worker_heartbeat_seconds),
        heartbeat_failure_limit=settings.worker_heartbeat_failure_limit,
        sweep_interval=timedelta(seconds=settings.worker_sweep_seconds),
        poll_interval=timedelta(seconds=settings.worker_poll_seconds),
    )


def build_loop(container: WorkerContainer, lane: str | None = None) -> WorkerLoop:
    return WorkerLoop(
        work=container.managers.work,
        outbox=container.managers.outbox,
        purges={
            "tasks": container.managers.tasks.purge_deleted,
            "tenancy": container.managers.tenancy.purge_deleted,
            "idempotency": container.managers.idempotency.purge,
            "work": container.managers.work.purge_settled,
            "events": container.managers.events.purge_expired,
        },
        handlers={WorkKind.NOOP: NoopHandlerImpl()},
        topics=container.infra.get_topics(),
        liveness=container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=loop_options(container.settings, lane),
    )


async def serve(lane: str | None) -> int:
    settings = MaintenanceSettings()
    configure_logging(settings.log_level, settings.log_json)
    # Second, before anything logs: every line this process writes carries the
    # service and the environment, whether or not reporting is configured.
    name_process(settings.service_name, settings.environment)
    install_trust_store()
    configure_error_reporting(
        settings.sentry_dsn, settings.environment, settings.service_name, settings.version
    )
    configure_tracing(
        settings.otel_endpoint,
        settings.service_name,
        timedelta(seconds=settings.otel_timeout_seconds),
    )
    container = WorkerContainer.build(settings)
    await container.start()
    loop = build_loop(container, lane)
    running = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        running.add_signal_handler(sig, loop.stop)
    # /metrics for Prometheus locally and the collector sidecar in the cloud,
    # /healthz for the container probe: the liveness key the loop heartbeats
    # into, read through the running process's own cache.
    http = WorkerHttpServer(
        settings.metrics_host,
        settings.metrics_port,
        liveness_probe(container, settings.worker_id),
        running,
    )
    http.start()
    try:
        await loop.run()
    finally:
        http.stop()
        await container.close()
    log.info("%s stopped", settings.worker_id)
    return 0


def liveness_probe(container: WorkerContainer, worker_id: str) -> Probe:
    cache = container.infra.get_cache(CacheScope.WORKER_LIVENESS)

    async def alive() -> bool:
        return await cache.get(EMPTY_UUID, f"worker:{worker_id}") is not None

    return alive


def health(settings: MaintenanceSettings) -> int:
    """The probe by hand: asks the serving process's `/healthz` on the metrics
    port and exits 0 on 200, 1 otherwise. The container healthcheck makes the
    same request without importing this package."""
    host = "127.0.0.1" if settings.metrics_host == "0.0.0.0" else settings.metrics_host
    url = f"http://{host}:{settings.metrics_port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return 0 if response.status == 200 else 1
    except urllib.error.HTTPError as error:
        print(f"{url} answered {error.code}", file=sys.stderr)
    except OSError as error:
        print(f"{url} is unreachable: {error}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tadas-maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    p_serve = sub.add_parser("serve", help="run the worker loop")
    p_serve.add_argument("--lane", help="the lane to claim from; defaults to TADAS_WORKER_LANE")
    sub.add_parser("health", help="exit 0 while the serving worker answers /healthz with 200")
    args = parser.parse_args(argv)
    if args.command == "health":
        return health(MaintenanceSettings())
    return asyncio.run(serve(args.lane))


if __name__ == "__main__":
    sys.exit(main())
