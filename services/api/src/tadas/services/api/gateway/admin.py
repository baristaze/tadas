"""The operator gate: resolves the bearer to an identity, admits it only when
the identity is an operator and the credential is the person's own sign-in,
and produces an AdminContext. No OpContext exists on this path."""

from typing import Annotated

from fastapi import Depends, Header, Request

from tadas.om.opcontext import AdminContext
from tadas.services.api.gateway.auth import bearer_of
from tadas.services.api.gateway.observability import request_id_of


async def current_admin(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AdminContext:
    tenancy = request.app.state.container.managers.tenancy
    return await tenancy.authenticate_operator(
        bearer_of(authorization), request_id_of(request.scope)
    )


AdminCtx = Annotated[AdminContext, Depends(current_admin)]
