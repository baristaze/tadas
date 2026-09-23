# The maintenance worker

The background process of Tadas. It runs the work queue's claim loop,
the consumer of what Slack sends, and, on a timer, the sweep that keeps
the platform tidy. Every replica is the same process on one lane; a
second lane is a second replica told its lane. The same image runs one
more process, `slack`, which holds Slack's connection (below).

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
- **The kinds.** A reminder marks its task reminded and announces it,
  if the task is still open and still due at the time the reminder was
  set for; otherwise it sends nothing. A Slack post writes one line to
  the org's channel (a task created, completed, or reminded of),
  records it under the item's key so a rerun posts nothing, parks on a
  rate limit for the time Slack named, and marks the connection broken
  when Slack refuses the channel for good. The third kind does nothing
  and keeps the loop honest.
- **What Slack sends.** The worker reads the `slack` queue: `/tadas`
  commands, mentions, and the App Home opening, each already
  acknowledged to Slack. `/tadas add` creates a task in the channel's
  org, `/tadas link` spends a link code, anything else answers with the
  usage. A delivery that fails stays on the queue and comes back.
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
    removed members with their ended memberships, revoked keys, dead
    sessions, spent tickets, finished idempotency records, and settled
    work items. Under an org deleted longer ago than the retention,
    every row goes, its event stream included, and the org row stays as
    the record. Each namespace
    purges its own rows and asks tenancy the one question, whether the
    org has expired.
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

## The Slack connection

Slack delivers commands and events over a websocket the app opens
(Socket Mode), not over HTTP, and wants each acknowledged within three
seconds. `tadas-maintenance slack` holds that socket: it acknowledges
each delivery first, then puts it on the `slack` queue, and remembers
recent keys so Slack's retries are dropped. It does nothing else, so a
slow database never delays an acknowledgement. One runs per
environment, never two: Slack spreads deliveries across every open
connection. It opens the socket only when `TADAS_SLACK_APP_TOKEN` is
set, and local and staging share one Slack app, so a laptop leaves the
token empty. Posting needs only `TADAS_SLACK_BOT_TOKEN`; without it a
local worker posts through the twin and a deployed one posts nothing.

## The subcommands

| Subcommand | Does |
|------------|------|
| `serve` | Runs the loop and the `slack` queue's consumer; `--lane` overrides the lane from settings. |
| `slack` | Holds the Slack Socket Mode connection and queues what arrives; idles when no app token is set. |
| `health` | Asks the serving process's `/healthz` by hand; exits 0 on 200. |

## What it never does

It never runs a job under a person's credential: a claimed item runs
under the service role for the org, with the person who asked kept as
the attribution. It never hard-deletes anything before its retention.
And it never settles an item it no longer holds: every write after the
claim is conditional on the claim token.
