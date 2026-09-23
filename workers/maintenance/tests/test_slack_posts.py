"""The Slack post: through a queue, behind the twin. A post is recorded under
its item's key and never posted twice; a rate limit parks it for the time
Slack named; a channel no retry fixes marks the connection broken and stops
the posting; any other refusal fails the item, which retries."""

from datetime import timedelta
from pathlib import Path

import pytest
from slack_support import build, claim, connect, make_task, owner_of, queued

from tadas.integrations.slack import SlackChannelUnusable, SlackFailed, SlackRateLimited
from tadas.integrations.slack.twin import SlackTwinImpl
from tadas.om.slack.types.connection import SlackConnectionStatus
from tadas.om.tasks.types.task import TaskStatus
from tadas.om.work.types.handler import WorkParked
from tadas.om.work.types.work_item import SlackPostEvent, WorkKind
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.slack_posts import SlackPostHandlerImpl, message_for


def handler(container: WorkerContainer, twin: SlackTwinImpl) -> SlackPostHandlerImpl:
    return SlackPostHandlerImpl(container.managers.tasks, container.managers.slack, twin)


async def test_created_and_completed_are_posted_to_the_connected_channel(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann, channel="C0TEAM")
    tasks = container.managers.tasks
    task = await tasks.create_task(ann, make_task(ann, "Ship <!channel> & friends"))
    await tasks.update_task(ann, task.model_copy(update={"status": TaskStatus.DONE}), 1)
    posting = handler(container, twin)
    while (claimed := await claim(container, WorkKind.SLACK_POST)) is not None:
        await posting.handle(*claimed)
        await container.managers.work.complete(*claimed)
    lines = [post.text for post in twin.posts if post.channel_id == "C0TEAM"]
    assert lines[1:] == [
        ":memo: New task: *Ship &lt;!channel&gt; &amp; friends*",
        ":white_check_mark: Done: *Ship &lt;!channel&gt; &amp; friends*",
    ], "the first line is the one the link posted"


async def test_an_org_with_no_channel_queues_no_post(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    await container.managers.tasks.create_task(ann, make_task(ann))
    assert await queued(container, ann, WorkKind.SLACK_POST) == []


async def test_a_retried_post_never_posts_twice(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    await container.managers.tasks.create_task(ann, make_task(ann))
    claimed = await claim(container, WorkKind.SLACK_POST)
    assert claimed is not None
    posting = handler(container, twin)
    before = len(twin.posts)
    await posting.handle(*claimed)
    await posting.handle(*claimed)  # the item runs again: a crash before it completed
    assert len(twin.posts) == before + 1
    ctx, item = claimed
    recorded = await container.managers.slack.read_post(ctx, item.idempotency_key)
    assert recorded is not None and recorded.ts == twin.posts[-1].ts


async def test_a_rate_limit_parks_the_post_for_the_time_slack_named(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    await container.managers.tasks.create_task(ann, make_task(ann))
    claimed = await claim(container, WorkKind.SLACK_POST)
    assert claimed is not None
    twin.fail_next(SlackRateLimited(timedelta(seconds=7)))
    with pytest.raises(WorkParked) as parked:
        await handler(container, twin).handle(*claimed)
    assert parked.value.resume_after == timedelta(seconds=7)
    ctx, item = claimed
    assert await container.managers.slack.read_post(ctx, item.idempotency_key) is None


@pytest.mark.parametrize("code", ["channel_not_found", "not_in_channel", "is_archived"])
async def test_a_channel_no_retry_fixes_breaks_the_connection(tmp_path: Path, code: str) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    await container.managers.tasks.create_task(ann, make_task(ann))
    claimed = await claim(container, WorkKind.SLACK_POST)
    assert claimed is not None
    twin.fail_next(SlackChannelUnusable(code))
    await handler(container, twin).handle(*claimed)  # completes: nothing to retry
    connection = await container.managers.slack.get_connection(ann)
    assert connection is not None
    assert connection.status is SlackConnectionStatus.BROKEN and connection.broken_reason == code
    before = len(await queued(container, ann, WorkKind.SLACK_POST))
    await container.managers.tasks.create_task(ann, make_task(ann, "after it broke"))
    assert len(await queued(container, ann, WorkKind.SLACK_POST)) == before, "posting stopped"


async def test_any_other_refusal_fails_the_item_for_a_retry(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    await container.managers.tasks.create_task(ann, make_task(ann))
    claimed = await claim(container, WorkKind.SLACK_POST)
    assert claimed is not None
    twin.fail_next(SlackFailed("internal_error"))
    with pytest.raises(SlackFailed):
        await handler(container, twin).handle(*claimed)


async def test_a_post_for_a_task_deleted_since_posts_nothing(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    task = await container.managers.tasks.create_task(ann, make_task(ann))
    await container.managers.tasks.delete_task(ann, task.id, 1)
    claimed = await claim(container, WorkKind.SLACK_POST)
    assert claimed is not None
    before = len(twin.posts)
    await handler(container, twin).handle(*claimed)
    assert len(twin.posts) == before


async def test_the_message_names_the_event_and_the_title(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    titled = make_task(ann, "Pay rent")
    assert message_for(SlackPostEvent.REMINDED, titled) == ":alarm_clock: Reminder: *Pay rent*"
