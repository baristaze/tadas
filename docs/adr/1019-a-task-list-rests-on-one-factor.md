# ADR 1019: A task list rests on one factor

**Status**: accepted (2026-10-14)

## Context

[ADR 0063, Auth sessions last weeks](0063-auth-sessions-last-weeks.md)
sets an auth session's lifetimes at weeks, the bounds NIST SP 800-63B
allows at AAL1, for an auth session that rests on one factor. Whether
one factor is enough depends on what an auth session reaches.

## Decision

Tadas takes those lifetimes as they are: an auth session reaches a
team's work, not its money or its secrets.

- A task list holds titles, notes, dates, assignees, and attached
  files.
- Card details go to Stripe and never reach Tadas: a payment starts in
  Stripe's checkout, and a card changes in Stripe's portal.
- Slack's bot token is the org's own secret, behind `SecretsInterface`
  ([ADR 0035](0035-slack-is-a-distributed-app-over-http-installed-per-org.md)),
  and it is never on the wire.

## Consequences

A feature that would put money or a secret a person reads behind an
auth session reopens these lifetimes, and asks whether one factor is
still enough.
