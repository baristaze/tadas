"""Command mode against the whole API in-process: sign in, the task verbs,
short ids, assignees by name, JSON output, and the exit codes."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import typer
from api_support import OWNER, run, seed_request
from cli_support import BOB, Stack
from typer.testing import CliRunner

from tadas.apps.cli import config, main
from tadas.client.client import ApiClient, ApiError
from tadas.om.base import new_id, utcnow
from tadas.om.opcontext import Role
from tadas.om.tasks.types.task import Task


def test_login_keeps_a_session_and_whoami_reads_it(stack: Stack) -> None:
    signed = stack.tadas(
        "login", "--email", OWNER["email"], "--password", OWNER["password"], token=None
    )
    assert signed.exit_code == 0, signed.output
    # Ann belongs to Acme and to her personal org; with no --org she enters
    # the personal one, the place every person has.
    assert signed.output.startswith("signed in as Ann at Ann (owner); session kept in ")
    session = config.load_session()
    assert session is not None and session.org_slug.startswith("ann-")
    assert session.api_url == "http://test"
    assert (config.home() / "session.json").stat().st_mode & 0o777 == 0o600

    who = stack.tadas("whoami", token=None)  # the session file, no TADAS_TOKEN
    assert who.exit_code == 0 and who.output == "Ann <ann@example.test> at Ann (owner)\n"

    out = stack.tadas("logout", token=None)
    assert out.exit_code == 0 and out.output == "signed out\n"
    assert config.load_session() is None
    assert stack.tadas("logout", token=None).output == "no session to forget\n"


def test_login_naming_an_org_the_person_is_not_in_is_a_usage_error(stack: Stack) -> None:
    out = stack.tadas(
        "login",
        "--email",
        OWNER["email"],
        "--password",
        OWNER["password"],
        "--org",
        "nope",
        token=None,
    )
    assert out.exit_code == 2, out.output
    assert "choose an org with --org: acme" in out.output
    assert config.load_session() is None


def test_logout_forgets_a_session_the_api_already_revoked(stack: Stack) -> None:
    """A session revoked elsewhere, or expired, answers 401: there is nothing
    left to revoke, so the file goes and the command succeeds."""
    stack.tadas("login", "--email", OWNER["email"], "--password", OWNER["password"], token=None)
    session = config.load_session()
    assert session is not None

    async def revoke_elsewhere() -> None:
        async with stack.client(session.token) as client:
            await client.logout()

    asyncio.run(revoke_elsewhere())
    out = stack.tadas("logout", token=None)
    assert out.exit_code == 0, out.output
    assert out.output == "signed out; the session was already gone (not_authenticated)\n"
    assert config.load_session() is None


def test_logout_revokes_the_kept_session_and_leaves_the_environments_token_alone(
    stack: Stack,
) -> None:
    stack.tadas("login", "--email", OWNER["email"], "--password", OWNER["password"], token=None)
    session = config.load_session()
    assert session is not None
    bob = stack.session_token(BOB["email"], BOB["password"])

    out = stack.tadas("logout", token=bob)  # TADAS_TOKEN is Bob's; the file is Ann's
    assert out.exit_code == 0 and out.output == "signed out\n"
    assert config.load_session() is None
    assert stack.tadas("whoami", token=bob).exit_code == 0
    assert stack.tadas("whoami", token=session.token).exit_code == 3

    again = stack.tadas("logout", token=bob)
    assert again.exit_code == 0
    assert again.output == "no session to forget; TADAS_TOKEN is the environment's, unset it\n"
    assert stack.tadas("whoami", token=bob).exit_code == 0


def test_logout_never_sends_the_session_to_another_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The session's token goes back to the API that issued it: an `--api`
    naming another one is refused, nothing is sent, and the file stays."""
    monkeypatch.setenv("TADAS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TADAS_TOKEN", raising=False)
    config.save_session(
        config.Session(
            api_url="https://api.example.test",
            token="ses_kept",
            email="ann@example.test",
            display_name="Ann",
            org_slug="acme",
            org_name="Acme",
        )
    )
    sent: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        main,
        "build_client",
        lambda url, token: ApiClient(
            url,
            app="cli",
            app_version="cli@test",
            token=token,
            transport=httpx.MockTransport(record),
        ),
    )
    result = CliRunner().invoke(main.app, ["logout", "--api", "http://localhost:8000"])
    assert result.exit_code == main.EXIT_USAGE, result.output
    assert sent == []
    assert config.load_session() is not None


