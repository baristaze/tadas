# Changelog

Each release has an entry here, the newest first. An entry lists what
changed since the previous tag. A project that clones Tadas at a release
checks out its tag, such as `git clone --branch v0.7.0`.

## 0.9.0 (2026-09-30)

Tadas's base is the guideline's scaffold, and the pin moves to v0.40.0
by merging it. The portal, the command line, and the API work as they
did at 0.8.0: no route, wire type, screen, or migration changes.

- **Tadas is based on the guideline's scaffold.** The branch `scaffold`
  holds swe_guidelines' `scaffold/acme_root/` as Tadas took it, renamed
  to `tadas`: v0.39.0, then v0.40.0. `main` merges that branch, so a
  later release comes in by a merge, and
  `/swe-guidelines:arch-upgrade-scaffold` makes the move. (#177)
- **The guideline pin moves to v0.40.0.** `make arch-check` passes at
  v0.40.0, and ADR 0082 records what the release asks: ADRs 0011, 0027,
  and 0040 are no longer deviations, and 0041 and 0067 keep one part
  each. (#177)
- **The ops skills** take the scaffold's added bounds and steps. (#177)

## 0.8.0 (2026-09-29)

Tadas moves to the shape of the guideline at v0.39.0. The portal, the
command line, and the API work as they did at 0.7.0: no route, wire
type, screen, or migration changes.

- **The guideline pin moves to v0.39.0,** by way of v0.38.0.
  `make arch-check` passes at v0.39.0, and ADRs 0080 and 0081 record
  where Tadas stands on each rule the two releases change. (#173, #174)
- **A tenant operation's context is `TenantContext`.** `OpContext` is
  renamed, and its module `tadas.om.opcontext` is `tadas.om.context`.
  Code built on Tadas imports the new names. (#174)
- **The TypeScript client is a package of its own.** `@tadas/client`,
  in `clients/typescript/`, holds the one transport, the generated
  types, and the OpenAPI document, which was `apps/portal/openapi.json`.
  The portal imports it alone, and a new browser app imports it too.
  (#171)
- **The ops skills live in `.agents/skills/`,** where any agent that
  reads the Agent Skills standard finds them, and `.claude/skills`
  links there. Every loop a skill runs has a count: a watch's batches,
  a query's polls, the request ids a root cause follows, and the hops
  of Next. (#170, #173)
- **The docs tell the story for two readers.** `docs/architecture.md`
  is gone: the guideline holds the shape, the tree is the system as
  built, and `docs/adr/` records each decision. The README and
  `llms.txt` take the scaffold's shape and keep the product story.
  (#172)
- **The deviations table lists live deviations only.** Each row in
  `specs/architecture.md` names its rule, the section the rule cites,
  and that section's tag at v0.39.0. There are 14. (#175)
- **CI** runs `astral-sh/setup-uv` 10.2.0. (#169)

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
