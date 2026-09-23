"""What Slack sends, after the acknowledgement: the command parser, the link
code (hashed, single use, expiring), `/tadas add` in a connected channel and
nowhere else, `/tadas list` and `/tadas` alone, the help, the mention, the App
Home, the tenant fence of the connection, and the queue consumer's delete-or-retry."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from slack_support import (
    PORTAL,
    TEAM,
    build,
    command,
    connect,
    delivery,
    inbound,
    make_task,
    member_of,
    owner_of,
)

from tadas.infra.queues import Queues
from tadas.infra.queues.memory import QueueMemoryImpl
from tadas.integrations.slack import SlackFailed
from tadas.integrations.slack.twin import SlackTwinImpl
from tadas.om.base import derived_id
from tadas.om.exceptions import NotAuthorized
from tadas.om.opcontext import OpContext
from tadas.om.slack.impl.manager import SlackManagerImpl, SlackOptions
from tadas.om.slack.rules import code_digest, normalized_code
from tadas.om.tasks.types.filter import TaskFilter
from tadas.om.tasks.types.task import Task, TaskScope, TaskStatus
from tadas.workers.maintenance.container import WorkerContainer
from tadas.workers.maintenance.slack_inbound import (
    CONNECTED,
    NOT_CONNECTED,
    USAGE,
    Command,
    InboundOptions,
    SlackInboundConsumer,
    SlackInboundHandler,
    Verb,
    home_view,
    parse_command,
)


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("", Command(Verb.LIST)),
        ("   ", Command(Verb.LIST)),
        ("list", Command(Verb.LIST)),
        ("  LIST ", Command(Verb.LIST)),
        ("List", Command(Verb.LIST)),
        ("help", Command(Verb.HELP)),
        ("  HELP  ", Command(Verb.HELP)),
        ("add Buy milk", Command(Verb.ADD, "Buy milk")),
        ("Add   Buy   milk ", Command(Verb.ADD, "Buy   milk")),
        ("link abcd-efgh", Command(Verb.LINK, "abcd-efgh")),
        ("add", Command(Verb.UNKNOWN, "add")),
        ("link", Command(Verb.UNKNOWN, "link")),
        ("delete 3", Command(Verb.UNKNOWN, "delete 3")),
        ("edit Buy milk", Command(Verb.UNKNOWN, "edit Buy milk")),
    ],
)
def test_the_command_parser(text: str, parsed: Command) -> None:
    assert parse_command(text) == parsed


def test_a_code_is_typed_loosely_and_stored_as_a_digest() -> None:
    assert normalized_code(" abcd-efgh ") == "ABCDEFGH"
    assert code_digest("abcd efgh") == code_digest("ABCD-EFGH")
    assert "ABCD" not in code_digest("ABCD-EFGH")


async def test_help_and_an_unknown_command_answer_with_the_usage(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    handler = inbound(container, twin)
    await handler.handle(command("help"))
    await handler.handle(command("rename 3 to 4"))
    assert [text for _, text in twin.responses] == [USAGE, USAGE]


async def test_add_in_a_channel_no_org_holds_says_how_to_connect(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    await inbound(container, twin).handle(command("add Buy milk"))
    assert [text for _, text in twin.responses] == [NOT_CONNECTED]


async def test_a_code_links_the_channel_once(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    issued = await container.managers.slack.issue_link_code(ann)
    handler = inbound(container, twin)
    await handler.handle(command(f"link {issued.code.lower()}", "C0TEAM", "U0ANN"))
    connection = await container.managers.slack.get_connection(ann)
    assert connection is not None
    assert (connection.team_id, connection.channel_id) == (TEAM, "C0TEAM")
    assert connection.created_by == ann.user_id and connection.linked_by_slack_user == "U0ANN"
    assert twin.posts[-1].channel_id == "C0TEAM" and twin.posts[-1].text == CONNECTED
    assert twin.responses[-1][1] == "Connected. Try `/tadas add <title>`."
    await handler.handle(command(f"link {issued.code}", "C0OTHER"))
    assert twin.responses[-1][1].startswith("That code is unknown, used, or expired")
    again = await container.managers.slack.get_connection(ann)
    assert again is not None and again.channel_id == "C0TEAM"


async def test_an_expired_code_links_nothing(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    expired = SlackManagerImpl(
        container.storage.get_slack_storage(),
        container.managers.tenancy,
        container.managers.outbox,
        SlackOptions(code_lifetime=timedelta(seconds=-1)),
    )
    issued = await expired.issue_link_code(ann)
    await inbound(container, twin).handle(command(f"link {issued.code}"))
    assert await container.managers.slack.get_connection(ann) is None
    assert twin.responses[-1][1].startswith("That code is unknown, used, or expired")


async def test_the_code_is_kept_as_its_digest_alone(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    ann = await owner_of(container, "acme")
    issued = await container.managers.slack.issue_link_code(ann)
    stored = container.storage.get_slack_storage()._codes  # type: ignore[attr-defined]
    [(_, code)] = stored.values()
    assert code.code_hash == code_digest(issued.code)
    assert normalized_code(issued.code) not in code.model_dump_json()


async def test_only_an_owner_or_an_admin_issues_a_code(tmp_path: Path) -> None:
    container, _ = build(tmp_path)
    await owner_of(container, "acme")
    bob = await member_of(container, "acme", "bob@acme.test")
    with pytest.raises(NotAuthorized):
        await container.managers.slack.issue_link_code(bob)
    with pytest.raises(NotAuthorized):
        await container.managers.slack.disconnect(bob)


async def test_relinking_replaces_the_channel(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann, "C0FIRST")
    first = await container.managers.slack.get_connection(ann)
    await connect(container, twin, ann, "C0SECOND")
    second = await container.managers.slack.get_connection(ann)
    assert first is not None and second is not None
    assert second.id == first.id and second.channel_id == "C0SECOND"
    await inbound(container, twin).handle(command("add In the old channel", "C0FIRST"))
    assert twin.responses[-1][1] == NOT_CONNECTED


async def test_a_channel_speaks_for_one_org(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    zoe = await owner_of(container, "zenith")
    await connect(container, twin, ann, "C0SHARED")
    issued = await container.managers.slack.issue_link_code(zoe)
    await inbound(container, twin).handle(command(f"link {issued.code}", "C0SHARED"))
    assert twin.responses[-1][1].startswith("This channel is connected to another Tadas org")
    assert await container.managers.slack.get_connection(zoe) is None
    theirs = await container.managers.slack.get_connection(ann)
    assert theirs is not None and theirs.channel_id == "C0SHARED"


async def test_add_creates_the_task_in_the_channels_org_alone(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    zoe = await owner_of(container, "zenith")
    await connect(container, twin, ann, "C0ACME")
    await connect(container, twin, zoe, "C0ZENITH")
    typed = command("add Order more coffee", "C0ACME")
    handler = inbound(container, twin)
    await handler.handle(typed)
    await handler.handle(typed)  # the queue handed the same delivery back
    tasks = container.managers.tasks
    acme = await tasks.get_open_tasks(
        ann, TaskFilter(scope=TaskScope.TEAM, user_id=ann.user_id), None, 50
    )
    zenith = await tasks.get_open_tasks(
        zoe, TaskFilter(scope=TaskScope.TEAM, user_id=zoe.user_id), None, 50
    )
    assert [task.title for task in acme.items] == ["Order more coffee"], "one task, in acme"
    assert zenith.items == ()
    [task] = acme.items
    assert task.id == derived_id(typed.key, typed.received_at)
    assert task.created_by == ann.user_id, "the member who linked the channel"
    assert twin.responses[-1][1] == "Added: *Order more coffee*"


async def test_disconnecting_stops_the_channel(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    assert await container.managers.slack.disconnect(ann) is not None
    assert await container.managers.slack.get_connection(ann) is None
    await inbound(container, twin).handle(command("add After the disconnect"))
    assert twin.responses[-1][1] == NOT_CONNECTED


async def test_a_mention_is_answered_in_its_thread_and_the_home_is_published(
    tmp_path: Path,
) -> None:
    container, twin = build(tmp_path)
    handler = inbound(container, twin)
    mention = {"type": "app_mention", "channel": "C0ANY", "ts": "1700.01", "text": "<@B> hi"}
    await handler.handle(delivery({"event_id": "Ev1", "event": mention}, kind="events_api"))
    assert twin.posts[-1].thread_ts == "1700.01" and twin.posts[-1].text == USAGE
    opened = {"type": "app_home_opened", "user": "U0ANN", "tab": "home"}
    await handler.handle(delivery({"event_id": "Ev2", "event": opened}, kind="events_api"))
    [(user, view)] = twin.homes
    assert user == "U0ANN" and view["type"] == "home"


async def test_the_consumer_deletes_what_it_handled_and_leaves_what_failed(
    tmp_path: Path,
) -> None:
    container, twin = build(tmp_path)
    queues = QueueMemoryImpl()
    consumer = SlackInboundConsumer(
        queues, inbound(container, twin), InboundOptions(wait=timedelta(0))
    )
    await queues.send(Queues.SLACK, b"not json")
    await queues.send(Queues.SLACK, command("help").model_dump_json().encode())
    assert await consumer.poll_once() == 2
    assert (await queues.depth(Queues.SLACK)).visible + (
        await queues.depth(Queues.SLACK)
    ).in_flight == 0
    twin.fail_next(SlackFailed("timeout"))
    await queues.send(Queues.SLACK, command("help").model_dump_json().encode())
    assert await consumer.poll_once() == 1
    assert (await queues.depth(Queues.SLACK)).in_flight == 1, "left for the queue to hand back"


async def test_the_consumer_stops_when_asked(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    consumer = SlackInboundConsumer(
        QueueMemoryImpl(), inbound(container, twin), InboundOptions(wait=timedelta(0))
    )
    running = asyncio.create_task(consumer.run())
    await asyncio.sleep(0.01)
    consumer.stop()
    await asyncio.wait_for(running, 1)


async def add_tasks(container: WorkerContainer, ctx: OpContext, count: int) -> list[Task]:
    """`count` open tasks, created oldest first, so the last one created is
    the top of the list."""
    return [
        await container.managers.tasks.create_task(ctx, make_task(ctx, f"Task {n}"))
        for n in range(1, count + 1)
    ]


async def listed(handler: SlackInboundHandler, twin: SlackTwinImpl, text: str = "list") -> str:
    await handler.handle(command(text))
    return twin.responses[-1][1]


async def test_list_in_a_channel_no_org_holds_says_how_to_connect(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    handler = inbound(container, twin)
    assert await listed(handler, twin) == NOT_CONNECTED
    assert await listed(handler, twin, "") == NOT_CONNECTED


async def test_an_empty_list_says_so(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    answer = await listed(inbound(container, twin), twin)
    assert answer == (
        f"No open tasks. Add one with `/tadas add <title>`, or open <{PORTAL}/|Tadas>."
    )
    assert twin.responses[-1][0] == "https://hooks.slack.com/commands/T/1/abc", "for one person"


async def test_the_list_is_the_open_list_in_its_own_order(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    await add_tasks(container, ann, 3)
    handler = inbound(container, twin)
    answer = await listed(handler, twin)
    assert answer == "\n".join(
        [
            "*Open tasks*",
            "• Task 3",
            "• Task 2",
            "• Task 1",
            f"Open <{PORTAL}/|Tadas> to work on them.",
        ]
    )
    assert await listed(handler, twin, "  ") == answer, "`/tadas` alone is `/tadas list`"


async def test_a_long_list_shows_ten_and_counts_the_rest(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    await add_tasks(container, ann, 12)
    answer = await listed(inbound(container, twin), twin, " LIST ")
    lines = answer.split("\n")
    assert lines[1:11] == [f"• Task {n}" for n in range(12, 2, -1)]
    assert lines[-1] == f"…and 2 more in <{PORTAL}/|Tadas>"
    assert len(lines) == 12


async def test_the_list_leaves_out_done_and_deleted_tasks(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    done, gone, kept = await add_tasks(container, ann, 3)
    tasks = container.managers.tasks
    await tasks.update_task(ann, done.model_copy(update={"status": TaskStatus.DONE}), done.version)
    await tasks.delete_task(ann, gone.id, gone.version)
    answer = await listed(inbound(container, twin), twin)
    assert answer.split("\n")[1:-1] == [f"• {kept.title}"]


async def test_a_title_cannot_ping_or_fake_a_link_and_the_due_time_is_localized(
    tmp_path: Path,
) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    await connect(container, twin, ann)
    due = datetime(2030, 5, 17, 14, 30, tzinfo=UTC)
    await container.managers.tasks.create_task(
        ann, make_task(ann, "Ship <!channel> & <https://evil.test|this>", remind_at=due)
    )
    answer = await listed(inbound(container, twin), twin)
    stamp = int(due.timestamp())
    assert answer.split("\n")[1] == (
        "• Ship &lt;!channel&gt; &amp; &lt;https://evil.test|this&gt;"
        f"  _due <!date^{stamp}^{{date_short_pretty}} {{time}}|2030-05-17 14:30 UTC>_"
    )
    assert "<!channel>" not in answer


async def test_the_list_is_the_channels_org_alone(tmp_path: Path) -> None:
    container, twin = build(tmp_path)
    ann = await owner_of(container, "acme")
    zoe = await owner_of(container, "zenith")
    await connect(container, twin, ann, "C0ACME")
    await connect(container, twin, zoe, "C0ZENITH")
    await container.managers.tasks.create_task(ann, make_task(ann, "Acme's own"))
    for n in range(12):
        await container.managers.tasks.create_task(zoe, make_task(zoe, f"Zenith {n}"))
    handler = inbound(container, twin)
    await handler.handle(command("list", "C0ACME"))
    acme = twin.responses[-1][1]
    assert acme.split("\n")[1:] == ["• Acme's own", f"Open <{PORTAL}/|Tadas> to work on them."]
    await handler.handle(command("list", "C0ZENITH"))
    zenith = twin.responses[-1][1]
    assert "Acme" not in zenith and zenith.endswith(f"…and 2 more in <{PORTAL}/|Tadas>")


def test_the_usage_and_the_home_name_the_list() -> None:
    assert "`/tadas list`" in USAGE
    [section] = [b for b in home_view()["blocks"] if b.get("text", {}).get("text") == USAGE]
    assert section["type"] == "section"
