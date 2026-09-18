"""The worker binary: settings, container, stop handlers, `serve`, and the
`health` probe the container healthcheck runs."""

import argparse
import asyncio
import logging
import signal
import sys
from datetime import timedelta

from prometheus_client import start_http_server

from tadas.infra.cache import CacheScope
from tadas.infra.impl.configured import InfraConfiguredImpl
from tadas.infra.observability import (
    configure_error_reporting,
    configure_logging,
    configure_tracing,
)
from tadas.infra.trust import install_trust_store
from tadas.om.base import EMPTY_UUID
from tadas.om.work.types.work_item import WorkKind
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.handler import NoopHandlerImpl
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
        },
        handlers={WorkKind.NOOP: NoopHandlerImpl()},
        topics=container.infra.get_topics(),
        liveness=container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=loop_options(container.settings, lane),
    )


async def serve(lane: str | None) -> int:
    settings = MaintenanceSettings()
    configure_logging(settings.log_level, settings.log_json)
    install_trust_store()
    configure_error_reporting(
        settings.sentry_dsn, settings.environment, settings.service_name, settings.version
    )
    configure_tracing(settings.otel_endpoint, settings.service_name)
    # The worker's /metrics, for Prometheus locally and the collector sidecar in the cloud.
    metrics_server, _ = start_http_server(settings.metrics_port, settings.metrics_host)
    container = WorkerContainer.build(settings)
    await container.start()
    loop = build_loop(container, lane)
    running = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        running.add_signal_handler(sig, loop.stop)
    try:
        await loop.run()
    finally:
        await container.close()
        metrics_server.shutdown()
    log.info("%s stopped", settings.worker_id)
    return 0


async def health(worker_id: str | None) -> int:
    """The container healthcheck: reads the serving worker's liveness key through
    the same cache the loop heartbeats into. Exit 0 while the key is present,
    1 when it is missing or the cache is unreachable. Nothing here touches
    storage or starts a listener."""
    settings = MaintenanceSettings()
    target = worker_id or settings.worker_id
    infra = InfraConfiguredImpl(settings)
    try:
        alive = await infra.get_cache(CacheScope.WORKER_LIVENESS).get(
            EMPTY_UUID, f"worker:{target}"
        )
    finally:
        await infra.close()
    if alive is None:
        print(f"worker {target} has no liveness key", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tadas-maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    p_serve = sub.add_parser("serve", help="run the worker loop")
    p_serve.add_argument("--lane", help="the lane to claim from; defaults to TADAS_WORKER_LANE")
    p_health = sub.add_parser("health", help="exit 0 while the serving worker is alive")
    p_health.add_argument(
        "--worker-id",
        help="the id the serving process heartbeats under; defaults to TADAS_WORKER_ID",
    )
    args = parser.parse_args(argv)
    if args.command == "health":
        return asyncio.run(health(args.worker_id))
    return asyncio.run(serve(args.lane))


if __name__ == "__main__":
    sys.exit(main())
