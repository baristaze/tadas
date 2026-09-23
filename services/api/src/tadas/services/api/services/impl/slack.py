from tadas.om.opcontext import OpContext
from tadas.om.slack import SlackManagerInterface
from tadas.services.api.services.slack import SlackServiceInterface
from tadas.services.api.types.slack import (
    IssuedSlackLinkCodeView,
    SlackConnectionView,
    SlackStatusView,
)


class SlackServiceImpl(SlackServiceInterface):
    def __init__(self, slack: SlackManagerInterface) -> None:
        self._slack = slack

    async def get_status(self, ctx: OpContext) -> SlackStatusView:
        connection = await self._slack.get_connection(ctx)
        view = None if connection is None else SlackConnectionView.model_validate(connection)
        return SlackStatusView(connection=view)

    async def issue_link_code(self, ctx: OpContext) -> IssuedSlackLinkCodeView:
        issued = await self._slack.issue_link_code(ctx)
        return IssuedSlackLinkCodeView(code=issued.code, expires_at=issued.expires_at)

    async def disconnect(self, ctx: OpContext) -> SlackStatusView:
        await self._slack.disconnect(ctx)
        return SlackStatusView(connection=None)
