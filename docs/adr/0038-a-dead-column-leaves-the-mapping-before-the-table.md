# ADR 0038: A dead column leaves the mapping one release before it leaves the table

**Status**: accepted (2026-09-25). Supersedes when the dead columns are
dropped in [ADR 0026](0026-what-0-31-0-leaves-as-a-choice.md) (the
last paragraph), [ADR 0028](0028-sign-in-is-the-identity-providers.md)
("Tadas keeps no password"), and
[ADR 0034](0034-a-task-is-due-on-a-date.md) (the contract half); the
rest of each record stands. The first release takes
`identities.password_hash`, `identities.failed_sign_ins`,
`identities.last_failed_sign_in_at`, and `tasks.remind_at` out of the
mapping, stops writing `remind_at`, and clears the password hashes with
the code-linked Slack channel's two tables. The second step is done
(2026-09-25): migration 202609290000 drops the four columns.

## Context

A column moves by expand and contract. A migration runs before the
services roll, so the previous release serves the new schema for the
minutes of the roll, and again after a fast rollback. A column may
leave the table only when no statement of the previous release names
it.

Taking a column out of every read is not enough. SQLAlchemy's mapper
names every mapped column in the insert it emits: a column the object
has no value for is sent as `NULL`, and one with a server default is
read back in the insert's `RETURNING`. A deferred column is still
mapped. So the previous release names it in every insert it makes, and
a drop under it fails every such insert for the minutes of the roll,
and for good if the circuit breaker rolls the deploy back.

## Decision

**A dead column leaves in two releases.** The first takes it out of the
mapping and keeps it in the table: the column is declared in the
table's `__table_args__` and named in the mapper's
`exclude_properties`. No statement names it, and the schema check still
compares it. The second release drops it with a migration, and the two
lines go.

**The data goes as early as it can.** A value nothing reads is cleared
in the first release when it is a secret, such as a hash. Clearing it
needs no drop, and a secret is better gone a release sooner.

**The proof is the previous release's own tests.** Before a contract
lands, the previous release runs its integration tests against the
contracted schema. A column any of them names stays one more release.

## Consequences

A column's removal takes two pull requests in two releases. The first
changes code and mapping only; the second is a migration that drops.

Deferring a column is not a step of its own. It keeps the column out of
the reads, and every insert still names it.

After a fast rollback to the previous release, that release may write
the column again. Nothing of the current release reads it.
