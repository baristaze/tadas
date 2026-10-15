"""Slack: the org's connection to its Slack workspace.

- **The installation.** The org's installation (its workspace, its
  channel, and whether it works), any member; the install, which answers
  Slack's page to send the browser to with a one-time state, and the
  uninstall, an owner or an admin (`/v1/slack/installation`: `GET`,
  `POST`, `DELETE`).
- **Slack's calls.** Outside `/v1`, since their shape is Slack's. No
  credential: a slash command and an event are each checked against the
  Slack app's signing secret over the body and its timestamp, within five
  minutes, acknowledged at once, and queued for the worker; one that fails
  the check is a 401 (`slack_signature_invalid`) and nothing is queued.
  With no Slack app configured, each answers 503 (`slack_unavailable`).
  The events route answers Slack's URL check. The install's return is
  where Slack sends the browser back; it is not signed, the one-time state
  is its check, and it redirects to the portal's Settings with the
  outcome (`routers/webhooks.py`, `/webhooks/slack/commands`,
  `/webhooks/slack/events`, `GET /webhooks/slack/oauth`).

Each function is one call into the slack service; the install runs under
the idempotency record."""

from fastapi import APIRouter, Response

from tadas.services.api.gateway.auth import Ctx
from tadas.services.api.gateway.idempotency import Idem
from tadas.services.api.gateway.resolve import SlackService
from tadas.services.api.types.slack import SlackInstallStartView, SlackStatusView

router = APIRouter(prefix="/slack", tags=["slack"])


@router.get("/installation", response_model=SlackStatusView)
async def get_installation(ctx: Ctx, slack: SlackService) -> SlackStatusView:
    return await slack.get_status(ctx)


# Slack's page for the org's workspace, with a one-time state in it, shown in
# the first response alone: a replay under the same Idempotency-Key answers
# with `url` null, and the caller asks for another.
@router.post("/installation", response_model=SlackInstallStartView, status_code=201)
async def start_install(ctx: Ctx, slack: SlackService, idem: Idem) -> Response:
    return await idem.run(201, lambda _: slack.start_install(ctx))


@router.delete("/installation", response_model=SlackStatusView)
async def uninstall(ctx: Ctx, slack: SlackService) -> SlackStatusView:
    return await slack.uninstall(ctx)
