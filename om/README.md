# What Tadas is made of

Tadas is a to-do list for a team. This page names the things Tadas is
made of and says how they relate. It is written for anyone; you need no
code to read it. Each kind of thing has a page of its own one level
down, which says what can happen to it and which rules always hold.

## The org and the people in it

An **organization**, org for short, is one tenant: a company, a team, a
household. Everything in Tadas belongs to exactly one org, and nothing
in one org can see anything in another. That is a rule, not a choice.

Every person has one **personal org**, made with them the first time
they sign in. It is theirs for as long as they exist, and it goes only
with their account. Every other org is a **team org**, which a person
makes and owns.

An **identity** is one person across every org: the email the sign-in
provider has verified. Tadas keeps no password.

A **user** is that person inside one org: the name the org sees.

A **membership** is the user's place in the org, with a role: viewer,
member, admin, or owner. The role decides what the person may do there.

An **invitation** asks a person to join an org, by email, with a role.
The sign-in provider sends the email.

## How a person proves who they are

A **session** is a signed-in visit to one org. It ends when the person
signs out, when it sits idle too long, or when it reaches its lifetime.

An **API key** is a named, expiring credential for a program, with a
role no higher than its maker's. Tadas keeps only its fingerprint, so
the key is shown once.

A **socket ticket** is a one-use pass that opens the live channel, the
connection through which changes reach a screen as they happen.

An **operator** is a person on the platform's own allowlist. An
operator works across orgs with an **operator token**: one permission,
an hour at most.

## The work

A **task** is one item on the list: a title, notes, who it is assigned
to, and whether it is open or done. Open tasks sit in the order the
team arranged them; done tasks are listed newest first. A task
remembers who created it and who last changed it. It can carry a
**due date**, a day and never an hour. On the morning of that day, at
nine where the person it is for lives, the team gets one reminder, on
every open screen and in the org's Slack channel.

Tasks can be **imported** from a CSV file: one row, one task. A done
task left unchanged for ninety days is **archived** by a cleanup that
runs once a day: it leaves the done list and every count, and it can be
read and restored.

## Files

A **file** is a record of something an org keeps in the object store:
its name, type, size, who uploaded it, and why. The bytes live in the
store, never in the record. A file on a task is an **attachment**.

## Slack

A **Slack installation** is the Tadas app added to one Slack workspace
for an org. An owner or an admin installs it from Settings with "Add to
Slack". The org has at most one, and a workspace belongs to one org.
The app's key into that workspace, its bot token, is the org's own
secret, kept in the secret store and never on the record.

The installation's **channel** is where reminders, new tasks, and
finished ones appear. An owner or an admin picks it by typing
`/tadas connect` there. In any channel the app is in, `/tadas` shows
your open tasks, `/tadas team` the org's, and `/tadas add <title>` adds
a task. Tadas knows who typed by the email address Slack holds for
them, which must be one a member signed in with.

## The plan

A **plan** is what an org is entitled to: how many members, whether it
may have API keys, how many active tasks, and how much room for files.
Every org is on one, Free to begin with. The plan belongs to the org,
never to a person: the owner pays for the team.

A **billing account** is the org's place at the payment processor: its
customer there, and Tadas's copy of the subscription the org pays for.
The processor owns the money; Tadas owns what a plan lets the org have,
and copies what the processor holds whenever it says something changed.
An operator can also grant an org a plan with no payment.

A **delivery mark** says that one message from the processor has been
applied, so the same message arriving again changes nothing.

## What the platform writes for itself

No person creates these and no screen shows them, but each belongs to
an org like everything else.

An **event** is a line in the org's diary: what changed, how, by whom,
and when. The lines are numbered with no gaps. An **audit entry** is an
event the platform records about itself, such as a job that failed for
good.

An **outbox row** is a note written in the same stroke as a change,
saying "tell everyone about this". The event and the live push come
from it, so no change goes unannounced.

A **work item** is a job for later, such as the reminder a due date
scheduled or a post to Slack. It waits in a queue until a worker claims
it, holds it for a short lease, and does it.

An **orchestration** is a long job kept as a record, done one step at a
time, such as an import or a day's cleanup. It succeeds, fails, or
parks until what it waits for is back: an import that reached the
plan's bound of active tasks waits for a plan that lifts it.

An **idempotency record** remembers the outcome of a request that may
arrive twice, so the second copy gets the first one's answer.

## How they fit together

- An org has users. A user is one identity's place in the org, held by
  a membership with a role.
- A session or an API key belongs to a user, so everything done with
  it is done as that user in that org.
- Tasks belong to the org. Each is created by a user and may be
  assigned to a user. A task added from Slack is created by the member
  who typed it; a task imported from a file, by the member who started
  the import.
- Files belong to the org. An attachment names the task it is on, and
  goes when the task goes.
- A Slack installation belongs to the org, and a workspace to one org.
- An org is on one plan. The plan bounds its members, its API keys,
  and its active tasks; meeting a bound is a refusal that offers the
  plan that lifts it, and nothing is ever taken away.
- Every change a screen acts on writes an outbox row, which becomes an
  event in the org's diary, which reaches every open screen of the org.
- A work item, an orchestration, an idempotency record, an event, and
  an outbox row each name their org, so the fence between orgs holds
  for them too.

## One page per kind

- [Orgs, identities, users, memberships, and credentials](src/tadas/om/tenancy/README.md)
- [Tasks](src/tadas/om/tasks/README.md)
- [Files](src/tadas/om/media/README.md)
- [Slack installations and posts](src/tadas/om/slack/README.md)
- [Plans, billing accounts, and delivery marks](src/tadas/om/billing/README.md)
- [Events](src/tadas/om/events/README.md)
- [Outbox rows](src/tadas/om/outbox/README.md)
- [Work items](src/tadas/om/work/README.md)
- [Orchestrations](src/tadas/om/orchestrations/README.md)
- [Idempotency records](src/tadas/om/idempotency/README.md)
