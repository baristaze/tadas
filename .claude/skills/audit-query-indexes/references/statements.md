# The statement file, and the cases each statement is measured in

## The format

`ops/audit/explain.py plans` reads statements, each under its headers, and
runs `EXPLAIN (ANALYZE, BUFFERS)` of each under the login and the scope
the storage funnel would use, in a transaction it rolls back (a write is
measured and never kept).

```sql
-- name: tasks: open list, mine scope, idle member
-- scope: 01900000-0000-7000-8000-00000000b16b
-- user: <the member's user id>
SELECT * FROM core.tasks
WHERE org_id = '01900000-0000-7000-8000-00000000b16b' AND status = 'open'
  AND deleted_at IS NULL
  AND (assignee_id = '<user id>' OR (assignee_id IS NULL AND created_by = '<user id>'))
ORDER BY rank, id LIMIT 51;

-- name: tasks: open list, team scope, generic plan
-- scope: 01900000-0000-7000-8000-00000000b16b
-- params: '01900000-0000-7000-8000-00000000b16b', 'open', 51
SELECT * FROM core.tasks WHERE org_id = $1 AND status = $2 AND deleted_at IS NULL
ORDER BY rank, id LIMIT $3;

-- name: work: claim the next ready item
-- scope: system
SELECT id FROM queue.work_items
WHERE lane = 'default' AND status = 'queued' AND available_at <= now()
ORDER BY available_at, id LIMIT 1 FOR UPDATE SKIP LOCKED;
```

- `-- scope:` is the tenant, or `system` for a statement across tenants;
  `system` runs on the system login, a tenant on the runtime login, as
  the funnel does.
- `-- user:` sets `app.user_id` for a table whose policy reads it.
- `-- params:` measures the generic plan, the one asyncpg's prepared
  statement settles on after five runs: write `$1`, `$2` where the driver
  binds a value, and give the values in order as SQL literals.
- A statement ends with `;` at the end of a line.

Write the statement the storage impl sends: the same `WHERE`, `ORDER BY`,
`LIMIT`, and locking clause. When the ORM makes that hard to read, run
the flow through the counter (`uv run python ops/audit/dbcalls.py run
<db> --only <flow> --out <file>`) and read the statement from the
`detail` lines of its row.

## The ids a statement names

The seed's heavy team org is `01900000-0000-7000-8000-00000000b16b`. Read
the other ids a statement needs from the seeded data with `rows`, which
prints what one `SELECT` returns:

```bash
# the heavy org's busiest assignee
uv run python ops/audit/explain.py rows <db> "SELECT assignee_id, count(*) FROM core.tasks WHERE org_id = '01900000-0000-7000-8000-00000000b16b' AND assignee_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 1"
# a member of the heavy org with no task at all
uv run python ops/audit/explain.py rows <db> "SELECT u.id FROM core.users u WHERE u.org_id = '01900000-0000-7000-8000-00000000b16b' AND u.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM core.tasks t WHERE t.org_id = u.org_id AND (t.assignee_id = u.id OR t.created_by = u.id)) LIMIT 1"
# a small tenant
uv run python ops/audit/explain.py rows <db> "SELECT id FROM core.orgs WHERE kind = 'personal' LIMIT 1"
```

## The cases

Each statement is measured where its cost differs, not once:

- a small tenant and the heavy one;
- a list's first page and a deep page (a cursor far in);
- a filter that matches much (a busy member) and one that matches nothing
  (an idle member): the second is the one that walks the whole range;
- the tenant scope and, for a statement across tenants, the system scope,
  where the policy's estimate is at its worst;
- the generic plan (`-- params:`) for every statement that runs on every
  request or every write, since that is the plan it runs under.

## Contention, when `--focus` asks for it

A lock held across round trips (the event cursor on every append, a
claim) is measured by running the storage call from several tasks at
once, through the real storage impl on the run's database. Write the
script into the evidence folder, never into the repository:

```python
import asyncio, statistics, time
from auditdb import urls
from tadas.om.storage.impl.postgres import StoragePostgresImpl
from tadas.om.storage.roles import DatabaseRole
from tadas.om.storage.settings import RolePool

values = urls("audit_query_indexes_<yyyymmdd>")
pool = RolePool(size=40, checkout_timeout_seconds=30, statement_timeout_seconds=30)
storage = StoragePostgresImpl(
    {r: values["TADAS_DATABASE_URL"] for r in DatabaseRole},
    {r: pool for r in DatabaseRole},
    system_urls={r: values["TADAS_DATABASE_SYSTEM_URL"] for r in DatabaseRole},
)
# Call one storage method from 1, 4, 16, and 32 tasks for a few seconds
# each; report calls per second, p50, and p99 per level.
```

Run it with `uv run python <script>` from the repository root with
`PYTHONPATH=ops/audit`. One process caps at about a thousand simple calls
a second; say so when a level reaches it.
