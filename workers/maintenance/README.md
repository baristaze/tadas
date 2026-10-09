# The maintenance worker

The background process of Tadas. Every replica runs four things side by
side, started in `main.py`.

- **The work loop** (`loop.py`) claims items from the work queue on its
  lane and runs each under the context the claim built. It renews each
  lease, and completes, fails, parks, or refuses the item. The handlers are
  in `handler.py`, `orchestrations.py`, `accounts.py`, `reminders.py`, and
  `slack_posts.py`.
- **The delivery consumer** (`deliveries.py`) long-polls `Queues.WEBHOOKS`,
  where the API queues each provider's verified delivery, and applies it
  once in the org it names. A message that can never apply is dropped; any
  other failure comes back.
- **The Slack consumer** (`slack_inbound.py`) long-polls `Queues.SLACK`,
  where the API queues each call Slack makes once its signature checked
  out, and handles it in the org that installed the app in the call's
  workspace. A call that fails stays on the queue and comes back.
- **The sweep** (`loop.py`) runs on a timer, within a budget. It requeues
  expired leases, relays the outbox, runs the chores of the orgs that have
  one due, ends each resource's lease past its expiry and the skew margin
  and offers the resource to its line, purges every row past its
  retention (`settings.py`), counts the platform's size, and logs the
  queue's gauges.

`serve` runs the four; `health` asks the running process's `/healthz`.

## The product's kinds

- **A reminder** waits for nine in the morning of its task's due date, in
  the time zone of the person the task is for, read when it runs; before
  then it parks until then. Then it marks its task reminded and announces
  it, if the task is still open and still due on that date; otherwise it
  sends nothing.
- **A Slack post** writes one line to the org's channel (a task created,
  completed, or reminded of), records it under the item's key so a rerun
  posts nothing, parks on a rate limit for the time Slack named, and marks
  the installation broken when Slack refuses the channel for good.
- **`SYNC_SEATS`** reads an org's active members when it runs and holds a
  Max subscription's quantity to them, with no proration and under a key
  made of the item and the count, so a retried run is one change.
- **An orchestration step** does one batch of its record: an import makes
  the tasks of the next hundred rows, a cleanup archives the next five
  hundred old done tasks. A wake-up resumes the org's records parked for
  the reason a plan that rose cleared.
- **A deleted account's item** deletes the person at WorkOS, cancels the
  personal org's subscription at once and deletes its customer at Stripe,
  removes its Slack app, and then deletes the org, which the next sweep
  purges whole. The person's open tasks in each team org they left go
  unassigned by an item of their own, run under their name.
- **A deleted team org's item** deletes the org's organization at WorkOS,
  cancels the subscription and deletes the customer at Stripe, removes the
  Slack app, and then deletes the org, which the sweep purges after the
  retention.

For `SYNC_SEATS` and the two deletions, a processor or a provider out of
reach, or refusing the process's own key, parks the item for a minute,
spending no attempt; one that refuses the request itself fails it at once.

## The payment processor's deliveries

Stripe's deliveries are applied in the org they name, under its service
context. The subscription is read from the processor again, and the
delivery's mark lands in the account's commit, so a copy changes nothing.

## What Slack sends

The consumer reads `/tadas` commands, mentions, the App Home opening, the
app's uninstall, and the bot joining a channel. When someone invites the
bot back to the channel Tadas posts to, an installation that channel broke
is well again and posts resume. The person is the org's member whose
sign-in proved the email their Slack profile holds; someone Tadas cannot
match is told how to join.

- `/tadas` alone answers with your ten newest open tasks, `/tadas team`
  with the org's, each with a count of the rest and a link to the portal at
  `TADAS_PORTAL_URL`.
- `/tadas add <title>` creates a task made by the person who typed it. A
  task past the org's plan is not added, and the reply names the plan and
  where to upgrade.
- `/tadas connect`, from an owner or an admin, makes the channel it was
  typed in the one Tadas posts to.
- `/tadas help`, and anything else, answers with the usage, and so does a
  mention, in its thread.

A call handled twice changes nothing: the task takes an id derived from the
call's key, and a mention's reply is recorded under it.

## The chores

One read across every org a sweep names the orgs with a chore due: a done
task past the day's archive cut, or an open task whose rank grew long, each
found on a partial index that holds only such tasks. It takes a page of a
thousand orgs a sweep, in id order, and the next sweep reads on from the
last org this one ran. An org with no chore due costs a sweep nothing
(ADR 0070). The chores run before the purges per org, and past the budget
they still take one org. Each org they take runs both, under its service
context:

- **Open the day's cleanup** of the org when it has a done task nobody
  changed for the archive age (`TADAS_TASKS_ARCHIVE_AFTER_DAYS`, ninety by
  default) when the day began, in UTC. The org, the kind, and the day are
  the record's unique key, so the first sweep of the day opens it and every
  later one opens nothing.
- **Respace a long rank** of the org when its open list has one: a rank
  past 24 digits after the point, which only many moves into one and the
  same gap make. The run of tasks around it takes short ranks, in the order
  it had, in one write, each task announced like an edit.

The sweep's purges take the product's rows too: deleted tasks (their
attachments first, under the task's org, so a detach that failed is tried
again), the payment processor's delivery marks, and Slack's old install
states and posts. The count of the platform's size counts the tasks created
in the day before it as well.

## Adding a work kind

Add the kind, its payload, and the permission that asks for it in
`tadas.om.work`. Write a handler that names the permissions it calls with
(`REQUIRES`), and add it to `handlers` in `build_loop`; a test holds the
two to each other. A long-running kind is an `OrchestrationKind` whose step
is mapped in `build_loop`.

## Adding a delivery provider

Implement `DeliveryProviderInterface`: read the delivery, name its org, and
apply it under an id derived from its key, so a copy changes nothing. Add it
to `providers` in `build_consumer`, under the name the API queues it with.
