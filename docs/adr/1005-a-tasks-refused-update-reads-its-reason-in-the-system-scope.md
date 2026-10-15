# ADR 1005: A task's refused update reads its reason in the system scope

**Status**: accepted (2026-10-14)

## Context

[ADR 0016, Row-level security is the second fence, taken by default](0016-row-level-security-is-the-second-fence.md)
narrows every transaction to its tenant, so a row of another tenant is
one the transaction cannot see.

A task's update, one or a batch, is a compare-and-set: the version the
caller read is in the `WHERE`. When one misses, the transaction rolls
back, and the refusal says which of three conditions missed: the task
is gone, another tenant holds it, or it moved past that version.
Narrowed to the tenant, "another tenant holds it" and "nobody does" are
one empty answer, and they are different refusals.

The controls show what the second fence is for: a suite with a
cross-tenant case for the open list and none for the done list stays
green when the done list's `WHERE` loses its tenant
(`docs/runbooks/tenant-isolation.md`).

## Decision

`TasksStoragePostgresImpl._why_not` reads the task's tenant and version
under the system scope, in a transaction of its own, after the
rollback. It reads two columns of one id, and answers `TenantMismatch`
for another tenant's task, or `PreconditionFailed` for a task that is
gone or has moved. It is named, with that reason, among the functions
that pass the system scope in `om/tests/unit/test_session_scope.py`.

## Consequences

The version a refusal names is a report, read after the write failed,
never a value to retry with. The read crosses tenants for one id the
caller already named, and returns nothing of the row but which
condition missed.
