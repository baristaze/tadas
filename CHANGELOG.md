# Changelog

Each release has an entry here, the newest first. An entry lists what
changed since the previous tag. A project that clones Tadas at a release
checks out its tag, such as `git clone --branch v0.7.0`.

## 0.7.0 (2026-09-27)

The first tagged release. Tadas is a multi-tenant to-do application for
teams of people and the agents that work alongside them, built in the
shape of the Software Design and Architecture Guidelines, pinned at
v0.37.0. This entry says what the system does at this tag. Every entry
after it lists the changes since the tag before.

- **Tasks for teams.** A person has a personal org and can create team
  orgs, switch between them, hand one on, or delete it. A task has a
  due date, an assignee, and attachments. Quick add is one text box,
  and the task list offers bulk actions with Undo.
- **Realtime.** Every change reaches every open portal and every
  `tadas listen` over one realtime channel. A client that falls behind
  the event stream resyncs.
- **The portal, the command line, and a Python client.** The portal is
  a browser app. `tadas` works one command at a time or listens. The
  Python client covers the public API under `/v1`, described by the
  committed OpenAPI document.
- **Sign-in and billing.** People sign in through WorkOS AuthKit, and
  sessions last 30 days, or 14 idle. API keys and operator credentials
  have budgets and end on their own. Billing runs through Stripe, and
  seats follow the org's members.
- **Slack.** The Slack app is installed per org, over HTTP.
- **Background work.** An outbox relays every write, a work queue and
  its worker run the jobs, and a sweep sends reminders, runs
  long-running orchestrations such as a task import, and purges what
  retention ends.
- **Operations.** It deploys to AWS with Terraform. `main` deploys to
  staging, and the `release` branch, moved by a workflow, deploys to
  production. Alarms cover the queue, the outbox, and failed rows, and
  a local stack runs everything in containers with `make up`.
