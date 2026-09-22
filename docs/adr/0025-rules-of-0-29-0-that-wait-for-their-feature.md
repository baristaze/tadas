# ADR 0025: The rules of 0.29.0 that wait for the feature they bind

**Status**: accepted (2026-09-22). Each item names what closes it.

## Context

Guideline v0.29.0 adds rules for features Tadas has only in part, and one
rule whose default Tadas decided against. Every other rule of 0.29.0 holds
in the code, and `make check` runs `arch-check` v0.29.0 on it.

## Decision

These are deviations, each recorded with its reason and its route back:

- **Three database logins (`STO-28`).** The migrations and the processes
  share one login, the master user, so the runtime login owns the tables,
  and the system scope is a setting it can write (ADR 0023). The split
  needs a migration login, a DML-only runtime login, and a system login,
  each with a write-only password. TAZ-54 and TAZ-56 close it together.
- **The release push by an app token (`DEL-38`).** No ruleset restricts
  who may push to `release`, so the workflow token's fast-forward is
  allowed and the workflow dispatches the production deploy itself
  (ADR 0024). The app becomes the one bypass actor the day `release` is
  locked.
- **A kept build that refuses a second write (`DEL-31`).** Production's
  artifacts bucket refuses every direct write and delete under
  `builds/portal/`, the administrator's included, so only replication
  writes there. A changed source object still replicates as a new
  version, because S3 has no condition that refuses a replicated
  overwrite. The recorded digest catches it before any plan, and
  `resolve` refuses it (ADR 0024).
- **The desired count left to autoscaling.** The guideline puts
  `desired_count` in `ignore_changes`. Tadas keeps it out, as the service
  module says: autoscaling is off by default, and with it off an ignored
  count would make the root's number a lie. With autoscaling on, an apply
  returns a scaled service to its floor, and the policy raises it again
  within its cooldown.
- **Queue and outbox alarms (`OPS-15`).** The work queue and the outbox
  are tables, so they have no metric to alarm on until the worker
  publishes one. TAZ-59.
- **The traffic identity between runs (`OPS-19`, the traffic skills).** The
  provisioner stays enabled in a deployed environment, and a run's tenants
  are not removed. TAZ-60, after TAZ-53.
- **A second factor and short-lived tokens for operators (`OPS-07`).**
  TAZ-57.
- **A session's idle lifetime.** A session ends at its absolute lifetime
  (`TADAS_SESSION_LIFETIME_SECONDS`, twelve hours), however long it sat
  unused. An idle lifetime needs a `last_seen_at` written, throttled, by
  every authenticated request, and the check in each of the four places
  a session is verified. TAZ-61.
- **The enqueue permission covering the handler's calls.** Every handler
  today is system maintenance, and no user-caused work kind exists yet.
  TAZ-58 lands with the first one.

The first-operator grant and the named smoke identity stay as ADR 0022
records them (TAZ-53).

## Consequences

- The pin moves to v0.29.0 with these recorded, so a check against the
  text reads them as decisions rather than drift.
- Each ticket that lands removes its line here. The ADR is superseded when
  the last one does.
