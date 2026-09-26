# The maintenance worker

The background process of Tadas. It runs the work queue's claim loop,
the consumer of what Slack sends, and, on a timer, the sweep that keeps
the platform tidy. Every replica is the same process on one lane; a
second lane is a second replica told its lane.

## What it does

- **Claim, handle, complete.** The loop wakes on `work_available`,
  with a short poll as the fallback for a missed wake-up, and claims
  the oldest available item on its lane while it has a free slot. Each
  item runs as a task of its own, under the context the claim produced,
  naming the request that caused the work and linking its trace to
  that request. When the handler returns, the item is completed; when
  it raises, the item is failed, which requeues it with a growing delay
  or, once its attempts are spent, makes it a dead letter. When it
  parks, the item is handed back for the time it named and spends no
  attempt.
- **The kinds.** A reminder waits for nine in the morning of its task's
  due date, in the time zone of the person the task is for, read when it
  runs; before then it parks until then. Then it marks its task reminded
  and announces it, if the task is still open and still due on that
  date; otherwise it sends nothing. A Slack post writes one line to
  the org's channel (a task created, completed, or reminded of),
  records it under the item's key so a rerun posts nothing, parks on a
  rate limit for the time Slack named, and marks the installation
  broken when Slack refuses the channel for good. `SYNC_SEATS` reads an org's
  active members when it runs and holds a Max subscription's quantity to
  them, with no proration and under a key made of the item and the
  count, so a retried run is one change. An orchestration step reads its
  record and, while it runs, does one batch of it: an import makes the
  tasks of the next hundred rows, a cleanup archives the next five
  hundred old done tasks. The batch, the record's next cursor, and the
  next step's item land in one commit. A step that raises is retried by
  the queue from the cursor the last commit left; on its last attempt the
  record fails as `defect`. A wake-up resumes the org's records parked
  for the reason a plan that rose cleared. The last kind does nothing and
  keeps the loop honest.
- **What Slack sends.** Slack calls the API, which checks each call's
  signature, acknowledges it within Slack's three seconds, and queues
  it on `slack`. The worker reads that queue: `/tadas` commands,
  mentions, the App Home opening, and the app's uninstall. The org is
  the one that installed the app in the call's workspace. The person
  is the org's member whose sign-in proved the email their Slack
  profile holds; someone Tadas cannot match is told how to join.
  `/tadas` alone answers with your ten newest open tasks, `/tadas team`
  with the org's, each with a count of the rest and a link to the
  portal at `TADAS_PORTAL_URL`. `/tadas add <title>` creates a task
  made by the person who typed it. `/tadas connect`, from an owner or
  an admin, makes the channel it was typed in the one Tadas posts to.
  `/tadas help`, and anything else, answers with the usage, and so
  does a mention, in its thread. A task past the org's plan is not
  added, and the reply names the plan and where to upgrade. A call
  handled twice changes nothing: the task takes an id derived from the
  call's key, and a mention's reply is recorded under it. A call that
  fails stays on the queue and comes back.
- **Apply the payment processor's deliveries.** Beside the claim loop,
  the worker long-polls the inbound queue the webhook route fills. For
  each delivery it finds the org the delivery names, mints that org's
  service context, and applies the delivery: the subscription is read
  from the processor again, and the delivery's mark lands in the
  account's commit, so a copy changes nothing. A message is deleted once
  it is applied, or once it can never be (no org named, or the org is
  gone); any other failure leaves it to come back after its visibility,
  and the queue dead-letters it past its receives.
- **Renew the lease and fence itself.** While an item runs, the worker
  renews its lease. A renewal refused because the lease was lost
  cancels the running task at once, since another worker holds the
  item now. A renewal that fails for any other reason is retried, and
  the task is cancelled at half the lease if none succeeds, so no
  worker keeps working an item it may no longer settle.
- **The sweep**, every thirty seconds by default, under one service
  context per org, the system scope first and deleted orgs included:
  - **Requeue** items whose lease has expired, or fail them when their
    attempts are spent. One sweep takes a batch per org (a hundred by
    default, `requeue_batch`), bounded in the statement; the rest wait
    for the next sweep.
  - **Purge** each namespace's rows past its retention: deleted tasks,
    removed files and uploads never confirmed (the object in the store
    first, then the row, a batch of a hundred per org per sweep),
    removed members with their ended memberships, revoked keys, dead
    sessions, spent tickets, finished idempotency records, the payment
    processor's delivery marks, settled work items, and orchestrations
    that succeeded or failed thirty days ago. With
    `TADAS_EVENT_RETENTION_DAYS` set, the oldest events of a living org
    go too, a batch of up to a thousand per org per sweep, and its
    floor moves with them in the same transaction; 0, the default, keeps
    every event (ADR 0040). Under an org deleted longer ago than the retention,
    every row goes, its event stream included, and the org row stays as
    the record. Each namespace
    purges its own rows and asks tenancy the one question, whether the
    org has expired.
  - **Open the day's cleanup** of each org that has a done task nobody
    changed for the archive age (`TADAS_TASKS_ARCHIVE_AFTER_DAYS`, ninety
    by default). The org, the kind, and the day are the record's unique
    key, so the first sweep of the day opens it and every later one
    opens nothing. No scheduler is involved.
  - **Relay** the outbox rows the request path left behind, one
    attempt each with a growing delay, and fail the ones whose
    attempts are spent.
  - **Purge** the outbox rows done or failed past eight days, which
    outlives the database backup retention.
- **Liveness.** The worker beats every ten seconds by default, in
  memory, and publishes each beat to the cache as best effort, bounded
  by its interval, so other replicas can see it. Its `/healthz`, served
  on the metrics port, answers 200 while the last beat is within three
  intervals; a cache outage neither fails the probe nor stops claiming,
  because the queue and its leases live in Postgres. The container
  probe and the `health` subcommand ask that URL. `/metrics` on the
  same port is what the collector scrapes.
- **Drain first.** On stop, the loop claims nothing new, cancels the
  items it holds and waits for each to hand its item back to the queue
  for another worker, then marks itself offline. A cloud rollout replaces one worker at a time, because a
  worker holds leases.

## The subcommands

| Subcommand | Does |
|------------|------|
| `serve` | Runs the loop and the `slack` queue's consumer; `--lane` overrides the lane from settings. |
| `health` | Asks the serving process's `/healthz` by hand; exits 0 on 200. |

## What it never does

It never runs a job under a person's credential: a claimed item runs
under the service role for the org, with the person who asked kept as
the attribution. It never hard-deletes anything before its retention.
And it never settles an item it no longer holds: every write after the
claim is conditional on the claim token.
