# ADR 1022: The system's size counts the day's tasks

**Status**: accepted (2026-10-14)

## Context

[ADR 0074, The system's size is a tally the sweep keeps](0074-the-systems-size-is-a-tally-the-sweep-keeps.md)
has the sweep count the live orgs and users and the change events of
the last day into one row, which the operator plane reads. Tadas's
first responder also reads how many tasks were made in that day.

## Decision

**The tally counts the tasks created in the day.** `tally_size()`
counts them in a statement of its own (`count_created_since`, on
`core`), between the orgs and users and the change events, and the size
carries the count as `tasks_last_24h`.

**The logins reach the row through the default privileges.** The
runtime and the system logins reach `admin.system_sizes` through the
default privileges `migrate ensure-logins` sets on every role schema,
which runs before every migrate. Tadas's admin chain grants nothing of
its own.

## Consequences

The tasks' statement reads every task, about 50 ns each, since no index
leads with `created_at`, so it grows with every task ever made.
Reading only the day's tasks waits for its trigger: the sweep's
`sweep: counted the system's size in <s>` above 2 s, about 40 million
tasks.