def test_logout_forgets_the_session_when_the_api_cannot_be_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The revoke did not happen, which the exit code says; the file goes
    anyway, so the next command is not run as a session the caller gave up."""
    monkeypatch.setenv("TADAS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TADAS_TOKEN", raising=False)
    config.save_session(
        config.Session(
            api_url="http://test",
            token="ses_kept",
            email="ann@example.test",
            display_name="Ann",
            org_slug="acme",
            org_name="Acme",
        )
    )

    def raise_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(
        main,
        "build_client",
        lambda _url, token: ApiClient(
            "http://test",
            app="cli",
            app_version="cli@test",
            token=token,
            transport=httpx.MockTransport(raise_failure),
            backoff_seconds=0.0,  # the retry still runs; this case is about the exit code
        ),
    )
    result = CliRunner().invoke(main.app, ["logout"])
    assert result.exit_code == 4, result.output
    assert result.output.startswith("session forgotten, not revoked; cannot reach the API:")
    assert config.load_session() is None


def test_a_wrong_password_is_refused_with_exit_1(stack: Stack) -> None:
    result = stack.tadas("login", "--email", OWNER["email"], "--password", "nope", token=None)
    assert result.exit_code == 1
    assert "refused: not_authenticated: email or password is wrong" in result.output


def test_a_task_that_changed_while_the_command_ran_is_refused_with_exit_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A verb reads the task, then writes naming the version it read; a write
    that landed in between is refused with 412, and the command says so in
    words a person acts on, not the code."""

    async def stale() -> None:
        raise ApiError(412, "precondition_failed", "task t is at version 3, not 2", "req_1")

    with pytest.raises(typer.Exit) as exited:
        main._run(stale(), signed_in=True)  # pyright: ignore[reportPrivateUsage]
    assert exited.value.exit_code == 1
    assert capsys.readouterr().err == "refused: the task changed while this ran; run it again\n"


def test_a_task_past_the_plans_bound_is_refused_with_exit_1_and_says_who_lifts_it(
    stack: Stack,
) -> None:
    billing = stack.container.storage.get_billing_storage()
    account = run(billing.read_account(stack.org_id))
    assert account is not None
    run(billing.write_account(stack.org_id, account.model_copy(update={"comped_plan": None}), ()))
    for n in range(10):
        assert stack.tadas("add", f"task {n}").exit_code == 0
    refused = stack.tadas("add", "one too many")
    assert refused.exit_code == 1
    assert refused.output == (
        "refused: the free plan allows 10 active tasks; an owner or an admin can change "
        "the plan in the portal, under Settings, Billing\n"
    )


def test_not_signed_in_is_exit_3(stack: Stack) -> None:
    result = stack.tadas("ls", token=None)
    assert result.exit_code == 3 and "run `tadas login`" in result.output
    bad = stack.tadas("ls", token="ses_nope")
    assert bad.exit_code == 3 and "credential was refused" in bad.output


def test_the_task_verbs_in_sequence(stack: Stack) -> None:
    added = stack.tadas("add", "Migrate DB", "--assignee", "bob")
    assert added.exit_code == 0, added.output
    verb, short, title = added.output.split(maxsplit=2)
    assert (verb, title.strip()) == ("added", "Migrate DB") and len(short) == 8

    second = stack.tadas("add", "Review PR #42", "--notes", "the auth one", "--assignee", "me")
    assert second.exit_code == 0, second.output

    listed = stack.tadas("ls")
    assert listed.exit_code == 0, listed.output
    lines = listed.output.splitlines()
    assert lines[0].startswith("ID        STATUS  ASSIGNEE")
    assert [line.split("  ")[-1].strip() for line in lines[1:]] == ["Review PR #42", "Migrate DB"]
    assert "Bob" in lines[2] and "Ann" in lines[1]

    edited = stack.tadas("edit", short, "--title", "Migrate the DB", "--unassign")
    assert edited.exit_code == 0 and edited.output == f"edited {short}  Migrate the DB\n"

    done = stack.tadas("done", short)
    assert done.output == f"done {short}  Migrate the DB\n"
    assert "Migrate the DB" not in stack.tadas("ls").output
    assert "Migrate the DB" in stack.tadas("ls", "--done").output

    reopened = stack.tadas("reopen", short, "--json")
    assert reopened.exit_code == 0
    assert json.loads(reopened.output)["status"] == "open"
    lines = stack.tadas("ls").output.splitlines()
    assert lines[1].endswith("Migrate the DB")  # back at the top

    mine = stack.tadas("ls", "--mine")  # assigned to me, or unassigned and created by me
    assert "Review PR #42" in mine.output and "Migrate the DB" in mine.output
    bobs = stack.tadas("ls", "--mine", token=stack.session_token(BOB["email"], BOB["password"]))
    assert bobs.output.count("\n") == 1  # the header only

    review_short = second.output.split()[1]
    moved = stack.tadas("mv", short, "--after", review_short)
    assert moved.exit_code == 0 and moved.output.startswith("moved")
    lines = stack.tadas("ls").output.splitlines()
    assert [line.split("  ")[-1].strip() for line in lines[1:]] == [
        "Review PR #42",
        "Migrate the DB",
    ]

    removed = stack.tadas("rm", short)
    assert removed.output == f"deleted {short}  Migrate the DB\n"
    assert stack.tadas("ls").output.count("\n") == 2


