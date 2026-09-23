# What Tadas is made of

Tadas is a to-do list for a team. This page names the things the
product is made of and says how they relate. It is written for anyone;
you need no code to read it. Each kind of thing has a page of its own
one level down, and that page says what can happen to it and which
rules always hold.

## The team and the people in it

An **organization**, org for short, is one team: a company, a club, a
family. Everything in Tadas belongs to exactly one org, and nothing in
one org can see anything in another. That is a rule, not a choice.

Every person has one **personal org**, their own place to work. It is
made with them the first time they sign in, named after them, and it is theirs
for as long as they exist: it is never deleted, and it never changes
hands. Every other org is a **team org**, which a person makes when a
team needs one and owns from then on. A person can belong to many team
orgs, and anyone can be added to a personal org too.

An **identity** is one person, across every org. It is the email the
person signs in with, which the sign-in provider has verified. One
person has one identity, however many teams they belong to. Tadas keeps
no password: WorkOS, the sign-in provider, proves who the person is,
with an email code or link, Google, GitHub, or their company's single
sign-on.

A **user** is that person inside one org: the name the team sees. The
same identity is a different user in each org it belongs to, and a
user in one org knows nothing of the same person in another.

A **membership** is the user's place in the org. It carries a role:
viewer, member, admin, or owner. The role decides what the person may
do in that org. The person who creates the org is its first owner, and
the person of a personal org is its owner for good.

An **invitation** asks a person to join an org, by email, with a role.
The sign-in provider sends the email; signing in through its link makes
the person a member.

## How a person proves who they are

A **session** is a signed-in visit. Signing in through the sign-in
provider gives one. It is good for a while, and it ends when the
person signs out or when it expires. A session belongs to one user in
one org, so a person who belongs to two teams picks which team they
are visiting.

An **API key** is a long-lived credential for a program: a script, an
agent, a tool on a laptop. A member makes it, names it, and gives it a
role that is never above their own. It expires, and it can be revoked
at any time. Tadas keeps only a fingerprint of the key, never the key
itself, so the key is shown once, when it is made.

A **socket ticket** is a small pass that opens the live channel, the
connection through which changes reach a screen the moment they
happen. It works once and it expires in minutes. It stands for the
session or the API key that asked for it, so it opens nothing they
could not open themselves.

## The work

A **task** is one item on the list: a title, notes, who it is assigned
to, and whether it is open or done. Open tasks sit in the order the
team arranged them; done tasks are listed newest first. A task
remembers who created it and who last changed it. It can carry a
**due time**: when it comes, the team gets one reminder, on every open
screen and in the org's Slack channel.

## Slack

A **Slack connection** is the one Slack channel an org posts to:
reminders, new tasks, and finished ones appear there, and
`/tadas add <title>` typed there adds a task, and `/tadas list` shows
the first open ones to whoever typed it. An owner or an admin
connects it with a **link code**, a short code Tadas shows once and
that works once.

A **file** is something a person keeps with the work: a document, a
picture, a recording. Tadas keeps a record of the file (its name, its
type, its size, who uploaded it, and why it is there) and keeps the
bytes themselves in a separate store, never in the record. A file on a
task is an **attachment**. The org's files add up to its storage used.

## What the platform writes for itself

The things above are what people see and touch. The four below are how
Tadas keeps its promises. No person creates them and no screen shows
them, but every one of them belongs to an org like everything else.

An **event** is a line in the org's diary: which thing changed, how,
by whom, and when. The lines are numbered one, two, three, with no
gaps, and a line is never edited; the diary goes only with its org, once
a deleted org's retention has passed. A line about a person records that
something happened to them, never their email or name. The live channel pushes
each new line to every open screen. A screen that was away reads the
diary from the last number it saw and catches up.

An **outbox row** is a note Tadas writes beside a change, in the same
stroke as the change itself, saying "tell everyone about this". From
the note comes the event, and from the event the push. Because the
note and the change are written together, no change is ever made
without its announcement, and no announcement is made of a change that
did not happen.

A **work item** is a job for later: something the platform does in the
background on behalf of a person who asked once, such as the reminder a
due time scheduled or a post to Slack. It waits in a queue, some of it
until a set time.
A worker claims it, holds it for a short lease, does it, and marks it
done. If the worker dies, the lease runs out and another worker picks
the job up.

An **idempotency record** remembers the outcome of a request that
might arrive twice, such as a "create task" that a flaky network
repeats. The second copy gets the first copy's answer instead of making
a second task.

## How they fit together

- An org has users. A user is one identity's place in that org, held
  by a membership with a role.
- An identity has exactly one personal org, and a user and an owner
  membership in it.
- A session or an API key belongs to a user, so everything done with
  it is done as that user in that org. A socket ticket stands for one
  of them.
- Tasks belong to the org. Each is created by a user and may be
  assigned to a user. A task added from Slack is created by the user
  whose code linked the channel.
- A Slack connection belongs to the org, and a channel to one org.
- Files belong to the org. Each is uploaded by a user, for a purpose;
  an attachment names the task it is on, and goes when the task goes.
- Every change to a task or a file, and every change to a user, a membership, a
  session, or an API key that the org's screens act on (a member added,
  changed, or removed, a credential revoked), writes an outbox row, which
  becomes an event in the org's diary, which reaches every screen of the
  org. Signing in, and creating an org, announce nothing.
- A work item, an idempotency record, an event, and an outbox row each
  name the org they belong to, so the fence between orgs holds for them
  too.

## One page per kind

- [Orgs, identities, users, memberships, sessions, API keys, and socket tickets](src/tadas/om/tenancy/README.md)
- [Tasks](src/tadas/om/tasks/README.md)
- [Files](src/tadas/om/media/README.md)
- [Slack connections, link codes, and posts](src/tadas/om/slack/README.md)
- [Events](src/tadas/om/events/README.md)
- [Work items](src/tadas/om/work/README.md)
- [Idempotency records](src/tadas/om/idempotency/README.md)
- [Outbox rows](src/tadas/om/outbox/README.md)
