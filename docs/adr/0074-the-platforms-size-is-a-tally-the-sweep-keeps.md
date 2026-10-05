# ADR 0074: The platform's size is a tally the sweep keeps

**Status**: accepted (2026-09-26)

## Context

STO-21 keeps analytics across tenants out of the request path of every
role: a report reads a mirror or a periodic copy, never a role the
application writes to.

`GET /v1/admin/size` answers the platform's size: the live orgs, the
live users, the tasks created in the last day, and the events produced
in it. The first responder reads it before escalating an alarm
(`tadas-ops size`), so it is read when something is already wrong.
Counted in the handler, it is three statements across every tenant, two
on `core` and one on `activity`, and each grows with the platform, the
tasks' with every task ever made.

## Decision

**The sweep counts, the handler reads.** The operator manager's
`tally_size()` is the sweep's count: the live orgs and users in one
statement (`count_orgs_and_users`, on `core`), the tasks created in the
day (`count_created_since`, on `core`), the events produced in the day
(`count_since`, on `activity`), then one write of the result.
It takes no context, since it counts for no tenant and no principal,
and it is listed with the other principal-less methods. `size` reads
the result and counts nothing.

**The tally lives in the `admin` role.** The guideline gives `admin`
"the operator plane's own state, global rows", and STO-21 keeps a report
off the roles the application writes to. The size is the operator
plane's own, and it is one global row, `admin.platform_sizes`, keyed by
`EMPTY_UUID`, the platform's reference (OM-13). It is `system`-scoped:
no tenant, no policy. The runtime and the system logins reach it through
the default privileges `migrate ensure-logins` sets on every role schema,
which runs before every migrate. The row is a persisted read model,
derived and rebuilt by the next count. It is a row, never a cache
entry: the cache is best effort, and a flush would lose the size until
the next count. It is one row, never a row per count: a history needs a
purge, and nothing reads one.

**Once every five minutes, not every pass.** The counts cover a day, so
a count five minutes old is off by about a three-hundredth of its
window at most, and the tenants and the users move slower than that.
The interval is a setting, `TADAS_WORKER_TALLY_SECONDS` (300). Counting
on every pass, every thirty seconds, would add the count's cost to
every idle pass.

Each worker keeps its own clock, in memory, and counts on its first
pass, so two workers count twice an interval. Reading the row's age on
every pass would coordinate them, at the cost of a read on every pass
of every worker to save one count every five minutes. The write takes
the newer count: a count older than the row's does not replace it, so
two workers that count at once leave the later one.

**Whatever the budget.** The count runs after the purges and before the
gauges, whether or not the pass's budget is spent, as the gauges do. A
backlog that spends every budget is exactly when the first responder
reads the size.

**The answer says how old it is.** The read model and
`PlatformSizeView` carry `counted_at`, and the window is the day before
it (`since`). `tadas-ops size` prints how long ago the worker counted.
Before the first count the route is `404`: the size does not exist yet.
It is never `503`, which the gateway logs as a failure with a stack and
presents as "internal error"; a fresh environment is not failing.

## Consequences

`GET /v1/admin/size` reads two rows in two transactions: the operator's
credential on `core`, and the tally on `admin`. It reads nothing across
tenants.

The size is up to five minutes and one pass old. A worker that stops
counting shows as a `counted_at` that keeps aging, which the ops skills
read as a finding.

The count still grows with the platform. The tasks' statement reads
every task, about 50 ns each. It runs off every request path, once an
interval, on the system login's pool. The worker logs `sweep: counted
the platform's size in <s>`, which is where a count that grows too slow
shows first. Reading only the day's tasks waits for its trigger: that
line above 2 s, about 40 million tasks.
