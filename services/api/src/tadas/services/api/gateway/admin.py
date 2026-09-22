"""The operator gate: the identity stage the bearer reaches is admitted only
when the identity is an operator, and produces an OperatorContext. Two
credentials reach it: the person's own sign-in, which admits only with a
verified second factor, and an operator token, which carries one permission.
The tenancy manager's `admit_operator` decides; the gate adds one rule of
the edge: an operator with no second factor enrolled yet reaches the two
enrolment routes and is refused on every other one, by name. No OpContext
exists on this path."""

from typing import Annotated

from fastapi import Depends, Request

from tadas.om.exceptions import SecondFactorNotEnrolled
from tadas.om.opcontext import OperatorContext, OperatorPermission
from tadas.services.api.gateway.auth import Identity
from tadas.services.api.gateway.resolve import container_of


async def enrolling_admin(request: Request, identity: Identity) -> OperatorContext:
    """Any admitted operator, an unenrolled one included: for the two routes
    that enrol the second factor."""
    tenancy = container_of(request).managers.tenancy
    return await tenancy.admit_operator(identity)


EnrollingOperatorCtx = Annotated[OperatorContext, Depends(enrolling_admin)]


async def current_admin(admin: EnrollingOperatorCtx) -> OperatorContext:
    """An operator the plane admits to its work: one whose admission carries
    more than `ENROL`."""
    if admin.permissions <= {OperatorPermission.ENROL}:
        raise SecondFactorNotEnrolled(
            "enrol a second factor first: POST /v1/admin/me/totp, then /confirm"
        )
    return admin


OperatorCtx = Annotated[OperatorContext, Depends(current_admin)]
