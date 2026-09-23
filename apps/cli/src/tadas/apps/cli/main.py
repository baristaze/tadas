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
import time
import webbrowser
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Any, NoReturn
from uuid import UUID

import httpx
import typer

from tadas.apps.cli import config
from tadas.apps.cli.listen import listen as run_listener
from tadas.apps.cli.model import (
    choose_org,
    org_lines,
    parse_due,
    resolve,
    short_id,
    task_table,
)
from tadas.client.client import UNSET, ApiClient, ApiError, Unset
from tadas.client.realtime import ChannelRefused
from tadas.client.types import (
    IssuedLoginView,
    IssuedSessionView,
    TaskScope,
    TaskStatus,
    TaskView,
    UserView,
)

EXIT_REFUSED = 1
EXIT_USAGE = 2
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
        retries=config.retries(),
        backoff_seconds=config.backoff_seconds(),
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


def setting[T](read: Callable[[], T]) -> T:
    """A setting is read through here wherever it is read outside `_run`, so
    a value the environment got wrong is a usage error there too."""
    try:
        return read()
    except config.BadSetting as error:
        _fail(str(error), EXIT_USAGE)


def run[T](work: Callable[[ApiClient], Coroutine[Any, Any, T]], api: str | None = None) -> T:
    """Runs one command's coroutine under a signed-in client and turns what
    goes wrong into a line on stderr and an exit code."""
    api_url, bearer = setting(lambda: config.credentials(api))
    if bearer is None:
        _fail("not signed in; run `tadas login`", EXIT_NOT_SIGNED_IN)

    async def go() -> T:
        async with build_client(api_url, bearer) as client:
            return await work(client)

    return _run(go(), signed_in=True)


def _run[T](coroutine: Coroutine[Any, Any, T], *, signed_in: bool = False) -> T:
    """`signed_in` says a 401 means the kept credential is dead, not that a
    sign-in was refused."""
    try:
        return asyncio.run(coroutine)
    except config.BadSetting as error:
        # The environment names something the CLI cannot use. Nothing was
        # asked of the API, and the caller fixes it where they set it.
        _fail(str(error), EXIT_USAGE)
    except ApiError as error:
        if error.status == 401 and signed_in:
            _fail(
                f"the credential was refused ({error.code}); run `tadas login`", EXIT_NOT_SIGNED_IN
            )
        if error.status == 412:
            # The task changed between the read this command made and its
            # write; nothing was written, and the command reads afresh.
            _fail("refused: the task changed while this ran; run it again", EXIT_REFUSED)
        if error.code == "plan_limit_reached":
            # A plan's bound: the org's owner or an admin lifts it, in the
            # portal, and the same command then goes through.
            _fail(
                f"refused: {error.message}; an owner or an admin can change the plan "
                "in the portal, under Settings, Billing",
                EXIT_REFUSED,
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


REMIND_HELP = "A due time to be reminded at: +30m, +2h, +1d, or 2026-10-01T09:00 (local time)."


def _due(text: str) -> datetime:
    """The due time a person typed, or a usage error that says the forms."""
    now = datetime.now().astimezone()
    try:
        return parse_due(text, now, now.tzinfo or UTC)
    except ValueError as error:
        _fail(str(error), EXIT_USAGE)


def _show(task: TaskView, verb: str, as_json: bool) -> None:
    if as_json:
        typer.echo(task.model_dump_json(indent=2))
    else:
        typer.echo(f"{verb} {short_id(task.id)}  {task.title}")


async def _all(client: ApiClient, status: TaskStatus, scope: TaskScope) -> list[TaskView]:
    """A whole list, page after page until the API says there is no next one."""
    tasks: list[TaskView] = []
    cursor: str | None = None
    while True:
        page = await client.tasks(status, scope, cursor=cursor, limit=200)
        tasks += page.items
        cursor = page.next_cursor
        if cursor is None:
            return tasks


async def _visible(client: ApiClient) -> list[TaskView]:
    """Open and done team tasks, the pool a short id is resolved over."""
    return [
        *await _all(client, TaskStatus.open, TaskScope.team),
        *await _all(client, TaskStatus.done, TaskScope.team),
    ]


async def _task(client: ApiClient, reference: str) -> TaskView:
    try:
        return await client.task(UUID(reference))
    except ValueError:
        return resolve(reference, await _visible(client))


async def _user(client: ApiClient, reference: str) -> UserView:
    """`me`, an email, or a display name, over the org's members."""
    if reference == "me":
        return (await client.me()).user
    users = await client.every_user()
    wanted = reference.lower()
    matches = [u for u in users if wanted in (u.email.lower(), u.display_name.lower())]
    if len(matches) != 1:
        raise LookupError(f"{reference!r} names {'no' if not matches else 'more than one'} member")
    return matches[0]


# Signing in


SLOW_DOWN_SECONDS = 5
"""How much longer the next ask waits when the API says to ask less often."""


def open_browser(url: str) -> None:
    """Opens the confirmation page in the person's browser, when there is one
    to open; a terminal with none, or over SSH, prints the address instead."""
    try:
        webbrowser.open(url)
    except webbrowser.Error:
        pass


async def pause(seconds: float) -> None:
    """The wait between two asks; tests replace it."""
    await asyncio.sleep(seconds)


def now() -> float:
    """The clock the device code's expiry is read on; tests replace it."""
    return time.monotonic()


async def device_sign_in(client: ApiClient, *, browser: bool) -> IssuedLoginView:
    """The device sign-in: the API starts it at the identity provider, the
    person confirms the code in any browser, and the CLI asks every interval
    until they do, or the code expires."""
    started = await client.start_device_sign_in()
    typer.echo(
        f"to sign in, open {started.verification_uri_complete}\n"
        f"and confirm the code {started.user_code}",
        err=True,
    )
    if browser:
        open_browser(started.verification_uri_complete)
    interval = float(started.interval)
    deadline = now() + started.expires_in
    while True:
        await pause(interval)
        try:
            return await client.finish_device_sign_in(started.device_code)
        except ApiError as error:
            if error.code == "sign_in_slow_down":
                interval += SLOW_DOWN_SECONDS
            elif error.code != "sign_in_pending":
                raise
        if now() >= deadline:
            _fail("the code expired before it was confirmed; run `tadas login` again", EXIT_REFUSED)


@app.command()
def login(
    org: Annotated[
        str | None, typer.Option(help="The org's slug, when you belong to several.")
    ] = None,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Print the address; open no browser.")
    ] = False,
    dev_email: Annotated[
        str | None,
        typer.Option(
            "--dev-email",
            help="Local stack only: sign in as this address with no browser. "
            "A deployed API has no such door and answers 404.",
        ),
    ] = None,
    api: Api = None,
) -> None:
    """Sign in through the browser with a one-time code and keep the session
    for the next commands."""
    api_url = config.api_url(api)

    async def go() -> None:
        async with build_client(api_url, None) as client:
            if dev_email is not None:
                issued = await client.dev_sign_in(dev_email)
            else:
                issued = await device_sign_in(client, browser=not no_browser)
            try:
                chosen = choose_org(issued.memberships, org)
            except LookupError as slugs:
                # The API signed the person in; what is missing is the flag.
                _fail(f"choose an org with --org: {slugs}", EXIT_USAGE)
            session = await client.exchange_session(issued.token, chosen.org.id)
            path = keep(api_url, session)
            typer.echo(
                f"signed in as {session.user.display_name} at {session.org.name}"
                f" ({session.role.value}); session kept in {path}"
            )

    _run(go())


