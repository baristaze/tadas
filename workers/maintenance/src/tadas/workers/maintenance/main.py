"""The worker binary: settings, container, stop handlers, and `serve`."""

import argparse
import asyncio
import logging
import signal
import sys
from datetime import timedelta

from tadas.infra.cache import CacheScope
from tadas.infra.observability import configure_logging, configure_tracing
from tadas.infra.trust import install_trust_store
from tadas.om.work.types.work_item import WorkKind
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.handler import NoopHandlerImpl
from tadas.workers.maintenance.loop import LoopOptions, WorkerLoop
from tadas.workers.maintenance.settings import MaintenanceSettings

log = logging.getLogger(__name__)


def loop_options(settings: MaintenanceSettings) -> LoopOptions:
    return LoopOptions(
        worker_id=settings.worker_id,
        queue=settings.worker_queue,
        capacity=settings.worker_capacity,
        lease=timedelta(seconds=settings.worker_lease_seconds),
        heartbeat_interval=timedelta(seconds=settings.worker_heartbeat_seconds),
        heartbeat_failure_limit=settings.worker_heartbeat_failure_limit,
        sweep_interval=timedelta(seconds=settings.worker_sweep_seconds),
        poll_interval=timedelta(seconds=settings.worker_poll_seconds),
    )


def build_loop(container: WorkerContainer) -> WorkerLoop:
    return WorkerLoop(
        work=container.managers.work,
        handlers={WorkKind.NOOP: NoopHandlerImpl()},
        topics=container.infra.get_topics(),
        liveness=container.infra.get_cache(CacheScope.WORKER_LIVENESS),
        options=loop_options(container.settings),
    )


async def serve() -> int:
    settings = MaintenanceSettings()
    configure_logging(settings.log_level, settings.log_json)
    install_trust_store()
    configure_tracing(settings.otel_endpoint, settings.service_name)
    container = WorkerContainer.build(settings)
    await container.start()
    loop = build_loop(container)
    running = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        running.add_signal_handler(sig, loop.stop)
    try:
        await loop.run()
    finally:
        await container.close()
    log.info("%s stopped", settings.worker_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tadas-maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the worker loop")
    parser.parse_args(argv)
    return asyncio.run(serve())


if __name__ == "__main__":
    sys.exit(main())
