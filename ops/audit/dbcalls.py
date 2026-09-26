"""The database calls of every endpoint and flow, counted where they leave
the process.

    uv run python ops/audit/dbcalls.py run audit_<run> --out <results.json> \
        [--flows <extra.py> ...] [--only tasks,sweep]
    uv run python ops/audit/dbcalls.py summary <results.json>

`run` builds the real API and the real worker in this process over the
audit database (Postgres storage, the provider twins, the local infra),
drives them through the flows of `dbcalls_flows.py` and of any `--flows`
file, and counts at the asyncpg adapter: each `BEGIN`, each statement, each
`COMMIT` or `ROLLBACK`, and each `PREPARE` a cold statement cache sends. It
labels every transaction the storage funnel opens with its role, its scope,
and the storage method that opened it. A flow is an `async def` that takes
the `World` and calls `world.http(...)` for a request or
`world.measure(...)` for a manager or worker call; a flows file lists its
flows in `FLOWS`, in order.

`summary` folds the results into one line per call: its count, the warm
round trips (every statement already prepared), the transactions, and the
roles, each as a range when the call ran more than once.

The counter is installed in this process only, by patching the adapter's
classes; nothing of it reaches the application's own code.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import importlib.util
import json
import logging
import sys
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------- counter


@dataclass
class Trip:
    kind: str  # BEGIN, PREPARE, EXEC, EXECMANY, COMMIT, ROLLBACK
    sql: str
    txn: int | None


@dataclass
class Txn:
    n: int
    role: str
    scope: str  # system or tenant
    method: str
    trips: list[Trip] = field(default_factory=list)


@dataclass
class Recorder:
    trips: list[Trip] = field(default_factory=list)
    txns: list[Txn] = field(default_factory=list)

    def mark(self) -> tuple[int, int]:
        return len(self.trips), len(self.txns)

    def since(self, mark: tuple[int, int]) -> Window:
        return Window(self.trips[mark[0] :], self.txns[mark[1] :])

    def record(self, kind: str, sql: str) -> None:
        txn = CURRENT.get()
        trip = Trip(kind, " ".join(sql.split())[:300], txn.n if txn else None)
        self.trips.append(trip)
        if txn is not None:
            txn.trips.append(trip)


@dataclass
class Window:
    trips: list[Trip]
    txns: list[Txn]

    @property
    def round_trips(self) -> int:
        return len(self.trips)

    @property
    def prepares(self) -> int:
        return sum(1 for t in self.trips if t.kind == "PREPARE")

    @property
    def warm_round_trips(self) -> int:
        return self.round_trips - self.prepares

    @property
    def statements(self) -> int:
        return sum(1 for t in self.trips if t.kind in ("EXEC", "EXECMANY"))

    @property
    def roles(self) -> list[str]:
        return sorted({t.role for t in self.txns})

    def detail(self) -> list[str]:
        """One line per transaction: its role and scope, the storage method,
        its round trips, and the statements after the scope's own."""
        lines = []
        for txn in self.txns:
            kinds = [t.kind for t in txn.trips if t.kind != "PREPARE"]
            statements = [t.sql[:200] for t in txn.trips if t.kind in ("EXEC", "EXECMANY")][1:]
            lines.append(
                f"T{txn.n} {txn.role}/{txn.scope} {txn.method}: {len(kinds)} trips | "
                + " ; ".join(statements)
            )
        stray = [t for t in self.trips if t.txn is None]
        if stray:
            lines.append(f"outside the funnel: {len(stray)} trips")
        return lines


REC = Recorder()
CURRENT: contextvars.ContextVar[Txn | None] = contextvars.ContextVar("audit_txn", default=None)
_installed = False