def keep(api_url: str, session: IssuedSessionView) -> Path:
    """The one session the CLI holds, in the file the next command reads."""
    return config.save_session(
        config.Session(
            api_url=api_url,
            token=session.token,
            email=session.user.email,
            display_name=session.user.display_name,
            org_slug=session.org.slug,
            org_name=session.org.name,
        )
    )


@app.command()
def orgs(as_json: Json = False, api: Api = None) -> None:
    """The orgs you belong to; `*` marks the one the session is in."""

    async def go(client: ApiClient) -> None:
        memberships = await client.every_membership()
        if as_json:
            typer.echo(json.dumps([m.model_dump(mode="json") for m in memberships], indent=2))
            return
        current = (await client.me()).org.slug
        typer.echo(org_lines(memberships, current))

    run(go, api)


@app.command()
def switch(
    org: Annotated[str, typer.Argument(help="The slug of the org to switch to; see `tadas orgs`.")],
) -> None:
    """Move the kept session to another org. The API ends the old session in
    the same write, so the CLI never holds two. `TADAS_TOKEN` is the
    environment's credential, not the CLI's to end, so only the kept session
    switches."""
    session = config.load_session()
    if session is None:
        _fail("no kept session to switch; run `tadas login`", EXIT_NOT_SIGNED_IN)
    client = setting(lambda: build_client(session.api_url, session.token))

    async def go() -> None:
        async with client:
            try:
                chosen = choose_org(await client.every_membership(), org)
            except LookupError as slugs:
                _fail(f"no org {org!r} to switch to; yours are: {slugs}", EXIT_USAGE)
            switched = await client.switch_session(chosen.org.id)
            keep(session.api_url, switched)
            typer.echo(
                f"switched to {switched.org.name} as {switched.user.display_name}"
                f" ({switched.role.value}); the old session is ended"
            )

    _run(go(), signed_in=True)


