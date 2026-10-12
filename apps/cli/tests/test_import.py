"""`tadas import` and `tadas imports` over the in-process API and a scripted
channel: the file uploaded and its import started, then followed as the
worker's steps land (run here through the managers, as the worker runs
them) until it stops; the line each outcome ends on, and its exit code; the
org's imports listed; and a parked import resumed rather than started
again."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from uuid import UUID

import pytest
from api_support import OWNER, account_written, run, seed_request
from cli_support import Stack

from tadas.apps.cli import imports, main
from tadas.client.client import ApiClient
from tadas.client.envelopes import EntityChanged
from tadas.client.realtime import State
from tadas.client.types import ImportView
from tadas.om.base import new_id
from tadas.om.billing.types.plan import Plan
from tadas.om.orchestrations.types.orchestration import OrchestrationStatus


def worker_steps(stack: Stack) -> imports.OpenChannel:
    """A channel whose pushes are the worker's steps: after the first open,
    each step of every running import of the org is taken through the
    managers and pushed, as the socket would carry it."""

    async def channel(
        client: ApiClient,
        on_state: Callable[[State], None],
        on_first_open: Callable[[], Awaitable[None]],
    ) -> AsyncIterator[EntityChanged]:
        await on_first_open()
        managers = stack.container.managers
        owner = await managers.tenancy.authenticate(
            seed_request(), stack.session_token(OWNER["email"])
        )
        ctx = await managers.tenancy.service_context(seed_request(), owner.org_id, owner.user_id)
        seq = 0
        while running := [
            r
            for r in (await managers.tasks.imports.get_imports(ctx, 20)).items
            if r.status is OrchestrationStatus.RUNNING
        ]:
            for record in running:
                record = await managers.tasks.imports.step_import(ctx, record)
                seq += 1
                yield EntityChanged(
                    kind="orchestrations.orchestration.updated",
                    target_id=record.id,
                    seq=seq,
                    actor_id=owner.user_id,
                )

    return channel


@pytest.fixture
def follows_the_worker(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    channel = worker_steps(stack)

    async def follow(client: ApiClient, import_id: UUID) -> ImportView:
        return await imports.follow(client, import_id, channel=channel)

    monkeypatch.setattr(main, "follow", follow)


@pytest.mark.usefixtures("follows_the_worker")
def test_an_import_is_uploaded_started_and_followed_to_its_end(
    stack: Stack, tmp_path: Path
) -> None:
    rows = tmp_path / "tasks.csv"
    rows.write_text("title,due_on\n" + "".join(f"Task {n},\n" for n in range(1, 151)) + ",\n")
    result = stack.tadas("import", str(rows))
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-3:] == [
        "created 0 of ?, skipped 0",
        "created 100 of 150, skipped 0",
        "imported: created 150 of 150, skipped 0",
    ]
    listed = stack.tadas("ls", "--json")
    assert '"Task 150"' in listed.output


@pytest.mark.usefixtures("follows_the_worker")
def test_a_file_that_is_not_csv_fails_the_import_and_exits_1(stack: Stack, tmp_path: Path) -> None:
    rows = tmp_path / "tasks.csv"
    rows.write_text("name,notes\nno,title\n")
    result = stack.tadas("import", str(rows))
    assert result.exit_code == 1
    assert result.output.splitlines()[-1] == "failed: no title column (created 0 of ?, skipped 0)"


def on_plan(stack: Stack, plan: Plan | None) -> None:
    """Puts the org on `plan` (None is Free) in storage, as an operator's
    grant would, with no wake of what parked."""
    billing = stack.container.storage.get_billing_storage()
    account = run(billing.read_account(stack.org_id))
    assert account is not None
    run(billing.write_account(stack.org_id, account.model_copy(update={"comped_plan": plan}), ()))
    run(account_written(stack.container, stack.org_id))


@pytest.mark.usefixtures("follows_the_worker")
def test_imports_lists_the_orgs_imports_and_resume_goes_on_with_a_parked_one(
    stack: Stack, tmp_path: Path
) -> None:
    on_plan(stack, None)  # Free: ten active tasks
    broken = tmp_path / "notes.csv"
    broken.write_text("name\nno title\n")
    assert stack.tadas("import", str(broken)).exit_code == 1
    rows = tmp_path / "tasks.csv"
    rows.write_text("title\n" + "".join(f"Task {n}\n" for n in range(1, 16)))
    parked = stack.tadas("import", str(rows))
    assert parked.exit_code == 1
    assert parked.output.splitlines()[-1].startswith("parked at row 11")

    listed = stack.tadas("imports").output.splitlines()
    assert listed[0].split() == ["ID", "STATUS", "STARTED", "(UTC)", "PROGRESS"]
    assert [(line.split()[1], line.split(maxsplit=4)[4]) for line in listed[1:]] == [
        ("parked", "created 10 of 15, skipped 0"),
        ("failed", "created 0 of ?, skipped 0"),
    ]
    short = listed[1].split()[0]
    assert f"`tadas import --resume {short}`" in parked.output

    on_plan(stack, Plan.TEAM)  # room again, and nothing woke the import
    resumed = stack.tadas("import", "--resume", short)
    assert resumed.exit_code == 0, resumed.output
    assert resumed.stderr.splitlines()[0] == f"resuming {short}"
    assert resumed.stdout.splitlines()[-1] == "imported: created 15 of 15, skipped 0"
    after = stack.tadas("imports", "--json")
    assert [(i["id"][-8:], i["status"]) for i in json.loads(after.stdout)] == [
        (short, "succeeded"),
        (listed[2].split()[0], "failed"),
    ], "the parked import went on; no second import started"


def test_import_takes_a_file_or_resume_and_refuses_an_id_no_import_has(
    stack: Stack, tmp_path: Path
) -> None:
    rows = tmp_path / "tasks.csv"
    rows.write_text("title\nOne\n")
    assert stack.tadas("import").exit_code == 2
    both = stack.tadas("import", str(rows), "--resume", "abc")
    assert (both.exit_code, both.stderr) == (2, "give exactly one of a CSV file and --resume\n")
    for reference in ("nothing", "", "../../etc"):
        missing = stack.tadas("import", "--resume", reference)
        assert missing.exit_code == 1
        assert missing.stderr.startswith("no recent import matches")


def view(**fields: object) -> ImportView:
    return ImportView.model_validate(
        {
            "id": str(new_id()),
            "file_id": str(new_id()),
            "status": "running",
            "total": 50,
            "cursor": 10,
            "created": 10,
            "skipped": 0,
            "row_errors": [],
            "park_reason": None,
            "fail_reason": None,
            "created_at": "2026-09-25T09:00:00Z",
            "updated_at": "2026-09-25T09:00:00Z",
            "finished_at": None,
            "created_by": str(new_id()),
            **fields,
        }
    )


def test_a_parked_import_says_where_it_stopped_and_what_lifts_it() -> None:
    parked = imports.outcome(view(status="parked", park_reason="plan_limit"))
    assert parked.startswith("parked at row 11: the plan's active tasks are full")
    assert "Settings, Billing" in parked and "Resume" in parked
    assert "`tadas import --resume " in parked
    assert imports.outcome(view(status="failed", fail_reason="too_many_rows")) == (
        "failed: too many rows (created 10 of 50, skipped 0)"
    )
