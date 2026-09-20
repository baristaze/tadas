# Tenant isolation: the cases, and the control that proves them

Tenancy is a data boundary and lives in storage. The predicate in the
query is the fence. `om/tests/unit/test_storage_exceptions.py` reads
signatures and says only that the tenant is offered to the query; a
method can take `org_id` and write a `WHERE` without it and pass there.
What says the query uses the tenant is the cross-tenant cases of the
contract suites: each presents another tenant's identifier and asserts
that nothing is found and nothing changes.

Each suite declares the methods it covers in a `CROSS_TENANT_CASES`
frozenset, and `test_every_tenant_method_is_named_in_a_cross_tenant_case`
holds those sets to the interfaces, so a storage method added with no
case fails the gate. That test reads names, not queries. A name listed
with no case behind it passes it. The control below is what keeps the
names honest.

## Running the control

A suite is worth what it catches, so the way to know is to break the
fence on purpose.

1. Pick one query. Take the tenant out of it: delete the `org_id`
   comparison from a `WHERE`, or swap a per-tenant helper for one that
   reads every row.
2. Run `make test-unit`. It must fail, and the failures must name the
   cross-tenant cases of the methods that query serves.
3. Put the predicate back and run `make test-unit` again. It must pass.

A predicate that goes missing with the suite still green is the finding
that matters. Write the case that catches it, confirm it fails, and add
it here.

Probe several queries, not one, and pick them to reach different
shapes: a helper the impls share, a method with a `WHERE` of its own,
a list, a page, the bulk write. The fast gate runs the memory impls,
so these are the queries a run here reaches. The Postgres queries carry
the same predicates in SQL and the same cases run over them under
`make test-integration`; a control against those is run on the compose
stack and recorded here the same way.

## The last run: 2026-09-20, over the memory impls

Eight queries, one at a time, each against `make test-unit`. Every one
failed the suite.

| Query | What the suite reported |
|---|---|
| `MemoryStorageBase._get`, the shared single-row read | 13 failed, 904 passed |
| `MemoryStorageBase._rows`, the shared list | 42 failed, 875 passed |
| `MemoryStorageBase._put`, the shared write fence | 8 failed, 909 passed |
| `TasksStorageMemoryImpl._live`, the helper the two task lists share | 8 failed, 909 passed |
| `TasksStorageMemoryImpl.update_tasks`, the bulk write's own check | 1 failed, 916 passed |
| `TenancyStorageMemoryImpl.read_sessions`, a list with its own filter | 2 failed, 915 passed |
| `TenancyStorageMemoryImpl.read_api_keys`, a page with its own filter | 5 failed, 912 passed |
| `OutboxStorageMemoryImpl.mark_done`, a write with its own check | 1 failed, 916 passed |

The narrow probes name the case that catches them. The bulk write's
check is caught by
`test_a_bulk_update_refuses_a_row_of_another_tenant_and_lands_none`
alone; `mark_done` by `test_mark_done_is_per_tenant_and_idempotent`
alone; `read_sessions` by
`test_the_session_reads_and_writes_are_tenant_scoped` and the list's own
ordering case.

## The hole the control found

`read_done_tasks` carries a `WHERE` of its own, and the suite had a
cross-tenant case for the open list and none for the done list. The two
share the `_live` helper, so a change to the helper was caught and a
predicate dropped from the done list alone was not.

Taking the tenant out of `read_done_tasks` and nothing else, against the
suite as it stood:

```
903 passed, 109 deselected in 28.91s
```

Green. Every task any tenant has carried to done was readable by every
other tenant, through storage and through `GET /v1/tasks?status=done`,
and nothing said so.

The same breach against the suite as it stands now:

```
om/tests/unit/test_task_storage.py::TestTaskStorageMemory::test_a_cursor_of_another_tenant_pages_nothing
om/tests/unit/test_task_storage.py::TestTaskStorageMemory::test_the_done_list_is_tenant_scoped_on_its_own
services/api/tests/test_tenant_isolation_api.py::test_no_list_carries_another_tenants_rows
3 failed, 914 passed in 29.70s
```

Two things closed it. `test_the_done_list_is_tenant_scoped_on_its_own`
and `test_a_cursor_of_another_tenant_pages_nothing` in
`om/tests/contracts/task_storage.py` give the done list and its cursor
cases of their own. And `seed_tenant` in
`services/api/tests/test_tenant_isolation_api.py` now carries one task
to done in each tenant: the API sweep read the done half of the task
list all along, over two tenants that had nothing done, so it passed on
an empty page.

## What the impls disagree on

These are known and not fixed. Both impls refuse the cross-tenant call
and both change nothing, so the boundary holds; what differs is what
the caller is told, and a contract two impls answer differently is two
contracts.

- `remove_member` under another tenant raises `NotFound` over memory
  (`om/src/tadas/om/tenancy/storage/impl/memory.py`, the `_get` guards
  in `remove_member`) and `TenantMismatch` over Postgres
  (`om/src/tadas/om/tenancy/storage/impl/postgres.py`, the `row.org_id`
  check in `remove_member`). That is a 404 on one impl and a 409 on the
  other. `test_remove_member_lands_whole_or_not_at_all` accepts both
  and asserts what they agree on.
- `append_event` refused for a tenant mismatch spends a sequence number
  over memory and none over Postgres
  (`om/src/tadas/om/events/storage/impl/memory.py`, `append_event`
  takes the next `seq` before `_put` raises). Postgres rolls the number
  back with the insert, which
  `test_a_retried_append_consumes_no_seq` states for the retry of an
  id the tenant already holds. Over memory, naming an id another tenant
  holds moves the naming tenant's cursor.
