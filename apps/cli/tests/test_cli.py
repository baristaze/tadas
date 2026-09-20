"""Command mode against the whole API in-process: sign in, the task verbs,
short ids, assignees by name, JSON output, and the exit codes."""

import json

import httpx
import pytest
from api_support import OWNER, run, seed_request
from cli_support import BOB, Stack
from typer.testing import CliRunner

from tadas.apps.cli import config, main
from tadas.client.client import ApiClient
from tadas.om.base import new_id, utcnow
from tadas.om.tasks.types.task import Task


def test_login_keeps_a_session_and_whoami_reads_it(stack: Stack) -> None:
    signed = stack.tadas(
        "login", "--email", OWNER["email"], "--password", OWNER["password"], token=None
    )
    assert signed.exit_code == 0, signed.output
    assert signed.output.startswith("signed in as Ann at Acme (owner); session kept in ")
    session = config.load_session()
    assert session is not None and session.org_slug == "acme" and session.api_url == "http://test"
    assert (config.home() / "session.json").stat().st_mode & 0o777 == 0o600

    who = stack.tadas("whoami", token=None)  # the session file, no TADAS_TOKEN
    assert who.exit_code == 0 and who.output == "Ann <ann@example.test> at Acme (owner)\n"

    out = stack.tadas("logout", token=None)
    assert out.exit_code == 0 and out.output == "signed out\n"
    assert config.load_session() is None
    assert stack.tadas("logout", token=None).output == "no session to forget\n"


def test_a_wrong_password_is_refused_with_exit_1(stack: Stack) -> None:
    result = stack.tadas("login", "--email", OWNER["email"], "--password", "nope", token=None)
    assert result.exit_code == 1
    assert "refused: not_authenticated: email or password is wrong" in result.output


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
        ),
    )
    result = CliRunner().invoke(
        main.app, ["ls"], env={"TADAS_API_URL": "http://test", "TADAS_TOKEN": "ses_1"}
    )
    assert result.exit_code == 4, result.output
    assert result.output.startswith("cannot reach the API:")