def install() -> None:
    """Wraps the asyncpg adapter's round trips and the storage funnel. Once
    per process; a second call does nothing."""
    global _installed
    if _installed:
        return
    _installed = True
    from sqlalchemy.dialects.postgresql import asyncpg as sa_asyncpg

    from tadas.om.base import EMPTY_UUID
    from tadas.om.storage.impl import pg_base

    connection = sa_asyncpg.AsyncAdapt_asyncpg_connection
    cursor = sa_asyncpg.AsyncAdapt_asyncpg_cursor

    def wrap(
        cls: Any, name: str, kind: str, sql_of: Callable[..., str], when: Callable[..., bool]
    ) -> None:
        original = getattr(cls, name)

        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            if when(self, *args, **kwargs):
                REC.record(kind, sql_of(self, *args, **kwargs))
            return await original(self, *args, **kwargs)

        setattr(cls, name, wrapper)

    def cold(self: Any, operation: str, asof: Any) -> bool:
        cache = self._prepared_statement_cache
        if cache is None or operation not in cache:
            return True
        return not cache[operation][2] > asof

    wrap(
        connection,
        "_start_transaction",
        "BEGIN",
        lambda *_: "",
        lambda self: self.isolation_level != "autocommit",
    )
    wrap(connection, "_prepare", "PREPARE", lambda self, op, asof: op, cold)
    wrap(connection, "_commit_and_discard", "COMMIT", lambda *_: "", lambda *_: True)
    wrap(connection, "_rollback_and_discard", "ROLLBACK", lambda *_: "", lambda *_: True)

    # A statement is recorded once it returns, after the BEGIN and the PREPARE it caused.
    execute = cursor._prepare_and_execute

    async def execute_wrapper(self: Any, operation: str, parameters: Any) -> Any:
        try:
            return await execute(self, operation, parameters)
        finally:
            REC.record("EXEC", operation)

    cursor._prepare_and_execute = execute_wrapper
    many = cursor._executemany

    async def many_wrapper(self: Any, operation: str, seq: Any) -> Any:
        try:
            return await many(self, operation, seq)
        finally:
            REC.record("EXECMANY", f"[{len(seq)} rows] {operation}")

    cursor._executemany = many_wrapper  # type: ignore[assignment]
    session_for = pg_base.PgStorageBase._session_for

    @asynccontextmanager
    async def labelled(
        self: Any, target: Any, *, org_id: Any, user_id: Any = None, identity_id: Any = None
    ):
        role = pg_base.role_of(target).value
        frame = sys._getframe(2)
        while frame and "contextlib" in frame.f_code.co_filename:
            frame = frame.f_back
        owner = type(self).__name__.replace("StoragePostgresImpl", "")
        method = f"{owner}.{frame.f_code.co_name}" if frame else "?"
        txn = Txn(len(REC.txns), role, "system" if org_id == EMPTY_UUID else "tenant", method)
        REC.txns.append(txn)
        token = CURRENT.set(txn)
        try:
            async with session_for(
                self, target, org_id=org_id, user_id=user_id, identity_id=identity_id
            ) as s:
                yield s
        finally:
            CURRENT.reset(token)

    pg_base.PgStorageBase._session_for = labelled  # type: ignore[method-assign]


# --------------------------------------------------------------------- world


@dataclass
class Row:
    area: str
    name: str
    status: str
    round_trips: int
    warm_round_trips: int
    prepares: int
    statements: int
    txns: int
    roles: list[str]
    note: str
    detail: list[str]


