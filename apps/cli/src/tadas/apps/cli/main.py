"""The commands. Command mode does one thing and returns (`add`, `ls`, `edit`,
`done`, `reopen`, `rm`, `mv`); `listen` stays and prints the team's changes
as they happen. Every command is a thin call into the client; the API
decides, the CLI shows. A verb that changes a task reads it first and sends
the version it read, so a change that raced another is refused (exit 1) and
never overwrites it. Exit codes: 0 done, 1 the API refused, 2 usage, 3 not
signed in, 4 the API is unreachable."""

import asyncio
import json
import sys
from collections.abc import Callable, Coroutine
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any, NoReturn
from uuid import UUID

import httpx
import typer

from tadas.apps.cli import config
from tadas.apps.cli.listen import listen as run_listener
from tadas.apps.cli.model import resolve, short_id, task_table
from tadas.client.client import UNSET, ApiClient, ApiError, Unset
from tadas.client.realtime import ChannelRefused
from tadas.client.types import TaskScope, TaskStatus, TaskView, UserView

EXIT_REFUSED = 1
EXIT_NOT_SIGNED_IN = 3
EXIT_UNREACHABLE = 4


def app_version() -> str:
    try:
        return f"cli@{version('tadas-cli')}"
    except PackageNotFoundError:
        return "cli@dev"


def build_client(api_url: str, token: str | None) -> ApiClient:
    """The one place a client is built; tests replace it with one over a test transport."""
    return ApiClient(
        api_url,
        app="cli",
        app_version=app_version(),
        token=token,
        timeout=config.timeout_seconds(),
    )


app = typer.Typer(
    help="Tadas from the terminal: one command at a time, or `listen` for what the team does.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,  # an unexpected error is a plain traceback, not a panel
)

Api = Annotated[str | None, typer.Option("--api", help="The API, else TADAS_API_URL, else local.")]
Json = Annotated[bool, typer.Option("--json", help="Print the API's view as JSON.")]
Ref = Annotated[str, typer.Argument(help="A task id, or the short id `ls` shows (its tail).")]


def run[T](work: Callable[[ApiClient], Coroutine[Any, Any, T]], api: str | None = None) -> T:
    """Runs one command's coroutine under a signed-in client and turns what
    goes wrong into a line on stderr and an exit code."""
    bearer = config.token()
    if bearer is None:
        _fail("not signed in; run `tadas login`", EXIT_NOT_SIGNED_IN)

    async def go() -> T:
        async with build_client(config.api_url(api), bearer) as client:
            return await work(client)

    return _run(go(), signed_in=True)


def _run[T](coroutine: Coroutine[Any, Any, T], *, signed_in: bool = False) -> T:
    """`signed_in` says a 401 means the kept credential is dead, not that a
    password was wrong."""
    try:
        return asyncio.run(coroutine)
    except ApiError as error:
        if error.status == 401 and signed_in:
            _fail(
                f"the credential was refused ({error.code}); run `tadas login`", EXIT_NOT_SIGNED_IN
            )
        _fail(f"refused: {error}", EXIT_REFUSED)
    except ChannelRefused as error:
        _fail(f"the channel was refused ({error}); run `tadas login`", EXIT_NOT_SIGNED_IN)
    except httpx.TransportError as error:
        # Any failure of the wire: refused, timed out, reset, or a proxy
        # that answered nothing. The API did not decide, so it is exit 4.
        _fail(f"cannot reach the API: {error}", EXIT_UNREACHABLE)
    except LookupError as error:
        _fail(str(error), EXIT_REFUSED)


