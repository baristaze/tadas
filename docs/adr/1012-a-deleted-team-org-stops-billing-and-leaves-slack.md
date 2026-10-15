# ADR 1012: A deleted team org stops billing and leaves Slack

**Status**: accepted (2026-10-14)

## Context

[ADR 0042, An owner deletes a team org, closed at once, and its providers by the queue](0042-an-owner-deletes-a-team-org-closed-at-once-and-its-providers-by-the-queue.md)
closes a team org at once and deletes its organization at the identity
provider through the queue. A Tadas team org also holds a plan, which
Stripe may bill, and may have its Slack app installed. An owner who
deletes the org means the plan stops billing and the app leaves too.

## Decision

`DELETE_ORG` deletes the provider organization, cancels the org's
subscription and deletes its customer at Stripe, removes the Slack app,
and deletes the org, in that order. Each step finds its own work done
on a rerun. Slack's side stays best effort.

An operator's deletion takes the same path, so an org deleted on the
operator plane stops billing and leaves its Slack workspace too.

The owner lands in their personal org, and the portal opens its task
list there.

## Consequences

While Stripe is down, or refuses the key, the org waits, empty, and
its subscription keeps billing until Stripe answers.

Stripe's runtime key already has Customers and Subscriptions at Write
([ADR 0032](0032-two-restricted-stripe-keys.md)). No key gains a
permission.
