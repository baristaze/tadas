# ADR 0009: Tasks carry a version, and every write names the one it read

**Status**: accepted (2026-09-19)

## Context

The guideline (Shape of an Operation) makes optimistic concurrency
opt-in: last writer wins by default, and an entity whose concurrent
edits matter carries a `version`, the copy increments it, and the write
is a compare-and-set that refuses a row that moved.

A task's concurrent edits matter. A task is edited from two windows and
two terminals at once, by design: the portal's drag reorder, the CLI's
`done` and `rm`, and the realtime demo all write the same rows from
different places. The manager's copy on update starts from the stored
row, which keeps the provenance honest, but a write with no condition
lands over whatever another writer landed between the read and the
write: an edit that races a delete brings the task back.

## Decision

`Task` carries `version`. The manager's copy increments it on every
write of a task, and the storage write is a compare-and-set: `WHERE
version = :expected` in one statement in Postgres, the same check and
write under the lock in the memory impl. A row at another version, or
gone, raises `PreconditionFailed`, 412 `precondition_failed`. The update
never inserts a missing row; the create primitive is the only way in.

The expected version comes from the caller and never from a row read
inside the update. On the wire, `TaskView` shows `version`, and every
write names the one the caller read. A PATCH and a DELETE name it in
`If-Match`, as an entity tag, which the gateway parses; a move and a
restore name it in `expected_version`. A write that names neither is
422 `validation_failed`.

`Task` declares `MANAGER_OWNED_FIELDS` (`rank`, `version`, and the
reminder's and the archive's marks), and the copy on update excludes
them beside `PROVENANCE_FIELDS`, so an edit cannot place a task or set
its version.

The clients send the version they hold: the portal from the task in its
query cache, the CLI from the task it reads before every verb, the
Python client as a required argument.

## Consequences

A client that writes a task must have read it first and must read again
after a 412; there is no write that wins by default. The portal reloads
on 412, and the CLI says a 412 in words.

Every other table stays at the guideline's default until its concurrent
edits matter, and the next such table follows this shape: the column,
the compare-and-set in both impls, the version on the view and on every
write.