def test_ls_lists_past_the_page_the_api_clamps_at(stack: Stack) -> None:
    # 201 open tasks against the API's clamp of 200: `ls` follows the cursor
    # and shows every one, and a short id resolves on the second page too.
    token = stack.session_token(OWNER["email"], OWNER["password"])
    ctx = run(stack.container.managers.tenancy.authenticate(seed_request(), token))
    manager = stack.container.managers.tasks
    now = utcnow()
    for i in range(201):
        run(
            manager.create_task(
                ctx,
                Task(
                    id=new_id(),
                    created_at=now,
                    updated_at=now,
                    created_by=ctx.user_id,
                    updated_by=ctx.user_id,
                    title=f"t{i}",
                ),
            )
        )
    listed = stack.tadas("ls")
    assert listed.exit_code == 0, listed.output
    lines = listed.output.splitlines()[1:]
    assert len(lines) == 201 and lines[0].endswith("t200") and lines[-1].endswith("t0")
    last_short = lines[-1].split("  ")[0]
    done = stack.tadas("done", last_short)
    assert done.exit_code == 0 and done.output == f"done {last_short}  t0\n"


def test_short_ids_and_members_that_do_not_resolve(stack: Stack) -> None:
    stack.tadas("add", "one")
    stack.tadas("add", "two")
    ambiguous = stack.tadas("done", "")  # every id ends with the empty string
    assert ambiguous.exit_code == 1 and "more than one task" in ambiguous.output
    missing = stack.tadas("done", "ffffffff")
    assert missing.exit_code == 1 and "no task matches" in missing.output
    unknown = stack.tadas("add", "three", "--assignee", "carol")
    assert unknown.exit_code == 1 and "names no member" in unknown.output
    nothing = stack.tadas("edit", "")
    assert nothing.exit_code == 2 and "nothing to change" in nothing.output
    both = stack.tadas("mv", "", "--top", "--after", "")
    assert both.exit_code == 2 and "exactly one" in both.output


def test_a_member_sees_the_owners_tasks_and_the_api_decides_what_is_allowed(stack: Stack) -> None:
    stack.tadas("add", "Owner's task")
    bob = stack.session_token(BOB["email"], BOB["password"])
    listed = stack.tadas("ls", token=bob)
    assert "Owner's task" in listed.output
    assert stack.tadas("whoami", token=bob).output == "Bob <bob@example.test> at Acme (member)\n"


def test_the_client_is_built_with_the_timeout_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TADAS_HTTP_TIMEOUT_SECONDS", raising=False)
    assert config.timeout_seconds() == config.DEFAULT_TIMEOUT_SECONDS
    assert main.build_client("http://127.0.0.1:1", None).timeout == config.DEFAULT_TIMEOUT_SECONDS
    monkeypatch.setenv("TADAS_HTTP_TIMEOUT_SECONDS", "2.5")
    assert config.timeout_seconds() == 2.5
    assert main.build_client("http://127.0.0.1:1", None).timeout == 2.5
    for bad in ("soon", "0", "-1"):
        monkeypatch.setenv("TADAS_HTTP_TIMEOUT_SECONDS", bad)
        with pytest.raises(ValueError):
            config.timeout_seconds()