@app.command()
def logout(api: Api = None) -> None:
    """Revoke the session `login` kept and forget it. `TADAS_TOKEN` is the
    environment's credential, not the CLI's to revoke, and is left alone."""
    session = config.load_session()
    if session is None:
        hint = "; TADAS_TOKEN is the environment's, unset it" if setting(config.token) else ""
        typer.echo(f"no session to forget{hint}")
        return

    # The token goes back to the API that issued it and nowhere else: an
    # `--api` naming another one is refused before the file is touched,
    # never handed the session's token.
    if api is not None and api.rstrip("/") != session.api_url.rstrip("/"):
        _fail(
            f"the session was issued by {session.api_url}, not {api}; "
            "run `tadas logout` without --api",
            EXIT_USAGE,
        )
    # Before the file is touched: a setting the environment got wrong means
    # the API is never asked, and a session nobody tried to revoke is not
    # forgotten over a typo.
    client = setting(lambda: build_client(session.api_url, session.token))

    async def revoke() -> str:
        async with client:
            try:
                await client.logout()
            except ApiError as error:
                # Revoked or expired already, or no longer a session token:
                # nothing is left to revoke.
                if error.status in (401, 422):
                    return f"signed out; the session was already gone ({error.code})"
                raise
        return "signed out"

    # The file goes whatever the API answered: a session the caller gave up
    # is not run as again, and the exit code says whether it was revoked.
    try:
        try:
            outcome = asyncio.run(revoke())
        finally:
            config.clear_session()
    except ApiError as error:
        _fail(f"session forgotten, not revoked; the API refused: {error}", EXIT_REFUSED)
    except httpx.TransportError as error:
        _fail(f"session forgotten, not revoked; cannot reach the API: {error}", EXIT_UNREACHABLE)
    except config.BadSetting as error:
        # The file is the one thing `logout` owns, so a file it cannot remove
        # is what the caller is told, whatever the API answered.
        _fail(str(error), EXIT_USAGE)
    typer.echo(outcome)


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
        tasks = await _all(client, status, scope)
        if as_json:
            typer.echo(json.dumps([t.model_dump(mode="json") for t in tasks], indent=2))
            return
        names = {u.id: u.display_name for u in await client.every_user()}
        typer.echo(task_table(tasks, lambda uid: names.get(uid, "someone") if uid else "-"))

    run(go, api)


@app.command()
def add(
    title: Annotated[str, typer.Argument(help="What to do.")],
    notes: Annotated[str, typer.Option(help="Details, kept with the task.")] = "",
    assignee: Annotated[str | None, typer.Option(help="`me`, an email, or a name.")] = None,
    remind: Annotated[str | None, typer.Option(help=REMIND_HELP)] = None,
    as_json: Json = False,
    api: Api = None,
) -> None:
    """Create a task at the top of the open list."""
    remind_at = _due(remind) if remind else None

    async def go(client: ApiClient) -> None:
        assignee_id = (await _user(client, assignee)).id if assignee else None
        created = await client.create_task(
            title, notes=notes, assignee_id=assignee_id, remind_at=remind_at
        )
        _show(created, "added", as_json)

    run(go, api)


@app.command()
def edit(
    ref: Ref,
    title: Annotated[str | None, typer.Option(help="A new title.")] = None,
    notes: Annotated[str | None, typer.Option(help="New notes.")] = None,
    assignee: Annotated[str | None, typer.Option(help="`me`, an email, or a name.")] = None,
    unassign: Annotated[bool, typer.Option("--unassign", help="Clear the assignee.")] = False,
    remind: Annotated[str | None, typer.Option(help=REMIND_HELP)] = None,
    no_remind: Annotated[bool, typer.Option("--no-remind", help="Clear the due time.")] = False,
    as_json: Json = False,
    api: Api = None,
) -> None:
    """Change a task's title, notes, assignee, or due time."""
    if assignee and unassign:
        _fail("--assignee and --unassign exclude each other", EXIT_USAGE)
    if remind and no_remind:
        _fail("--remind and --no-remind exclude each other", EXIT_USAGE)
    nothing = title is None and notes is None and assignee is None and remind is None
    if nothing and not (unassign or no_remind):
        _fail(
            "nothing to change; give --title, --notes, --assignee, --unassign, --remind,"
            " or --no-remind",
            EXIT_USAGE,
        )
    remind_at: datetime | Unset | None = UNSET
    if no_remind:
        remind_at = None
    elif remind:
        remind_at = _due(remind)

    async def go(client: ApiClient) -> None:
        task = await _task(client, ref)
        assignee_id: UUID | Unset | None = UNSET
        if unassign:
            assignee_id = None
        elif assignee:
            assignee_id = (await _user(client, assignee)).id
        updated = await client.update_task(
            task.id,
            version=task.version,
            title=title,
            notes=notes,
            assignee_id=assignee_id,
            remind_at=remind_at,
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
        _fail("give exactly one of --after and --top", EXIT_USAGE)

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
