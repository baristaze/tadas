"""create_app: boot (settings, logging, trust store, tracing), then the
container, middleware in a fixed order, routers under /v1, health routes,
and the lifespan that starts and closes the container."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import APIRouter, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tadas.infra.observability import metrics_exposition
from tadas.services.api.container import AppContainer, boot
from tadas.services.api.gateway.admission import AdmissionMiddleware
from tadas.services.api.gateway.errors import register_error_handlers
from tadas.services.api.gateway.observability import RequestIdMiddleware
from tadas.services.api.routers import all_routers
from tadas.services.api.settings import ApiSettings

API_PREFIX = "/v1"


def create_app(container: AppContainer | None = None) -> FastAPI:
    settings = container.settings if container is not None else ApiSettings()
    boot(settings)
    container = container or AppContainer.build(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await container.start()
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(title="Tadas API", version=settings.version, lifespan=lifespan)
    app.state.container = container

    # Middleware, innermost first. CORS is outermost, so every answer a
    # browser gets carries the headers that let it read the body: the request
    # id middleware writes the 500 envelope itself, and outside CORS that
    # envelope, its code, and its request id would be blocked by the browser
    # while a 401 from the same origin came through. A preflight is answered
    # before the request id is minted, which is right: it is not a request of
    # this API and it belongs in neither the access log nor the metrics.
    #
    # Admission goes inside both, and for the same two reasons. Inside CORS,
    # because its refusal is an answer a browser has to read, Retry-After
    # included, and outside CORS the browser would see a network error where
    # the process said "come back". Inside the request id, because a refusal
    # is an answer of this API like any other: it carries the id the caller
    # correlates on, it is counted, and it is in the access log, which is
    # where the operator reads that the process is refusing and how often. A
    # preflight is answered outside it and holds no slot, which is right for
    # the same reason it is not logged. What admission leaves outside itself
    # is only the little the two middlewares above it do, and it takes its
    # lane's bound before routing, the request body, and every dependency:
    # the lane is the method's, which the scope carries this far out.
    app.add_middleware(
        AdmissionMiddleware,
        limit_reads=settings.admission_limit_reads,
        limit_writes=settings.admission_limit_writes,
        retry_after=timedelta(seconds=settings.admission_retry_after_seconds),
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "Retry-After", "Idempotent-Replayed"],
    )
    register_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    for router in all_routers():
        api.include_router(router)
    app.include_router(api)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": settings.version}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        """The storage healthcheck under a deadline of its own, shorter than
        its prober's timeout (the deploy's check after a rollout waits ten
        seconds; the deadline is two): a probe that waits on the
        dependency it reports on stops answering exactly when the answer
        matters, and an orchestrator reads a probe that hangs as a timeout
        rather than as the negative answer it is. So the deadline answers
        here, 503 and `ready: false`; it never raises and never hangs. The
        deadline reaches the wait itself: `healthcheck` catches `Exception`
        and a cancellation is not one, so an exhausted pool is interrupted
        where it waits rather than kept until it gives up on its own."""
        try:
            async with asyncio.timeout(settings.readiness_timeout_seconds):
                ready = await container.storage.healthcheck()
        except TimeoutError:
            ready = False
        return JSONResponse(status_code=200 if ready else 503, content={"ready": ready})

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        body, content_type = metrics_exposition()
        return Response(content=body, media_type=content_type)

    return app