def test_the_client_is_built_with_the_retry_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The count and the delay travel from the settings into the client the
    way the timeout does, so the CLI never wraps it in a retry of its own."""
    for name in ("TADAS_HTTP_RETRIES", "TADAS_HTTP_RETRY_BACKOFF_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    built = main.build_client("http://127.0.0.1:1", None)
    assert built.retries == config.DEFAULT_RETRIES
    assert built.backoff_seconds == config.DEFAULT_BACKOFF_SECONDS
    monkeypatch.setenv("TADAS_HTTP_RETRIES", "0")
    monkeypatch.setenv("TADAS_HTTP_RETRY_BACKOFF_SECONDS", "1.5")
    built = main.build_client("http://127.0.0.1:1", None)
    assert built.retries == 0 and built.backoff_seconds == 1.5
    for bad in ("two", "-1", "1.5"):
        monkeypatch.setenv("TADAS_HTTP_RETRIES", bad)
        with pytest.raises(config.BadSetting):
            config.retries()
    monkeypatch.delenv("TADAS_HTTP_RETRIES")
    for bad in ("soon", "0", "-1"):
        monkeypatch.setenv("TADAS_HTTP_RETRY_BACKOFF_SECONDS", bad)
        with pytest.raises(config.BadSetting):
            config.backoff_seconds()


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("reset")],
    ids=["refused", "timed out", "reset"],
)
def test_an_api_that_cannot_be_reached_is_exit_4(
    monkeypatch: pytest.MonkeyPatch, failure: httpx.TransportError
) -> None:
    """Every failure of the wire, not only a refused connection, is exit 4."""

    def raise_failure(request: httpx.Request) -> httpx.Response:
        raise failure

    monkeypatch.setattr(
        main,
        "build_client",
        lambda _url, token: ApiClient(
            "http://test",
            app="cli",
            app_version="cli@test",
            token=token,
            transport=httpx.MockTransport(raise_failure),
            backoff_seconds=0.0,  # the retry still runs; this case is about the exit code
        ),
    )
    result = CliRunner().invoke(
        main.app, ["ls"], env={"TADAS_API_URL": "http://test", "TADAS_TOKEN": "ses_1"}
    )
    assert result.exit_code == 4, result.output
    assert result.output.startswith("cannot reach the API:")


@pytest.mark.parametrize(
    "bad",
    ["soon", "0", "-1", "1e", " "],
    ids=["word", "zero", "negative", "half a number", "blank"],
)
def test_a_timeout_the_environment_got_wrong_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """A setting the environment got wrong is the caller's input, so it is
    exit 2 and one line, inside the exit-code contract, for every command:
    the signed-in ones, `login`, and `logout`."""
    monkeypatch.setenv("TADAS_HOME", str(tmp_path / "home"))
    environment = {
        "TADAS_API_URL": "http://127.0.0.1:1",
        "TADAS_TOKEN": "ses_1",
        "TADAS_HTTP_TIMEOUT_SECONDS": bad,
    }
    runner = CliRunner()
    for command in (["ls"], ["listen"], ["login", "--email", "a@b.test", "--password", "pw"]):
        result = runner.invoke(main.app, command, env=environment, catch_exceptions=False)
        assert result.exit_code == 2, f"{command}: {result.output}"
        assert result.output.startswith("TADAS_HTTP_TIMEOUT_SECONDS"), result.output


def test_a_bad_timeout_does_not_forget_the_session_logout_could_not_revoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`logout` forgets the session whatever the API answers, but a setting
    the environment got wrong means the API was never asked: the session
    stays, so the caller fixes the setting and signs out for real."""
    monkeypatch.setenv("TADAS_HOME", str(tmp_path / "home"))
    session = config.Session(
        api_url="http://127.0.0.1:1",
        token="ses_1",
        email="ann@example.test",
        display_name="Ann",
        org_slug="acme",
        org_name="Acme",
    )
    config.save_session(session)
    result = CliRunner().invoke(
        main.app, ["logout"], env={"TADAS_HTTP_TIMEOUT_SECONDS": "soon"}, catch_exceptions=False
    )
    assert result.exit_code == 2, result.output
    assert result.output.startswith("TADAS_HTTP_TIMEOUT_SECONDS")
    assert config.load_session() == session


