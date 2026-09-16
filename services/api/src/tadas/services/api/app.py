"""create_app: settings, logging, trust store, tracing, then middleware in a
fixed order, routers under /v1, health routes, and the lifespan that starts
and closes the container."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tadas.infra.observability import configure_logging, configure_tracing, metrics_exposition
from tadas.infra.trust import install_trust_store
from tadas.services.api.container import AppContainer
from tadas.services.api.gateway.errors import register_error_handlers
from tadas.services.api.gateway.observability import RequestIdMiddleware
from tadas.services.api.routers import all_routers
from tadas.services.api.settings import ApiSettings

API_PREFIX = "/v1"


def create_app(container: AppContainer | None = None) -> FastAPI:
    container = container or AppContainer.build(ApiSettings())
    settings = container.settings
    configure_logging(settings.log_level, settings.log_json)
    install_trust_store()
    configure_tracing(settings.otel_endpoint, settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await container.start()
        try:
            yield
        finally:
            await container.close()

    app = FastAPI(title="Tadas API", version=settings.version, lifespan=lifespan)
    app.state.container = container

    # Middleware, innermost first: CORS answers preflights inside the request id.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "Retry-After", "Idempotent-Replayed"],
    )
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    for router in all_routers():
        api.include_router(router)
    app.include_router(api)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": settings.version}

    @app.get("/readyz", include_in_schema=False)
    async def readyz(request: Request) -> JSONResponse:
        ready = await container.storage.healthcheck()
        return JSONResponse(status_code=200 if ready else 503, content={"ready": ready})

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        body, content_type = metrics_exposition()
        return Response(content=body, media_type=content_type)

    return app
