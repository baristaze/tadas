# ADR 0023: The row-level security bypass is a setting, for now

**Status**: accepted (2026-09-22), amended (2026-09-22). A deviation
for one more release. [TAZ-54](https://linear.app/taze/issue/TAZ-54)
and [TAZ-56](https://linear.app/taze/issue/TAZ-56) split the logins
(release A, below); release B removes the master from the clause and
closes this record.

## Context

Row-level security is the second tenant fence
([ADR 0016](0016-row-level-security-is-the-second-fence.md)). Every
`tenant_fence` policy admits a row whose `org_id` equals
`current_setting('app.org_id')`. It also admits every row when that
setting is the system scope, the all-zero UUID, which is how the sweep
and the relay read across tenants.

This bypass is a setting. The runtime login can write it in any
session with
`SET app.org_id = '00000000-0000-0000-0000-000000000000'`. The first
fence is the code, where every storage method takes the tenant and the
funnel sets the scope per transaction. So the second fence holds
against a mistake in the code, but not against SQL injected past it:
an injected `SET` lifts the second fence as well.

## Decision

The bypass stays a setting until one login is split into several.
There are three logins to split out: a migration login that owns the
schema (TAZ-54), a sweeper login for the cross-tenant paths (TAZ-56),
and the runtime login. Once the sweeper login exists, the bypass clause
moves into policies declared `TO` it, and the runtime login's policies
carry no bypass.

It is not done here because it changes every policy migration, the
database URL of each role, the migration task's secret, and the
integration engines, in one change. It is also one design with TAZ-54's
owner and DML split.

## Consequences

- Tenant isolation against injection rests on the first fence alone:
  every query is parameterised through SQLAlchemy, and no statement is
  built from a string.
- The negative-control test and the policy check test stay as they are.
  They prove the fence against a missing predicate, which is the case
  it covers today.

## Amended: release A

The logins are split. Three logins reach the database, and none is a
superuser or carries BYPASSRLS:

- `tadas_migration` owns every role schema, table, sequence, and
  version table, and runs the migrations.
- `tadas_runtime` is every request's connection. It owns nothing and
  holds DML only.
- `tadas_system` is its twin for the system scope, on a pool of its
  own. The funnel opens the system scope on it and every other scope
  on the runtime login.

`tadas-api migrate ensure-logins` makes them, run as the master by the
migrate task before `migrate --all`.

The bypass is no longer a setting alone. The system-scope clause of
every `tenant_fence` policy is now:

```sql
current_setting('app.org_id', true) = '00000000-0000-0000-0000-000000000000'
AND current_user IN ('tadas_system', 'tadas')
```

The runtime login naming the system scope reads nothing, so an injected
`SET` on a request's connection no longer lifts the second fence.

`tadas`, the master, stays in the clause for release A only. It is the
login every task of the release before connects as, and those tasks keep
serving while release A rolls out beside them. Until release B, the
master's password can still read across tenants through the setting.
That login is held by the migrate task alone once release A is live.

Release B drops `'tadas'` from the clause, in a migration of its own,
after every task of the release before has stopped. This record closes
with it. [ADR 0026](0026-what-0-31-0-leaves-as-a-choice.md) lists what
else release B removes.
