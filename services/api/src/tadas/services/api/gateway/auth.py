"""The gateway verifies credentials and builds OpContext; nothing else does.
The credential's prefix decides which dependency accepts it, and a socket
opens on a single-use ticket rather than a credential in its URL."""

import logging
from typing import Annotated

from fastapi import Depends, Header, Query, Request, WebSocket, WebSocketException

from tadas.infra.observability import current_trace_id
from tadas.om.exceptions import (
    InvalidCredential,
    NotAuthenticated,
    PlatformException,
    ValidationFailed,
)
from tadas.om.opcontext import AppContext, AppType, CredentialKind, OpContext
from tadas.om.tenancy.rules import credential_kind_of
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


async def current_context(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_app: Annotated[str | None, Header()] = None,
    x_app_version: Annotated[str | None, Header()] = None,
) -> OpContext:
    tenancy = container_of(request).managers.tenancy
    return await tenancy.authenticate(
        bearer_of(authorization),
        app_context_of(x_app, x_app_version),
        request_id_of(request.scope),
        current_trace_id(),
    )


Ctx = Annotated[OpContext, Depends(current_context)]


async def login_credential(authorization: Annotated[str | None, Header()] = None) -> str:
    """The tenant-less sign-in credential, accepted only where a tenant is chosen."""
    credential = bearer_of(authorization)
    if credential_kind_of(credential) is not CredentialKind.LOGIN:
        raise InvalidCredential("this route accepts a login credential")
    return credential


LoginCredential = Annotated[str, Depends(login_credential)]


async def socket_context(
    websocket: WebSocket,
    ticket: Annotated[str, Query()],
    x_app: Annotated[str | None, Header()] = None,
    x_app_version: Annotated[str | None, Header()] = None,
) -> OpContext:
    """The socket's principal: the tenancy manager consumes the ticket once and
    re-checks the credential behind it. A refused ticket closes the socket
    with 4401 before the handler runs."""
    tenancy = container_of(websocket).managers.tenancy
    try:
        return await tenancy.redeem_ticket(
            ticket, app_context_of(x_app, x_app_version), request_id_of(websocket.scope)
        )
    except PlatformException as error:
        log.info("socket refused: %s", error.message)
        raise WebSocketException(code=CLOSE_UNAUTHENTICATED, reason=error.code) from None


SocketCtx = Annotated[OpContext, Depends(socket_context)]
