# Architecture

This project follows the Software Design and Architecture Guidelines:
<https://github.com/baristaze/swe_guidelines/blob/v0.39.0/architecture.md>
(pinned at release `v0.39.0`; the pin moves with the releases this
project adopts, one pull request per release).

The guideline is the source of truth for how this system is shaped, and
the tree is the system as built. `docs/adr/` records the decisions that
constrain future work, every deliberate deviation among them.

## Substitutions

Recorded in `docs/adr/0002-technology-choices.md`. A departure from a
`default` section of the guideline is a substitution, not a deviation.

| Named in the guideline | Here |
|------------------------|------|
| React and TypeScript on Vite, for every browser app (Client App Architecture, Stack) | The company site, `apps/site`, is HTML and CSS on Vite, with no script ([ADR 0030](../docs/adr/0030-the-company-site-is-html-and-css-not-react.md)). |

## Deviations

Each row names its rule by the lens ID and the section the lens cites,
with that section's tag from How to Read This: `core`, or untagged,
where the text is the rule. A departure from an `optional` or a `style`
section is no deviation. A record that is closed or superseded leaves
the table and keeps its status line.

| ADR | Rule | Tag | Summary |
|-----|------|-----|---------|
| [0006](../docs/adr/0006-pre-release-compatibility.md) | NET-23, The Network Layer, Public Types | `core` | While Tadas has no customer, the API keeps `/v1`, and a field may leave it one release after it is marked deprecated, where the rule asks for a new prefix: a task write's `version`, then `remind_at`, and `position` next. The first customer, or the first client outside this repository, ends it. The one-step column renames ended with the first deployment, on 2026-09-22. |
| [0010](../docs/adr/0010-operator-console-not-built-yet.md) | DEL-16, Client App Architecture, The Operator Console | untagged | No operator console yet: the `/v1/admin/*` routes take `OperatorContext` and operators use the API. The console lands in `apps/admin` with the portal's stack, its own origin and bundle, and no socket, when an operator task needs a screen. |
| [0011](../docs/adr/0011-audit-entries-are-events.md) | OM-16, Namespaces as Swimlanes | `core` | An audit entry is an `Event` with an audit kind in the events stream, built by the `audit_event` helper on the events manager; an `audit` namespace of its own appears when audit gains a reader of its own. |
| [0019](../docs/adr/0019-an-api-key-hash-stays-unique-after-revocation.md) | STO-26, The Storage Layer, Defining ORM Classes | untagged | `uq_api_keys_key_hash` is a full unique index on a soft-deletable table: a key hash digests a fresh random secret, and the lookup reads revoked keys so it can answer "revoked". |
| [0020](../docs/adr/0020-the-cli-signs-in-as-a-person.md) | DEL-17, Client App Architecture, The CLI Is Different | untagged | The CLI signs in as a person, not with an API key, and follows the person's rules: one session in one org, chosen by `--org` or the only membership, listed by `tadas orgs`, and moved by `tadas switch`, whose exchange ends the old session. An API key in `TADAS_TOKEN` is never switched. |
| [0021](../docs/adr/0021-each-environment-has-an-aws-account-of-its-own.md) | OPS-18, Operations, Cost Boundaries | untagged | While Cost Explorer is off for an account, the create script leaves the anomaly monitor out, and the budget stands alone. It closes on the first create run after Cost Explorer is on. |
| [0024](../docs/adr/0024-what-staging-hands-production-is-recorded-and-verified.md) | DEL-38, Deployment, Cloud: AWS | untagged | The release push stays on the workflow token while no ruleset locks `release`; the host's app becomes the one bypass actor the day one does. |
| [0025](../docs/adr/0025-rules-of-0-29-0-that-wait-for-their-feature.md) | DEL-31, Deployment, Cloud: AWS; OPS-17, Operations, Scale-Out as a Lever | untagged; untagged | The kept portal builds carry no object lock: only replication writes them, and the recorded digest refuses a changed copy. `desired_count` stays out of `ignore_changes`, so an apply returns a scaled service to its floor. |
| [0027](../docs/adr/0027-a-task-slack-creates-takes-an-id-derived-from-the-delivery.md) | OM-12, Naming Entities, Identifiers | `core` | A task `/tadas add` creates takes a v7 id derived from the Slack delivery's key and the time it arrived, so a delivery handled twice creates nothing. Every other id is `new_id()`. |
| [0040](../docs/adr/0040-the-event-stream-has-a-floor.md) | NET-22, The Network Layer, Realtime at the Edge; DEL-18, Cross-Cutting Conventions, Exceptions | `core`; untagged | The stream is gapless above a per-org floor the trim moves in its own transaction, not from seq 1. A read below the floor is `410 stream_truncated`, a status the shapes do not list, and it names the head; both clients read afresh from there. |
| [0041](../docs/adr/0041-an-account-is-deleted-at-once-and-its-providers-by-the-queue.md) | STO-32, The Storage Layer, Database Roles; CTX-34, Worker Roles, The Work Queue | `core`; `core` | A person's account is a hard delete in one commit, outside the sweep, and its providers go after, through the queue. The person's open tasks in each team org go unassigned on the service role, whatever role they held. |
| [0050](../docs/adr/0050-a-move-writes-one-row.md) | STO-05, The Storage Layer, Storage Principles | `core` | Two triggers keep a task's rank and its position in step for the release before, which writes and reads the position alone. They go with the position's column. |
| [0053](../docs/adr/0053-the-scope-rides-in-the-message-that-begins.md) | STO-28, The Storage Layer, The Second Fence | untagged | The scope goes out in the message that begins the transaction, as checked literals, not as a statement of its own with bind parameters. |
| [0067](../docs/adr/0067-what-0-36-0-asks-and-what-stays-a-choice.md) | OPS-11, Operations, Operational Skills; CTX-27, TenantContext, Stages | untagged; `core` | The two optional audits also count, on a database of their own, what they read. The socket's recheck interval is `realtime_recheck_seconds`, not `session_recheck_interval`. |