def test_a_token_the_environment_got_wrong_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A credential travels in a header, which carries ascii and nothing else.
    A copy that brought a typographic quote with it is the caller's input: one
    line and exit 2, and the line names the variable, never the secret in it."""
    monkeypatch.setenv("TADAS_HOME", str(tmp_path / "home"))
    smuggled = "ses_" + chr(0x2019) + "secret"  # the quote a document turned typographic
    result = CliRunner().invoke(
        main.app,
        ["ls"],
        env={"TADAS_API_URL": "http://127.0.0.1:1", "TADAS_TOKEN": smuggled},
        catch_exceptions=False,
    )
    assert result.exit_code == 2, result.output
    assert result.output == "TADAS_TOKEN has characters a request header cannot carry\n"
    assert "secret" not in result.output


def test_a_session_that_cannot_be_kept_is_a_usage_error(stack: Stack, tmp_path: Path) -> None:
    """The API signed the caller in, but TADAS_HOME names a place the CLI
    cannot write: one line naming the place, exit 2, no traceback."""
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")
    result = stack.tadas(
        "login",
        "--email",
        OWNER["email"],
        "--password",
        OWNER["password"],
        token=None,
        env={"TADAS_HOME": str(blocked / "tadas")},
    )
    assert result.exit_code == 2, result.output
    assert result.output.startswith("the session cannot be kept in "), result.output


def test_a_session_that_cannot_be_forgotten_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`logout` forgets the file whatever the API answers, so a file it cannot
    remove is the one thing left to tell: one line and exit 2."""
    monkeypatch.setenv("TADAS_HOME", str(tmp_path / "home"))
    config.save_session(
        config.Session(
            api_url="http://127.0.0.1:1",
            token="ses_1",
            email="ann@example.test",
            display_name="Ann",
            org_slug="acme",
            org_name="Acme",
        )
    )

    def refuse(self: Path, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "unlink", refuse)
    result = CliRunner().invoke(main.app, ["logout"], catch_exceptions=False)
    assert result.exit_code == 2, result.output
    assert result.output.startswith("the session cannot be forgotten: "), result.output


def second_org(stack: Stack) -> None:
    """The owner also belongs to Beta, as a member."""
    tenancy = stack.container.managers.tenancy
    run(tenancy.bootstrap(seed_request(), "Beta", "beta", "bea@example.test", "pw-1234", "Bea"))
    run(
        tenancy.add_member(
            seed_request(), "beta", OWNER["email"], OWNER["password"], OWNER["name"], Role.MEMBER
        )
    )


def test_orgs_lists_where_the_person_belongs_and_marks_the_current_one(stack: Stack) -> None:
    second_org(stack)
    stack.tadas(
        "login",
        "--email",
        OWNER["email"],
        "--password",
        OWNER["password"],
        "--org",
        "acme",
        token=None,
    )
    listed = stack.tadas("orgs", token=None)
    assert listed.exit_code == 0, listed.output
    acme, mine, beta = listed.output.splitlines()
    assert acme.startswith("* acme ") and acme.endswith("  Acme (owner)")
    assert mine.startswith("  ann-") and mine.endswith("  Ann (owner, personal)")
    assert beta.startswith("  beta ") and beta.endswith("  Beta (member)")
    as_json = stack.tadas("orgs", "--json", token=None)
    teams = [m["org"]["slug"] for m in json.loads(as_json.output) if m["org"]["kind"] == "team"]
    assert sorted(teams) == ["acme", "beta"]


def test_switch_moves_the_kept_session_and_ends_the_old_one(stack: Stack) -> None:
    second_org(stack)
    stack.tadas(
        "login",
        "--email",
        OWNER["email"],
        "--password",
        OWNER["password"],
        "--org",
        "acme",
        token=None,
    )
    before = config.load_session()
    assert before is not None
    moved = stack.tadas("switch", "beta", token=None)
    assert moved.exit_code == 0, moved.output
    assert moved.output == "switched to Beta as Ann (member); the old session is ended\n"
    after = config.load_session()
    assert after is not None and after.org_slug == "beta" and after.token != before.token
    who = stack.tadas("whoami", token=None)
    assert who.output == "Ann <ann@example.test> at Beta (member)\n"
    # The session the file held before is over.
    old = stack.tadas("whoami", token=before.token)
    assert old.exit_code == 3, old.output


def test_switch_to_an_org_the_person_is_not_in_is_a_usage_error(stack: Stack) -> None:
    stack.tadas("login", "--email", OWNER["email"], "--password", OWNER["password"], token=None)
    before = config.load_session()
    out = stack.tadas("switch", "nope", token=None)
    assert out.exit_code == 2, out.output
    assert "no org 'nope' to switch to; yours are: acme" in out.output
    assert config.load_session() == before


def test_switch_needs_a_kept_session(stack: Stack) -> None:
    out = stack.tadas("switch", "acme")  # TADAS_TOKEN is the environment's, not the CLI's
    assert out.exit_code == 3, out.output
    assert "no kept session to switch" in out.output
