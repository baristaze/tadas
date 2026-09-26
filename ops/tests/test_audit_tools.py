"""The audit skills' tools under `ops/audit/`, without a database: the
refusals that keep a run on its own local database, the seed's scale, the
statement file's headers, the counter's arithmetic, and the deploy
timeline's reading of what the pipeline and the cluster record."""

import pytest
from auditdb import check_name, on_database
from dbcalls import Row, Trip, Txn, Window, selected, summary
from deploy_timeline import events, steps, when
from explain import SYSTEM, explain_sql, parse
from seed import FIXED, Counts, statements

HEAVY = FIXED["heavy_org"]


# ---------------------------------------------------------------- the database


@pytest.mark.parametrize(
    "name", ["tadas", "audit_", "audit_Upper", "audit_a;drop", "postgres", "x" * 60]
)
def test_a_database_not_named_for_an_audit_is_refused(name: str) -> None:
    with pytest.raises(SystemExit):
        check_name(name)


def test_an_audit_name_is_taken() -> None:
    assert check_name("audit_query_indexes_0926") == "audit_query_indexes_0926"


def test_a_remote_host_is_refused() -> None:
    with pytest.raises(SystemExit, match="local stack"):
        on_database("postgresql+asyncpg://tadas:secret@db.example.com:5432/tadas", "audit_x")


def test_the_url_keeps_its_login_and_moves_to_the_audit_database() -> None:
    url = on_database(
        "postgresql+asyncpg://tadas_runtime:tadas_runtime@127.0.0.1:55432/tadas", "audit_x"
    )
    assert url == "postgresql+asyncpg://tadas_runtime:tadas_runtime@127.0.0.1:55432/audit_x"


# ---------------------------------------------------------------- the seed


def test_scale_one_is_the_heavy_seed() -> None:
    counts = Counts.at(1)
    assert (counts.people, counts.members, counts.open_tasks, counts.events) == (
        5000,
        200,
        40000,
        1_000_000,
    )


def test_a_small_scale_keeps_the_shape_and_a_floor() -> None:
    counts = Counts.at(0.0001)
    assert counts.people == 3 and counts.members == 2 and counts.open_tasks == 4
    assert all(value >= 1 for value in counts.__dict__.values())


@pytest.mark.parametrize("scale", [0, -1, 11])
def test_a_scale_out_of_bounds_is_refused(scale: float) -> None:
    with pytest.raises(SystemExit):
        Counts.at(scale)


def test_the_seed_names_the_heavy_org_and_ends_with_analyze() -> None:
    named = statements(Counts.at(0.01))
    assert named[-1] == ("analyze", "ANALYZE")
    assert any(HEAVY in sql for _, sql in named)
    assert len({label for label, _ in named}) == len(named)


# ---------------------------------------------------------------- the statement file

FILE = f"""
-- a comment before the first header is skipped
-- name: open list, team
-- scope: {HEAVY}
SELECT * FROM core.tasks
WHERE org_id = '{HEAVY}' LIMIT 51;

-- name: the claim
-- scope: system
SELECT 1;

-- name: generic
-- scope: {HEAVY}
-- user: {HEAVY}
-- params: '{HEAVY}', 51
SELECT * FROM core.tasks WHERE org_id = $1 LIMIT $2;
"""


def test_a_file_reads_as_named_statements_with_their_scopes() -> None:
    team, claim, generic = parse(FILE)
    assert (team.name, team.scope, team.system) == ("open list, team", HEAVY, False)
    assert team.sql.endswith("LIMIT 51")
    assert (claim.scope, claim.system) == (SYSTEM, True)
    assert generic.user == HEAVY and generic.params == f"'{HEAVY}', 51"


def test_a_plain_statement_is_one_explain_and_a_generic_one_is_prepared_first() -> None:
    team, _, generic = parse(FILE)
    assert explain_sql(team) == [f"EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) {team.sql}"]
    prepare, mode, measure = explain_sql(generic)
    assert prepare.startswith("PREPARE audit_statement AS SELECT")
    assert mode == "SET LOCAL plan_cache_mode = force_generic_plan"
    assert measure.endswith(f"EXECUTE audit_statement('{HEAVY}', 51)")


@pytest.mark.parametrize(
    "source",
    [
        "SELECT 1;",  # no name, no scope
        "-- name: x\nSELECT 1;",  # no scope
        "-- name: x\n-- scope: not-a-uuid\nSELECT 1;",
        "-- name: x\n-- scope: system\nSELECT 1",  # no closing ';'
    ],
)
def test_a_statement_without_its_headers_is_refused(source: str) -> None:
    with pytest.raises(SystemExit):
        parse(source)


# ---------------------------------------------------------------- the counter