class World:
    """What a flow drives: the API in process (`client`, `http`), the worker
    (`worker`, `loop`), their containers, the twins, and `sql` for the
    setup a flow needs that no route makes (aging rows). Flows share it, in
    order, and may keep what they made on it (`world.state`)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rows: list[Row] = []
        self.state: dict[str, Any] = {}
        self.client: Any = None
        self.container: Any = None
        self.worker: Any = None
        self.loop: Any = None
        self.idp: Any = None
        self.integrations: Any = None
        self.storage: Any = None
        self.infra: Any = None

    def mark(self) -> tuple[int, int]:
        """Where the counter stands; `since(mark)` is what was sent after it."""
        return REC.mark()

    def since(self, mark: tuple[int, int]) -> Window:
        return REC.since(mark)

    def record(self, area: str, name: str, status: object, window: Window, note: str = "") -> None:
        self.rows.append(
            Row(
                area,
                name,
                str(status),
                window.round_trips,
                window.warm_round_trips,
                window.prepares,
                window.statements,
                len(window.txns),
                window.roles,
                note,
                window.detail(),
            )
        )

    async def http(
        self, area: str, name: str, method: str, path: str, *, note: str = "", **kw: Any
    ) -> Any:
        """One request through the app, counted."""
        mark = REC.mark()
        response = await self.client.request(method, path, **kw)
        self.record(area, name, response.status_code, REC.since(mark), note)
        return response

    async def measure[T](
        self, area: str, name: str, call: Callable[[], Awaitable[T]], note: str = ""
    ) -> T | None:
        """One manager or worker call, counted; an exception is its status."""
        mark = REC.mark()
        value: T | None = None
        try:
            value = await call()
            status = "ok"
        except Exception as error:
            status = f"raised {type(error).__name__}: {str(error)[:120]}"
        self.record(area, name, status, REC.since(mark), note)
        return value

    async def sql(self, statement: str) -> list[Any]:
        """A statement as the local superuser on the audit database, uncounted:
        setup a flow needs that no route makes, such as aging rows."""
        from auditdb import superuser_on
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(superuser_on(self.name))
        try:
            async with engine.begin() as connection:
                result = await connection.exec_driver_sql(statement)
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()


@asynccontextmanager
async def world(name: str) -> AsyncIterator[World]:
    """The API and the worker over the audit database, the counter installed."""
    install()
    import httpx
    from auditdb import check_name, urls

    from tadas.infra.impl.local import InfraLocalImpl
    from tadas.integrations.identity.twin import IdentityProviderTwinImpl
    from tadas.integrations.impl.configured import IntegrationsOverImpl, payments_for, slack_for
    from tadas.services.api.app import create_app
    from tadas.services.api.container import AppContainer, postgres_storage
    from tadas.services.api.settings import ApiSettings
    from tadas.workers.maintenance.container import WorkerContainer, worker_managers
    from tadas.workers.maintenance.main import build_loop
    from tadas.workers.maintenance.settings import MaintenanceSettings

    values = urls(check_name(name))
    common = {
        "_env_file": None,
        "environment": "test",
        "billing_backend": "twin",
        "slack_backend": "twin",
        "database_url": values["TADAS_DATABASE_URL"],
        "database_system_url": values["TADAS_DATABASE_SYSTEM_URL"],
    }
    settings = ApiSettings.model_validate(
        {
            **common,
            "totp_encryption_key": "dGFkYXMtdGVzdHMtdG90cC1rZXktdGhpcnR5LXR3byE=",
            "dev_sign_in_enabled": True,
            "sentry_dsn": None,
            "otel_endpoint": None,
        }
    )
    w = World(name)
    w.storage = postgres_storage(settings)
    w.idp = IdentityProviderTwinImpl()
    w.integrations = IntegrationsOverImpl(
        w.idp,
        payments_for(settings, settings.environment),
        slack_for(settings, settings.environment),
    )
    w.infra = InfraLocalImpl(Path(tempfile.mkdtemp(prefix=f"{name}_")))
    w.container = AppContainer.for_tests(w.storage, w.infra, settings, w.integrations)
    ms = MaintenanceSettings.model_validate({**common, "worker_id": f"{name}-worker"})
    w.worker = WorkerContainer(
        ms,
        w.storage,
        w.infra,
        worker_managers(w.storage, w.infra, w.integrations, ms),
        w.integrations,
    )
    w.loop = build_loop(w.worker)
    logging.getLogger().setLevel(logging.WARNING)
    app = create_app(w.container)
    async with app.router.lifespan_context(app):
        # The app's start sets its own log level; a run prints its flows only.
        logging.getLogger().setLevel(logging.WARNING)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            w.client = client
            yield w


# --------------------------------------------------------------------- run


Flow = Callable[[World], Awaitable[None]]


def load_flows(path: Path) -> list[Flow]:
    spec = importlib.util.spec_from_file_location(f"audit_flows_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load flows from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    flows = getattr(module, "FLOWS", None)
    if not flows:
        raise SystemExit(f"{path} lists no FLOWS")
    return list(flows)


def selected(flows: list[Flow], only: set[str] | None) -> Iterator[Flow]:
    """The built-in flows to run: every one, or those named, and `seed`
    always, first. A `--flows` file's flows all run, after these."""
    for flow in flows:
        if only is None or flow.__name__ in only or flow.__name__ == "seed":
            yield flow


async def run(name: str, extra: list[Path], only: set[str] | None, out: Path) -> int:
    flows = list(selected(load_flows(Path(__file__).with_name("dbcalls_flows.py")), only))
    for path in extra:
        flows += load_flows(path)
    failed = 0
    async with world(name) as w:
        for flow in flows:
            try:
                await flow(w)
                print(f"{flow.__name__}: done", flush=True)
            except Exception as error:
                failed += 1
                print(f"{flow.__name__}: failed: {type(error).__name__}: {error}", flush=True)
            text = json.dumps([row.__dict__ for row in w.rows], indent=1)
            await asyncio.to_thread(out.write_text, text)
    print(f"{len(w.rows)} calls recorded in {out}; {failed} flows failed")
    return 1 if failed else 0


# --------------------------------------------------------------------- summary


def span(values: list[int]) -> str:
    low, high = min(values), max(values)
    return f"{low}" if low == high else f"{low}-{high}"


def summary(rows: list[dict[str, Any]]) -> list[str]:
    """One table line per (area, call), in the order they first ran."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["area"], row["name"]), []).append(row)
    lines = [
        "| Area | Call | Runs | Round trips (warm) | Transactions | Roles | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for (area, name), runs in groups.items():
        roles = ",".join(sorted({r for run in runs for r in run["roles"]})) or "none"
        status = "; ".join(sorted({str(run["status"])[:40] for run in runs}))
        lines.append(
            f"| {area} | {name} | {len(runs)} | {span([r['warm_round_trips'] for r in runs])} "
            f"| {span([r['txns'] for r in runs])} | {roles} | {status} |"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dbcalls", description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="drive the flows over the audit database and count")
    r.add_argument("name")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--flows", type=Path, action="append", default=[], help="a file of more FLOWS")
    r.add_argument(
        "--only", help="comma-separated built-in flows; seed always runs, --flows files in full"
    )
    s = sub.add_parser("summary", help="one line per call from a results file")
    s.add_argument("results", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        only = set(args.only.split(",")) if args.only else None
        return asyncio.run(run(args.name, args.flows, only, args.out))
    print("\n".join(summary(json.loads(args.results.read_text()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
