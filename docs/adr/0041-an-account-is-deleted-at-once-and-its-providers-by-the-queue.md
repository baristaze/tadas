# ADR 0041: An account is deleted at once, and its providers by the queue

**Status**: accepted (2026-09-26). A deviation from STO-32.

## Context

A person asks to delete their account. What that means is decided:

- It is a hard delete. The person is gone now, and gone from the
  backups within seven days, the database's backup retention
  (`backup_retention_days`). There is no grace period and no undo.
  Signing up again with the same address makes a new person.
- It is refused while the person is the last owner of a team org, and
  the refusal names those orgs. It is refused for an operator, who
  loses the operator role first.
- What they made in a team org stays the org's, under their id only:
  tasks, events, outbox rows, files, Slack posts. Their user and their
  membership go, and their open tasks there go unassigned.
- Their personal org is deleted whole: tasks, files (the object before
  the row), the Slack app, and the plan. A Stripe subscription is
  canceled at once and the Stripe customer deleted. Stripe keeps the
  invoices, as the law asks of it.
- The WorkOS user is deleted too, or a sign-in there would carry on as
  if nothing happened. Every session, API key, and operator token ends
  in the same act.

The guideline says it otherwise (STO-32, The Storage Layer, Database
Roles): "A soft-deleted row is purged by the maintenance sweep after its
entity's retention period, and the purge is the one hard delete.
Personal data lives in named fields, so erasing a person is a sweep over
a list, not a hunt."

Tadas has both halves of that already. Removing a member soft-deletes
their user and ends their membership; the sweep purges both thirty days
later. An operator's deletion of an org soft-deletes it; thirty days
later the sweep purges every row of it in every namespace, and marks it
purged once nothing is left. A user row holds the person's email and
name, so a soft delete keeps both for thirty days. The decision asks for
none.

## Decision

**The account goes in one commit, as a hard delete.** `POST
/v1/me/deletion`, from a session only, carries the account's email as
the person typed it. The tenancy manager checks it, and the two
refusals: `409 last_owner`, whose envelope names each org by id, name,
and slug, and `403 operator_role_held`. Then one named atomic write,
`TenancyStorageInterface.delete_person`, deletes the identity (its
second factor with it), every user it is in any org, removed ones too,
with their memberships, sessions, API keys, and socket tickets, its
sign-ins and operator tokens, and the sign-in delay of its address. It
is a cross-tenant method on the system scope, enumerated with the
others, and every statement in it names the person and the orgs their
users are in.

This is the deviation: a hard delete outside the sweep. A soft delete
would keep the email and the name for the retention, which is the one
thing the person asked not to happen. The personal fields are the named
ones the guideline asks for, so the delete is still a list, not a hunt.

**Every live credential is announced as revoked.** The same commit lands
`tenancy.session.revoked` and `tenancy.api_key.deleted` for each one
that was live, and `tenancy.user.deleted` in each org the person leaves,
so every socket they hold closes. Every payload carries ids only.

**A team org keeps the footprint, by id.** Nothing the person made
there is touched. The same commit asks, in each org they leave, for
`UNASSIGN_TASKS`. The worker runs it as the person, through the update a
person makes to clear an assignee, a page of their open tasks at a
time. A per-seat plan's count follows the membership, as it does on a
removal. The portal names an id it cannot resolve "Former member". No
row is rewritten for it.

**The personal org goes through the deletion that exists.** The last
step of `DELETE_ACCOUNT` soft-deletes the org, as an operator's deletion
does, and announces it. The one change is the retention:
`tenancy.rules.past_retention` counts a deleted personal org as past it
at once, since a personal org is deleted only with its person. So the
sweep's next pass runs the tenant purge every namespace already has:
files object first, then row; tasks; the Slack rows; the plan; the
events. The pass after marks it purged. There is no second deletion
mechanism. The org row stays as the record, as every deleted org's
does, and a personal org's name and slug, made from its person's name,
are replaced in the same write by "Deleted account" and
`deleted-<id>`.

**The providers go through the queue, after the local delete.** The
commit also asks for `DELETE_ACCOUNT` in the personal org, with the
person's WorkOS user id in its payload, since the identity that held it
is gone. The worker deletes the WorkOS user, cancels the subscription
and deletes the customer, removes the Slack app, and deletes the org,
in that order. Each step finds its own work done on a rerun: a user or
a customer the provider no longer holds is deleted already, and a
closed billing account names neither. A provider that cannot be reached
parks the item for a minute without spending an attempt: a guard
parks, a bound fails. A provider that refuses fails the item, which
retries and ends as a failed item an operator reads. Slack's side stays
best effort, as every removal of the app is.

The org waits for the providers because the queue would not run the
work otherwise: a claim refuses an item of a deleted org. The local
delete is the promise, and it is kept at once: from the moment the
request answers, nobody signs in as the person and no credential of
theirs works.

**The worker holds the WorkOS key.** It deletes the WorkOS user with the
Tadas App's own key, the one the API holds. Deleting a user is a
management call like the invitations the key already makes. Stripe's
runtime key already has Customers and Subscriptions at Write, which
cover the cancel and the delete.

**The browser ends the provider's session too.** The answer carries the
provider's logout address, as a sign-out's does, and the portal goes
there on its way to `/signed-out`, which says the account is gone.

## Consequences

While a provider is down, the personal org's rows wait for it, out of
reach of their person; anyone else they had added to the org keeps it
until then. A provider that keeps refusing (a key without a permission)
fails the item for good, and the org stays with it. Running the item
again once the key is fixed is by hand today.

A person who signs in through WorkOS before the item deletes their
WorkOS user is a new person in Tadas: the identity the sign-in would
have found is gone. The item may then delete the WorkOS user that new
person signed in as. Their next sign-in makes a WorkOS user again, and
Tadas links it to them by the verified address, as it links any person
WorkOS knows under a new id.

The refusal asks the last owner to make someone else an owner, which
the API does (`PATCH /v1/memberships/{user_id}`); the portal has no
control for it yet. A tenant cannot delete a team org yet either: an
operator does. So a team org whose only member is its owner holds its
owner's account until an operator deletes the org.

The WorkOS organization a personal org gets when its owner invites
someone to it stays at WorkOS under the org's id.

The outbox rows and work items of the deletion stay for their own
retention, eight and thirty days. They carry ids and a WorkOS user id,
never a name or an address.
