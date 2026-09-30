# ADR 0070: The sweep reads only the tenants with a chore due

**Status**: accepted (2026-09-26)

## Context

The sweep keeps two standing chores per tenant: the day's cleanup, which
archives the done tasks past the archive age, and the respace of a rank
that grew long. The purges of rows past their retention run once a pass
across tenants
([ADR 0045](0045-retention-purges-run-once-a-pass-across-tenants.md)),
so the chores are what a living tenant can cost a pass.

A chore that opens with a read of its tenant costs every tenant a
transaction of three round trips a pass, and almost every answer is no.
Counted at the driver with the tools of the `audit-database-calls`
skill, on the audit seed (one heavy tenant, the rest personal orgs), a
pass that runs both chores in every tenant of the ring costs:

| Tenants | Round trips | Transactions | Wall time |
|---|---|---|---|
| 1,005, idle | 6,113 | 2,033 | 2.53 to 2.57 s |
| 5,005, idle | 30,173 | 10,053 | 15.4 to 16.5 s |
| 5,005, 1,000 of them with a chore due | 41,073 | 13,353 | 20.05 s, the budget, and the pass does not reach every tenant |

That is 65 + 6T + 3⌈T/200⌉ round trips over T tenants, the system
scope counted as one, every thirty seconds: about 200 a second at 1,000
tenants and 1,000 a second at 5,000, almost all of them answering
"nothing".

## Decision

**One read a pass, across tenants, names the tenants with a chore
due.** `TasksStorageInterface.read_tenants_with_chores(archivable_before,
after, limit)` is a named read in the system scope. Like the other
methods that take no tenant, it is listed with its reason. It is one
statement with two arms, each on a partial index that holds only the
rows it may find:

- the done tasks not archived, on
  `ix_tasks_updated_at_org_id_done_unarchived (updated_at, org_id)
  WHERE status = 'done' AND archived_at IS NULL AND deleted_at IS
  NULL`. The day's cut is a range of it, so only the archivable tasks
  are read. The read names the status as the same literal, so the
  predicate is proven by any plan, as the files purge does
  ([ADR 0056](0056-purges-across-tenants-plan-with-their-values.md));
- the open tasks whose rank grew long, on `ix_tasks_org_id_rank_long`,
  the index the respace reads.

It returns each tenant once, in id order, at most `limit`, after
`after`. It is planned with its values, as the purges across tenants
are (ADR 0056). A generic plan knows neither the cut nor the tenant a
page starts after, and on the integration suite's data it walks the
tenant-led index of every unarchived task instead. The `SET LOCAL`
costs one round trip a pass.

It is one read for both chores, never a read per chore: the one read
runs both chores in each tenant it names, so a tenant due for one pays
the other's probe, three round trips, and only in a tenant with work to
do. And it reads its own partial index, never a skip scan of the
tenant-led done-shelf index
(`ix_tasks_org_id_status_updated_at_id_unarchived`), which descends
once per tenant, a cost that grows with every org made.

**The day's cut holds all day.** The day's cleanup takes the done tasks
that were past the archive age when the UTC day began
(`tasks.rules.archive_cutoff`), and the read uses the same cut. Once
the day's record has run, the org has nothing archivable until the next
day begins. A task that turns 90 during a day is archived the next day.
A cut taken at the moment the record opens would name an org on every
pass for the rest of the day, for a task that crossed the line after
its record opened.

**The chores are a phase of the pass, before the ring.** The loop reads
a page of the tenants with a chore due (`LoopOptions.chore_batch`,
1,000), and runs each tenant's chores once, under the service context
the pass listed for it. Past the budget it takes no new tenant, but
always one. The next pass reads on from the last tenant this one ran,
and a page that came back short and ran whole sends the next pass back
to the first. So more than a page of tenants with a chore due is a page
a pass, and each is reached within ⌈D/1,000⌉ + 1 passes. A tenant the
read names that has no context in the pass, purged or made since the
list was read, waits for the next pass.

The ring keeps the purge of a tenant past its retention and the mark of
a tenant purged. A chore that fails holds no tenant's mark back: a
tenant with no task left is named by no read. The ring lists every org:
the list is three round trips per 200 tenants, the one term of an idle
pass that grows with tenants.

**The index earns its writes.** It takes an entry only from a write
that leaves a task done, not archived, and not deleted: a completion, an
edit of a done task, a restore, and one per task of a bulk completion.
A write that leaves a task open, archived, or deleted writes it none, so
a create, a move, a respace, a reopen, and the cleanup's archive cost it
nothing. Every write to a task changes `updated_at`, which two other
indexes hold, so none of those writes is a HOT update with or without
it. The index adds one B-tree insert of a timestamp and a uuid to a
write that already updates several. It holds each tenant's Done shelf,
which the cleanup keeps to 90 days: 1.5 MB for the 25,000 such tasks of
the 5,000-tenant seed, beside a table of 67 MB.

## Consequences

The same flows, over the same seeds, with the chores in every tenant of
the ring and with the one read:

| Pass | Chores in every tenant | The one read |
|---|---|---|
| 1,005 tenants, idle | 6,113 round trips, 2,033 transactions, 2.53 s | 87 round trips, 24 transactions, 0.06 s |
| 1,005 tenants, 100 with a chore due | 8,013, 2,633, 3.39 s | 2,587, 824, 1.05 s |
| 5,005 tenants, idle | 30,173, 10,053, 15.4 to 16.5 s | 147, 44, 0.16 to 0.22 s |
| 5,005 tenants, 100 with a chore due | 32,073, 10,653, 18.2 s | 2,647, 844, 1.24 s |
| 5,005 tenants, 1,000 with a chore due | 41,073, 13,353, 20.05 s, unfinished | 23,867, 7,644, 10.98 s |

An idle pass is 69 + 3⌈T/200⌉ round trips in 18 + ⌈T/200⌉
transactions: the steps across tenants, and the org list the ring
needs. A tenant with a chore due costs 23 to 25 round trips and about
10.7 ms. The read takes 0.13 ms when nothing is due and 1.2 ms naming
880 tenants (`EXPLAIN ANALYZE` on the 5,000-tenant seed).

**The chores run one tenant after another, until a trigger fires.**

- An idle pass grows by about 25 µs a tenant, for the org list and the
  ring in memory: 0.06 s at 1,000 tenants and 0.2 s at 5,000. It nears
  16 s, four fifths of the budget, around 600,000 tenants.
- A pass takes at most a page of tenants with a chore due, about 11 s
  for a full page. A full page happens at the start of a UTC day, when
  each org with a done task that turned 90 the day before is due. It
  drains at a page a pass, a pass every 41 s or so (the pass, then the
  30 s interval): about 90,000 orgs an hour. A pass with a full
  page nears 16 s around 200,000 tenants, or once a tenant's chores
  cost over 15 ms.

The trigger: the pass duration's p95 over a day reaches 16 s outside
the first hour of the UTC day, or the day's first burst of tenants with
a chore due takes more than an hour to drain, about 90,000 due orgs.
When it fires, the calls come down before any chore runs in parallel.
The read can say which chore is due in each tenant, so a due tenant
skips the probe of the chore not due in it and the cleanup's own probe:
up to 6 of its 23 round trips. The cleanup's read of the day's record
can fold into its insert: 3 more.
