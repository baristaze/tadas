"""The operator gate: the identity stage the bearer reaches (the person's own
sign-in, verified by `current_identity`) is admitted only when the identity
is an operator, and produces an OperatorContext. No OpContext exists on this
path."""

from typing import Annotated

from fastapi import Depends, Request

from tadas.om.opcontext import OperatorContext
from tadas.services.api.gateway.auth import Identity
from tadas.services.api.gateway.resolve import container_of


async def current_admin(request: Request, identity: Identity) -> OperatorContext:
    tenancy = container_of(request).managers.tenancy
    return await tenancy.admit_operator(identity)


OperatorCtx = Annotated[OperatorContext, Depends(current_admin)]
