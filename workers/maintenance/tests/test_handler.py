from pathlib import Path

from worker_support import build_container, make_item, sign_in

from tadas.workers.maintenance.handler import NoopHandlerImpl


async def test_handler_is_idempotent_over_the_memory_container(tmp_path: Path) -> None:
    container = build_container(tmp_path)
    ctx = await sign_in(container)
    item = make_item(ctx)
    handler = NoopHandlerImpl()
    await handler.handle(ctx, item)
    await handler.handle(ctx, item)
    assert [handled.id for handled in handler.handled] == [item.id, item.id]
