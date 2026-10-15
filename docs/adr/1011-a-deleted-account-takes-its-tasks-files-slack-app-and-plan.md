# ADR 1011: A deleted account takes its tasks, files, Slack app, and plan

**Status**: accepted (2026-10-14)

## Context

[ADR 0041, An account is deleted at once, and its providers by the queue](0041-an-account-is-deleted-at-once-and-its-providers-by-the-queue.md)
deletes a person at once and their personal org whole, deletes their
user at the identity provider through the queue, and leaves what they
made in a team org to that org.

A Tadas personal org holds tasks, files, a Slack app, and a plan that
may be paid through Stripe. In a team org, the person may hold open
tasks assigned to them.

## Decision

**The personal org goes with everything the product holds there.**
`DELETE_ACCOUNT` deletes the person at the identity provider, cancels
the org's Stripe subscription at once and deletes its customer, removes
the Slack app, and deletes the personal org, in that order. Each step
finds its own work done on a rerun: a user or a customer the provider
no longer holds counts as deleted, and a closed billing account names
neither. Slack's side stays best effort, as every removal of the app
is. Stripe keeps the invoices, as the law asks of it. The sweep's
tenant purge then takes the files (the object before the row), the
tasks, the Slack rows, and the plan.

**In a team org, what the person made stays, and their open tasks go
unassigned.** Their tasks, files, Slack posts, outbox rows, and change
events stay the org's, under their id. The deleting commit asks, in
each org they leave, for `UNASSIGN_TASKS`. The worker runs it under
the person's name, through the update a person makes to clear an
assignee, a page of their open tasks at a time. A per-seat plan's count
follows the membership, as it does on a removal.

**The unassignment is a deviation from CTX-34** (Worker Roles, The Work
Queue): "a role may enqueue a kind only if it may call each of those
operations itself". It runs on the service role whatever role the
person held, and a viewer cannot clear an assignee. The unassignment is
what the deletion does to the org, decided for every account, not a
write the person asks for. The kind's enqueue permission is `WRITE`,
the width of its handler, and no route enqueues it.

## Consequences

The cancel and the delete take Customers and Subscriptions at Write,
which Stripe's runtime key holds
([ADR 0032](0032-two-restricted-stripe-keys.md)), so the deletion asks
no key for more.

While Stripe or Slack is down, or refuses the key, the personal org's
rows wait as they do for the identity provider, and a paid plan keeps
billing until Stripe answers.
