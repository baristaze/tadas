"""Slack routes: the org's connected channel, a one-time code to connect one,
and the disconnect. Each function is one call into the slack service."""

from fastapi import APIRouter, Response

from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.resolve import SlackService
from tadas.services.api.types.slack import IssuedSlackLinkCodeView, SlackStatusView

router = APIRouter(prefix="/slack", tags=["slack"])


@router.get("/connection", response_model=SlackStatusView)
async def get_connection(ctx: Ctx, slack: SlackService) -> SlackStatusView:
    return await slack.get_status(ctx)


# The code is shown once, in the first response: a replay under the same
# Idempotency-Key answers with `code` null, and the caller asks for another.
@router.post("/link-codes", response_model=IssuedSlackLinkCodeView, status_code=201)
async def issue_link_code(ctx: Ctx, slack: SlackService, idem: Idem) -> Response:
    return await idem.run(201, lambda _: slack.issue_link_code(ctx))


@router.delete("/connection", response_model=SlackStatusView)
async def disconnect(ctx: Ctx, slack: SlackService) -> SlackStatusView:
    return await slack.disconnect(ctx)
