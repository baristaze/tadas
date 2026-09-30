# ADR 0039: Long-running work is a record; a guard parks it, a bound fails it

**Status**: accepted (2026-09-25)

## Context

Two features take minutes, not a request: importing tasks from a CSV
file, and archiving the done tasks nobody changed for ninety days. The
guideline's "Long-Running Orchestrations" says what such work is: "a
durable record advanced by stateless workers", "a row with a status and
a cursor", claimed through a work item that is "a separate row from the
record it advances". It names three outcomes, "It succeeds, it fails, or
it parks", and the rule between the last two: "A guard parks, a bound
fails. A safety check leaves the work resumable; only a real limit
terminates it." "Maintenance Without a Scheduler" adds that the sweep
"open[s] the next period of a record kept per period".

## Decision

**One mechanism, a namespace of its own.** `om/orchestrations` holds
the record (`Orchestration`: a kind, its input, a period, a status, a
cursor, a total, what the steps applied and skipped, the first twenty
skipped rows with a reason, a park reason, a fail reason, and a
version), its storage in Postgres and in memory under the tenant fence,
and its manager: `start`, `get`, `get_recent`, `resume`, `wake`,
`fail`, and the purges. Both features are kinds of it, `task_import`
and `task_cleanup`. Each declares an input shape in
`ORCHESTRATION_INPUTS` and a step in the namespace whose rows it
changes: the tasks manager steps both.

**A step is one commit.** A step's effect (the tasks an import creates,
the tasks a cleanup archives), the record's next cursor, and the work
row that asks for the next step land in one transaction. The record
rides it as a companion statement (`Step`), the way an outbox row
rides a core write: the namespace's storage runs the
record's compare-and-set on its version in its own transaction, and
rolls back the effect with it when the record moved. So a worker that
dies leaves the record at its last committed step. A stale worker's
step, one that held an item past its lease, lands nothing. The count of
what was applied grows in that commit by the rows the effect wrote.

**A step runs twice and does once.** What a step makes takes an id
derived from the record and the row (`base.derived_id`), so a second
run meets its rows already there. The cleanup's write is conditional:
it archives only a task still done, not deleted, not archived, and
unchanged since the cutoff, so a task reopened or edited between the
read and the write is left alone, and a second run archives nothing
more.

**A guard parks, a bound fails.** A limit that can clear parks the
record at its cursor, in the step's own commit, and keeps what it made.
The one park reason is `plan_limit`, the plan's active tasks: when the
next row of an import would take the org past its plan's bound, the
step creates the rows before it, and parks the record at that row. The
bound is a lever an owner lifts, so it is the guideline's "a quota an
operator can raise", never a failure. The work item that clears a
reason is `WAKE_PARKED`, which resumes the org's records parked for it,
two seconds apart: every billing account write that lifts the org's
plan (a payment's delivery, the seed's grant, an operator's grant)
lands one in the account's own commit. A person may resume a parked
record too (`resume`), with Resume
(`POST /v1/tasks/imports/{id}/resume`) after finishing some tasks. A
woken record is not trusted: its next step asks its guard again. A bound
of the input fails the record with its reason, which a product adds
beside `defect`. The park is the record's status, not a
deferred work item, so only the record says why it waits.

The import's input has real limits: a file over one megabyte, over five
thousand rows, not text a CSV reader reads, or with no `title` column,
and a file removed before it was read. Each fails the record at once
with its reason, and nothing more is created. A row that is bad on its
own (no title, a date that is not a date, an assignee who is not a
member) is not a bound of the file: it is skipped and named.

**Everything else transient is the work queue's retry.** A database or
a store that does not answer makes the step raise, and the queue
retries the item with its growing delay, from the cursor the last
commit left. On the item's last attempt the handler fails the record as
`defect` instead of raising, so no record waits on work that will never
come. The storage layer's statement deadline bounds every batch, and a
batch is small (a hundred rows, five hundred tasks), each one
conditional write. The cleanup has no guard of its own, so it never
parks: it succeeds, or a defect fails it.

**A record kept per period has a unique key.** The org, the kind, and
the period are unique (`uq_orchestrations_org_id_kind_period`), so the
first start in a period opens its record and every later start answers
it as stored. A sweep can open the period's record on every pass with
no scheduler, no leader, and no lock.

**The day's cleanup is a unique key, not a clock.** Every sweep asks
each org whether it has a done task unchanged for the archive age and,
if so, opens its cleanup record for the UTC date. The cutoff is fixed
when the record opens, so every step of one day asks the same question;
a task that crosses the age during the day waits for tomorrow.

**Archived is a column, not a status.** A task keeps `status` done and
gains `archived_at`. It leaves the done list and every list and count
shown by default; it never was an active task, so the plan's count does
not move. It is read by its id, listed at `GET /v1/tasks/archived`, and
restored with `POST /v1/tasks/{id}/restore`, naming the version read:
restoring is one compare-and-set, so it is in the API. Reopening an
archived task restores it too. Its attachments stay, rows and objects;
archiving deletes nothing. The clock is the task's last change: a done
task someone edits keeps its place for another ninety days, and so does
a restored one. The age is the worker's setting
(`TADAS_TASKS_ARCHIVE_AFTER_DAYS`, 90), illustrative like the plans'
numbers.

**Progress is pushed.** Every write of a record lands
`orchestrations.orchestration.<created|updated>`, with the record's id
and the version the write left
([ADR 0061](0061-a-task-push-names-the-version-it-wrote.md)). A client
follows a record on the realtime channel and reads it on each push it
does not already hold. Nothing polls. Each imported task lands its own
`tasks.task.created`, as a created task does; an imported task posts
nothing to Slack, since a file of a thousand rows is not a thousand
messages.

## Consequences

The next long job is a kind, its input shape, a step in the namespace
that owns its rows, and, where it has a guard, a park reason and the
event that clears it.

One org's large job takes one step at a time, a work item each, so it
shares the worker's slots with every other org's work. A lane of its
own for a heavy kind is the guideline's answer when bulk work starves
its neighbours.

Every transition counts under the subsystem `orchestrations`, labelled
by kind and outcome, and a `defect` is an `ERROR` line naming the
record and its org.

A settled record is purged thirty days later; a parked or running one
is kept. A record whose last attempt could not write its failure stays
running until its org is purged, and the work queue's dead letter
names it.

The numbers are illustrative: the file's megabyte and five thousand
rows, the batches of a hundred and five hundred, the twenty rows named,
the ninety days.
