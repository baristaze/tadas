from tadas.infra.flags import FlagsInterface
from tadas.om.context import TenantContext
from tadas.services.api.services.flags import FlagsServiceInterface
from tadas.services.api.types.flags import FlagsView


class FlagsServiceImpl(FlagsServiceInterface):
    def __init__(self, flags: FlagsInterface) -> None:
        self._flags = flags

    async def get_flags(self, ctx: TenantContext) -> FlagsView:
        evaluated = await self._flags.evaluate(ctx.org_id, ctx.user_id)
        return FlagsView(
            flags={flag.value: on for flag, on in sorted(evaluated.for_clients().items())}
        )