def window() -> Window:
    txn = Txn(0, "core", "tenant", "Tasks.read_task")
    trips = [
        Trip("BEGIN", "", 0),
        Trip("EXEC", "SELECT set_config('app.org_id', $1, true)", 0),
        Trip("PREPARE", "SELECT * FROM core.tasks", 0),
        Trip("EXEC", "SELECT * FROM core.tasks", 0),
        Trip("ROLLBACK", "", 0),
        Trip("EXEC", "SELECT 1", None),
    ]
    txn.trips = trips[:5]
    return Window(trips, [txn])


def test_a_window_counts_round_trips_warm_and_cold() -> None:
    w = window()
    assert (w.round_trips, w.prepares, w.warm_round_trips, w.statements) == (6, 1, 5, 3)
    assert w.roles == ["core"]
    first, stray = w.detail()
    assert first.startswith("T0 core/tenant Tasks.read_task: 4 trips | SELECT * FROM core.tasks")
    assert stray == "outside the funnel: 1 trips"


def row(
    name: str, trips: int, txns: int, roles: list[str], status: str = "200"
) -> dict[str, object]:
    return Row("tasks", name, status, trips, trips, 0, 0, txns, roles, "", []).__dict__


def test_the_summary_folds_repeated_calls_into_a_range() -> None:
    lines = summary(
        [
            row("GET /v1/tasks", 14, 3, ["core"]),
            row("POST /v1/tasks", 35, 8, ["activity", "core"], "201"),
            row("GET /v1/tasks", 18, 4, ["core"]),
        ]
    )
    assert lines[2] == "| tasks | GET /v1/tasks | 2 | 14-18 | 3-4 | core | 200 |"
    assert lines[3] == "| tasks | POST /v1/tasks | 1 | 35 | 8 | activity,core | 201 |"


def test_a_selection_always_runs_the_seed_first() -> None:
    async def seed(_: object) -> None: ...
    async def tasks(_: object) -> None: ...
    async def sweep(_: object) -> None: ...

    assert [f.__name__ for f in selected([seed, tasks, sweep], {"sweep"})] == ["seed", "sweep"]
    assert [f.__name__ for f in selected([seed, tasks, sweep], None)] == ["seed", "tasks", "sweep"]


# ---------------------------------------------------------------- the deploy timeline

RUN = {
    "createdAt": "2026-09-26T09:08:01Z",
    "jobs": [
        {
            "name": "apply",
            "startedAt": "2026-09-26T09:09:12Z",
            "completedAt": "2026-09-26T09:14:41Z",
            "steps": [
                {
                    "name": "plan",
                    "startedAt": "2026-09-26T09:09:19Z",
                    "completedAt": "2026-09-26T09:09:38Z",
                },
                {
                    "name": "apply",
                    "startedAt": "2026-09-26T09:09:39Z",
                    "completedAt": "2026-09-26T09:14:26Z",
                },
                {
                    "name": "tiny",
                    "startedAt": "2026-09-26T09:14:26Z",
                    "completedAt": "2026-09-26T09:14:27Z",
                },
            ],
        },
        {
            "name": "build",
            "startedAt": "2026-09-26T09:08:15Z",
            "completedAt": "2026-09-26T09:09:08Z",
            "steps": [],
        },
        {"name": "skipped", "startedAt": None, "completedAt": None, "steps": []},
    ],
}


def test_the_jobs_come_in_the_order_they_started_and_the_long_steps_longest_first() -> None:
    lines = steps(RUN, at_least=5)
    assert lines[0] == "run: 6m40s from creation to its last job's end"
    assert lines[4] == "| build | +0m14s | 0m53s |"
    assert lines[5] == "| apply | +1m11s | 5m29s |"
    long = lines[-2:]
    assert long == ["| apply | apply | 4m47s |", "| plan | apply | 0m19s |"]


def test_the_events_are_the_windows_own_oldest_first() -> None:
    services = {
        "services": [
            {
                "serviceName": "api",
                "events": [
                    {
                        "createdAt": "2026-09-25T22:24:42+00:00",
                        "message": "(service api) has reached a steady state.",
                    },
                    {
                        "createdAt": "2026-09-25T22:22:18+00:00",
                        "message": "(service api) task failed its health checks",
                    },
                    {"createdAt": "2026-09-25T20:00:00+00:00", "message": "an older deploy"},
                ],
            }
        ]
    }
    lines = events(services, when("2026-09-25T22:20:27Z"), when("2026-09-25T22:30:00Z"))
    assert lines[2:] == [
        "| +1m51s | api | (service api) task failed its health checks |",
        "| +4m15s | api | (service api) has reached a steady state. |",
    ]
