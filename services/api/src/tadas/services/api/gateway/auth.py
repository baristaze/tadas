"""The gateway mints the request stage once per request and asks the tenancy
manager for every stronger stage; nothing else builds a context. The
credential's prefix decides which transition accepts it, and a socket opens
on a single-use ticket rather than a credential in its URL."""

import logging
from typing import Annotated

from fastapi import Depends, Header, Query, Request, WebSocket, WebSocketException
from starlette.requests import HTTPConnection

from tadas.infra.observability import current_trace_id
from tadas.om.exceptions import NotAuthenticated, PlatformException, ValidationFailed
from tadas.om.opcontext import AppContext, AppType, IdentityContext, OpContext, RequestContext
from tadas.services.api.gateway.observability import request_id_of
from tadas.services.api.gateway.resolve import container_of

log = logging.getLogger(__name__)

APP_HEADER = "x-app"
APP_VERSION_HEADER = "x-app-version"
CLOSE_UNAUTHENTICATED = 4401


def bearer_of(authorization: str | None) -> str:
    if not authorization:
        raise NotAuthenticated("missing bearer credential")
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise NotAuthenticated("expected a bearer credential")
    return credential.strip()


def app_context_of(x_app: str | None, x_app_version: str | None) -> AppContext:
    """The app header names the calling app; a machine caller without one is `api`."""
    if x_app is None:
        app_type = AppType.API
    else:
        try:
            app_type = AppType(x_app)
        except ValueError:
            raise ValidationFailed(f"unknown app {x_app!r} in {APP_HEADER}") from None
    return AppContext(type=app_type, version=x_app_version or f"{app_type.value}@unknown")


def request_context(
    connection: HTTPConnection,
    x_app: Annotated[str | None, Header()] = None,
    x_app_version: Annotated[str | None, Header()] = None,
) -> RequestContext:
    """The weakest stage, minted once at the edge: the request id the
    middleware stamped on the scope, the calling app from its headers, and the
    trace id of the current span. A websocket scope reaches it the same way."""
    return RequestContext(
        request_id=request_id_of(connection.scope),
        app=app_context_of(x_app, x_app_version),
        trace_id=current_trace_id(),
    )


Rctx = Annotated[RequestContext, Depends(request_context)]


async def current_context(
    request: Request,
    rctx: Rctx,
    authorization: Annotated[str | None, Header()] = None,
) -> OpContext:
    """The tenant stage: a session token or an api key, resolved to a membership."""
    tenancy = container_of(request).managers.tenancy
    return await tenancy.authenticate(rctx, bearer_of(authorization))


Ctx = Annotated[OpContext, Depends(current_context)]


async def current_identity(
    request: Request,
    rctx: Rctx,
    authorization: Annotated[str | None, Header()] = None,
) -> IdentityContext:
    """The identity stage: the tenant-less sign-in credential, accepted only
    where a tenant is chosen or an operator is admitted."""
    tenancy = container_of(request).managers.tenancy
    return await tenancy.authenticate_login(rctx, bearer_of(authorization))


Identity = Annotated[IdentityContext, Depends(current_identity)]


async def socket_context(
    websocket: WebSocket, rctx: Rctx, ticket: Annotated[str, Query()]
) -> OpContext:
    """The socket's principal: the tenancy manager consumes the ticket once and
    re-checks the credential behind it. A refused ticket closes the socket
    with 4401 before the handler runs."""
    tenancy = container_of(websocket).managers.tenancy
    try:
        return await tenancy.redeem_ticket(rctx, ticket)
    except PlatformException as error:
        log.info("socket refused: %s", error.message)
        raise WebSocketException(code=CLOSE_UNAUTHENTICATED, reason=error.code) from None


SocketCtx = Annotated[OpContext, Depends(socket_context)]