def _fail(message: str, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def _show(task: TaskView, verb: str, as_json: bool) -> None:
    if as_json:
        typer.echo(task.model_dump_json(indent=2))
    else:
        typer.echo(f"{verb} {short_id(task.id)}  {task.title}")


async def _visible(client: ApiClient) -> list[TaskView]:
    """Open and done team tasks, the pool a short id is resolved over."""
    open_page = await client.tasks(TaskStatus.open, TaskScope.team, limit=200)
    done_page = await client.tasks(TaskStatus.done, TaskScope.team, limit=200)
    return [*open_page.items, *done_page.items]


async def _task(client: ApiClient, reference: str) -> TaskView:
    try:
        return await client.task(UUID(reference))
    except ValueError:
        return resolve(reference, await _visible(client))


async def _user(client: ApiClient, reference: str) -> UserView:
    """`me`, an email, or a display name, over the org's members."""
    if reference == "me":
        return (await client.me()).user
    users = await client.users()
    wanted = reference.lower()
    matches = [u for u in users if wanted in (u.email.lower(), u.display_name.lower())]
    if len(matches) != 1:
        raise LookupError(f"{reference!r} names {'no' if not matches else 'more than one'} member")
    return matches[0]


# Signing in


@app.command()
def login(
    email: Annotated[str, typer.Option(prompt=True)],
    password: Annotated[str, typer.Option(prompt=True, hide_input=True)],
    org: Annotated[
        str | None, typer.Option(help="The org's slug, when you belong to several.")
    ] = None,
    api: Api = None,
) -> None:
    """Sign in with email and password and keep the session for the next commands."""
    api_url = config.api_url(api)

    async def go() -> None:
        async with build_client(api_url, None) as client:
            issued = await client.login(email, password)
            choices = issued.memberships
            if org is not None:
                choices = [m for m in choices if m.org.slug == org]
            if len(choices) != 1:
                slugs = ", ".join(m.org.slug for m in issued.memberships) or "none"
                _fail(f"choose an org with --org: {slugs}", EXIT_REFUSED)
            chosen = choices[0]
            session = await client.exchange_session(issued.token, chosen.org.id)
            path = config.save_session(
                config.Session(
                    api_url=api_url,
                    token=session.token,
                    email=session.user.email,
                    display_name=session.user.display_name,
                    org_slug=session.org.slug,
                    org_name=session.org.name,
                )
            )
            typer.echo(
                f"signed in as {session.user.display_name} at {session.org.name}"
                f" ({session.role.value}); session kept in {path}"
            )

    _run(go())


@app.command()
def logout(api: Api = None) -> None:
    """Revoke the session and forget it."""
    if config.token() is not None:
        run(lambda client: client.logout(), api)
    typer.echo("signed out" if config.clear_session() else "no session to forget")


@app.command()
def whoami(api: Api = None) -> None:
    """Who the session belongs to."""
    me = run(lambda client: client.me(), api)
    typer.echo(f"{me.user.display_name} <{me.user.email}> at {me.org.name} ({me.role.value})")


# One command at a time


@app.command()
def ls(
    done: Annotated[
        bool, typer.Option("--done", help="The done list instead of the open one.")
    ] = False,
    mine: Annotated[
        bool, typer.Option("--mine", help="Only tasks assigned to me, or unassigned and mine.")
    ] = False,
    as_json: Json = False,
    api: Api = None,
) -> None:
    """List tasks: open in their order, or done newest first."""

    async def go(client: ApiClient) -> None:
        status = TaskStatus.done if done else TaskStatus.open
        scope = TaskScope.mine if mine else TaskScope.team
        page = await client.tasks(status, scope, limit=200)
        if as_json:
            typer.echo(json.dumps([t.model_dump(mode="json") for t in page.items], indent=2))
            return
        names = {u.id: u.display_name for u in await client.users()}
        typer.echo(task_table(page.items, lambda uid: names.get(uid, "someone") if uid else "-"))

    run(go, api)


@app.command()
def add(
    title: Annotated[str, typer.Argument(help="What to do.")],
    notes: Annotated[str, typer.Option(help="Details, kept with the task.")] = "",
    assignee: Annotated[str | None, typer.Option(help="`me`, an email, or a name.")] = None,
    as_json: Json = False,
    api: Api = None,
) -> None:
    """Create a task at the top of the open list."""

    async def go(client: ApiClient) -> None:
        assignee_id = (await _user(client, assignee)).id if assignee else None
        _show(
            await client.create_task(title, notes=notes, assignee_id=assignee_id), "added", as_json
        )

    run(go, api)


@app.command()
def edit(
    ref: Ref,
    title: Annotated[str | None, typer.Option(help="A new title.")] = None,
    notes: Annotated[str | None, typer.Option(help="New notes.")] = None,
    assignee: Annotated[str | None, typer.Option(help="`me`, an email, or a name.")] = None,
    unassign: Annotated[bool, typer.Option("--unassign", help="Clear the assignee.")] = False,
    as_json: Json = False,
    api: Api = None,
) -> None:
    """Change a task's title, notes, or assignee."""
    if assignee and unassign:
        _fail("--assignee and --unassign exclude each other", 2)
    if title is None and notes is None and assignee is None and not unassign:
        _fail("nothing to change; give --title, --notes, --assignee, or --unassign", 2)

    async def go(client: ApiClient) -> None:
        task = await _task(client, ref)
        assignee_id: UUID | Unset | None = UNSET
        if unassign:
            assignee_id = None
        elif assignee:
            assignee_id = (await _user(client, assignee)).id
        updated = await client.update_task(
            task.id, version=task.version, title=title, notes=notes, assignee_id=assignee_id
        )
        _show(updated, "edited", as_json)

    run(go, api)


@app.command()
def done(ref: Ref, as_json: Json = False, api: Api = None) -> None:
    """Complete a task."""

    async def go(client: ApiClient) -> None:
        task = await _task(client, ref)
        done = await client.update_task(task.id, version=task.version, status=TaskStatus.done)
        _show(done, "done", as_json)

    run(go, api)


@app.command()
def reopen(ref: Ref, as_json: Json = False, api: Api = None) -> None:
    """Bring a done task back to the top of the open list."""

    async def go(client: ApiClient) -> None:
        task = await _task(client, ref)
        reopened = await client.update_task(task.id, version=task.version, status=TaskStatus.open)
        _show(reopened, "reopened", as_json)

    run(go, api)


@app.command()
def rm(ref: Ref, as_json: Json = False, api: Api = None) -> None:
    """Delete a task."""

    async def go(client: ApiClient) -> None:
        task = await _task(client, ref)
        _show(await client.delete_task(task.id, task.version), "deleted", as_json)

    run(go, api)


@app.command()
def mv(
    ref: Ref,
    after: Annotated[str | None, typer.Option(help="Place it right after this task.")] = None,
    top: Annotated[bool, typer.Option("--top", help="Place it at the top.")] = False,
    as_json: Json = False,
    api: Api = None,
) -> None:
    """Move an open task within the open list."""
    if (after is None) == (not top):
        _fail("give exactly one of --after and --top", 2)

    async def go(client: ApiClient) -> None:
        task = await _task(client, ref)
        anchor = None if top else (await _task(client, after or "")).id
        _show(await client.move_task(task.id, anchor, task.version), "moved", as_json)

    run(go, api)


# Realtime


@app.command()
def listen(
    mine: Annotated[
        bool, typer.Option("--mine", help="Only tasks assigned to me, or unassigned and mine.")
    ] = False,
    api: Api = None,
) -> None:
    """Stay connected and print every task change as it happens. Ctrl-C stops."""
    try:
        run(lambda client: run_listener(client, mine=mine), api)
    except KeyboardInterrupt:
        typer.echo("stopped", err=True)


def main() -> int:
    try:
        app(standalone_mode=True)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
