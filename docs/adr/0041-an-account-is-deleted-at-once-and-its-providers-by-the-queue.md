# ADR 0041: An account is deleted at once, and its providers by the queue

**Status**: accepted (2026-09-26)

## Context

A person asks to delete their account. It is a hard delete: the person
is gone now, and gone from the backups within seven days, the
database's backup retention. There is no grace period and no undo, and
signing up again with the same address makes a new person. Their
personal org goes whole: tasks, files (the object before the row), the
Slack app, and the plan. A Stripe subscription is canceled at once and
the Stripe customer deleted; Stripe keeps the invoices, as the law asks
of it. Their user at the identity provider goes too, or a sign-in there
would carry on as if nothing happened. What they made in a team org
stays the org's, under their id only: tasks, events, outbox rows,
files, Slack posts. Their open tasks there go unassigned. A last owner
of a team org is refused, and so is an operator, who leaves the
allowlist first. A last owner has two ways out in Settings, so no
account waits on an operator
([ADR 0042](0042-an-owner-deletes-a-team-org-closed-at-once-and-its-providers-by-the-queue.md)).

STO-32 (The Storage Layer, Database Roles) makes the sweep's purge the
one hard delete, save this one: a person's account may go at once, in
one atomic write that removes their identity and every user,
membership, and credential it holds. A soft delete would keep a user
row's email and name for the retention, the one thing the person asked
not to happen.

## Decision

**The account goes in one commit, as a hard delete.** `POST
/v1/me/deletion`, from a session only, carries the account's email as
the person typed it. The tenancy manager checks it and the two
refusals: `409 last_owner`, whose envelope names each org by id, name,
and slug, and `403 operator_role_held`. Then one named atomic write,
`TenancyStorageInterface.delete_person`, deletes:

- the identity, with its second factor;
- every user it is, in any org, with their memberships, sessions, API
  keys, and socket tickets;
- its sign-ins and operator tokens, and the sign-in delay of its
  address;
- every invitation sent to that address or accepted by one of its
  users.

It is a cross-tenant method on the system scope, enumerated with the
others. Under a row lock it counts the owners of each team org the
person owns, and refuses when one would be left with none, so two
owners who leave at once cannot both go. The personal fields are the
named ones the guideline asks for, so the delete is a list, not a hunt.

**Every live credential is announced as revoked.** The same commit
lands `tenancy.session.revoked` and `tenancy.api_key.deleted` for each
live one, and `tenancy.user.deleted` in each org the person leaves, so
every socket they hold closes. Every payload carries ids only.

**A team org keeps the footprint, by id.** Nothing else the person made
there is touched. The same commit asks, in each org they leave, for
`UNASSIGN_TASKS`. The worker runs it under the person's name, through
the update a person makes to clear an assignee, a page of their open
tasks at a time. It runs on the service role whatever role the person
held, and a viewer cannot clear an assignee: this is the deviation from
CTX-34 (Worker Roles, The Work Queue): "a role may enqueue a kind only
if it may call each of those operations itself". The
unassignment is what the deletion does to the org, decided for every
account, and not a write the person asks for; the kind's enqueue
permission is `WRITE`, the width of its handler, and no route enqueues
it. A per-seat plan's count follows the membership, as it does on a
removal. A client names an id it cannot resolve as a former member.

**The providers go through the queue, after the local delete.** The
same commit asks for `DELETE_ACCOUNT` in the personal org, with the
person's user id at the identity provider in its payload, since the
identity that held it is gone. The worker deletes that user, cancels
the subscription and deletes the customer, removes the Slack app, and
deletes the personal org, in that order. Each step finds its own work
done on a rerun: a user or a customer the provider no longer holds
counts as deleted, and a closed billing account names neither. A
provider out of reach, or one that refuses the process's own key, parks
the item for a minute without spending an attempt. A provider that
refuses the call itself fails the item at once
([ADR 0051](0051-a-refused-key-is-unavailable-a-refused-request-is-refused.md)).
Slack's side stays best effort, as every removal of the app is. Stripe's
runtime key already has Customers and Subscriptions at Write, which
cover the cancel and the delete.

**The personal org goes through the deletion that exists.** The last
step soft-deletes the org and announces it.
`tenancy.rules.past_retention` counts a deleted personal org as past
its retention at once, since it is deleted only with its person. So the
sweep's next pass runs the tenant purge every namespace already has
(files object first, then row; tasks; the Slack rows; the plan; the
events), and there is no second deletion mechanism. The org row stays
as the record, as every deleted org's does. In the same write, a
personal org's name and slug, made from its person's name, become
"Deleted account" and `deleted-<id>`.

**The browser ends the provider's session too.** The answer carries
`provider_logout_url`, as a sign-out's does, and the portal goes there
on its way to `/signed-out`.

## Consequences

The local delete is the promise, kept at once: from the answer on,
nobody signs in as the person and no credential of theirs works. The
org waits for the providers, because a claim refuses an item of a
deleted org.

While a provider is down, or refuses the key, the personal org's rows
wait, out of reach of their person; anyone else they added to the org
keeps it until then. A provider that refuses the call fails the item
for good. Once the cause is fixed, a person with a `write` operator
entry sends the item back (`tadas-ops work requeue`), and the org's
stream names who did.

A person who signs in through the provider before the item deletes
their user there is a new person in Tadas. The item may then delete the
provider's user that new person signed in as. Their next sign-in makes
one again, and Tadas links it by the verified address.

The WorkOS organization a personal org gets when its owner invites
someone to it stays at WorkOS under the org's id.

The deletion's outbox rows and work items stay for their own retention.
They carry ids and the provider's user id, never a name or an address.
