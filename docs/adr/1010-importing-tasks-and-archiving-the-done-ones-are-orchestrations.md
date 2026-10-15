# ADR 1010: Importing tasks and archiving the done ones are orchestrations

**Status**: accepted (2026-10-14)

## Context

[ADR 0039, Long-running work is a record; a guard parks it, a bound fails it](0039-long-running-work-is-a-record-a-guard-parks-and-a-bound-fails.md)
gives work that takes minutes a durable record, whose kinds a product
adds. Two of Tadas's features take minutes, not a request: importing
tasks from a CSV file, and archiving the done tasks nobody changed for
ninety days.

## Decision

**Both are kinds of the record, `task_import` and `task_cleanup`.** The
tasks namespace registers them and steps them in its own storage: the
tasks manager's `imports` delegate steps an import, and its `cleanup`
delegate a cleanup. A step's effect is the tasks an import creates, or
the tasks a cleanup archives.

**The plan's bound parks an import.** Tadas adds the park reason
`plan_limit`, the plan's bound on active tasks. When the next row of an
import would take the org past it, the step creates the rows before it
and parks the record at that row. The bound is a lever an owner lifts,
so it is the guideline's "a quota an operator can raise", never a
failure. Every billing account write that lifts the org's plan (a
payment's delivery, the seed's grant, an operator's grant) lands the
org's `WAKE_PARKED` for `plan_limit` in the account's own commit. A
person resumes a parked import after finishing some tasks
(`POST /v1/tasks/imports/{id}/resume`), or cancels it. A second import
stacks beside the first
([ADR 1002](1002-a-second-import-stacks-beside-the-first.md)).

**The file's limits fail an import.** A file over one megabyte, over
five thousand rows, not text a CSV reader reads, or with no `title`
column, and a file removed before it was read: each fails the record at
once with its reason (`file_too_large`, `too_many_rows`, `not_csv`,
`no_title_column`, `file_gone`), and nothing more is created. A row
that is bad on its own (no title, a date that is not a date, an
assignee who is not a member) is no bound of the file: it is skipped
and named.

**A cleanup's write is conditional.** It archives only a task still
done, not deleted, not archived, and unchanged since the cutoff. A task
reopened or edited between the read and the write is left alone, and a
second run archives nothing more. The cleanup has no guard, so it
never parks: it succeeds, or a defect fails it.

**The day's cleanup is a unique key, not a clock.** The sweep opens an
org's cleanup record for the UTC date, among its standing chores
([ADR 0070](0070-the-sweep-reads-only-the-tenants-with-a-chore-due.md)).
The cutoff is the start of that day less the archive age, so every step
of one day asks the same question, and a task that crosses the age
during the day waits for the next.

**Archived is a column, not a status.** A task keeps `status` done and
gains `archived_at`. It leaves the done list and every list and count
shown by default. It never was an active task, so the plan's count does
not move. It is read by its id, listed at `GET /v1/tasks/archived`, and
restored with `POST /v1/tasks/{id}/restore`, naming the version read:
a restore is one compare-and-set, so it is in the API. Reopening an
archived task restores it too. Its attachments stay, rows and objects:
archiving deletes nothing. The clock is the task's last change, so a
done task someone edits keeps its place for another ninety days, and so
does a restored one. The age is the worker's setting,
`TADAS_TASKS_ARCHIVE_AFTER_DAYS` (90).

**The batches are small.** An import step takes a hundred rows and a
cleanup step five hundred tasks, each one conditional write.

**Each imported task is announced as a created one.** It lands its own
`tasks.task.created`. An imported task posts nothing to Slack, since a
file of a thousand rows is not a thousand messages.

## Consequences

The numbers are illustrative: the file's megabyte and five thousand
rows, the batches of a hundred and five hundred, and the ninety days.

An import that parks keeps what it made, and the tasks page shows it
with its Resume. A cleanup never waits on a person.
