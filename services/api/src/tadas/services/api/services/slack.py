"""The slack service: what the wire can do with the org's Slack channel."""

from abc import ABC, abstractmethod

from tadas.om.opcontext import OpContext
from tadas.services.api.types.slack import IssuedSlackLinkCodeView, SlackStatusView


class SlackServiceInterface(ABC):
    @abstractmethod
    async def get_status(self, ctx: OpContext) -> SlackStatusView: ...

    @abstractmethod
    async def issue_link_code(self, ctx: OpContext) -> IssuedSlackLinkCodeView: ...

    @abstractmethod
    async def disconnect(self, ctx: OpContext) -> SlackStatusView: ...
