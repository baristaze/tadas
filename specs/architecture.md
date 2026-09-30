# Architecture

This project follows the Software Design and Architecture Guidelines:
<https://github.com/baristaze/swe_guidelines/blob/v0.43.0/architecture.md>
(pinned at release `v0.43.0`; the pin moves one release at a time, in a
pull request of its own).

The guideline is the source of truth for how this system is shaped, and
the tree is the system as built. `docs/adr/` records the decisions that
constrain future work, every deliberate deviation among them.

## Substitutions

Recorded in [ADR 0002](../docs/adr/0002-technology-choices.md). Tadas
adopts every other technology the guideline names.

| ADR | Rule | Summary |
|-----|------|---------|
| [0002](../docs/adr/0002-technology-choices.md) | DEL-12, Client App Architecture, Stack | The company site is HTML and CSS on Vite, with no script and no React. |

## Deviations

| ADR | Rule | Summary |
|-----|------|---------|
| [0006](../docs/adr/0006-pre-release-compatibility.md) | NET-23, Public Types | While Tadas has no customer, the API keeps `/v1`, and a field may leave it one release after it is marked deprecated, where the rule asks for a new prefix. A task's `position` leaves next. The first customer, or the first client outside this repository, ends it. |
| [0010](../docs/adr/0010-operator-console-not-built-yet.md) | DEL-16, The Operator Console | No console app: operators work through `/v1/admin/*` with `tadas-ops` and an operator token, until an operator task needs a screen. |
| [0019](../docs/adr/0019-an-api-key-hash-stays-unique-after-revocation.md) | STO-26, Defining ORM Classes | `uq_api_keys_key_hash` stays a full unique index, so the lookup can answer "revoked". |
| [0020](../docs/adr/0020-the-cli-signs-in-as-a-person.md) | DEL-17, The CLI Is Different | The CLI signs in as a person and holds one session in one org; an API key in `TADAS_TOKEN` works as the rule describes. |
| [0021](../docs/adr/0021-each-environment-has-an-aws-account-of-its-own.md) | OPS-18, Cost Boundaries | While the organization's Cost Explorer is off, the create script leaves the anomaly monitor out, and the budget stands alone. |
| [0024](../docs/adr/0024-what-staging-hands-production-is-recorded-and-verified.md) | DEL-31, DEL-38, Cloud: AWS | The kept builds carry no object lock: only replication writes them, and the recorded digest refuses a changed copy. The release push stays on the workflow token while no ruleset locks `release`; the host's app, or a deploy key, becomes the one bypass actor the day one does. |
| [0025](../docs/adr/0025-an-apply-returns-a-scaled-service-to-its-floor.md) | OPS-17, Scale-Out as a Lever | `desired_count` is not in `ignore_changes`: an apply returns a scaled service to its floor. |
| [0041](../docs/adr/0041-an-account-is-deleted-at-once-and-its-providers-by-the-queue.md) | CTX-34, The Work Queue | When a person deletes their account, their open tasks in each team org go unassigned on the service role, whatever role they held. |
| [0050](../docs/adr/0050-a-move-writes-one-row.md) | STO-05, Storage Principles | Two triggers keep a task's rank and its `position` column in step for the release before, which names the position in every insert and reads it as a number. They go with the column, in the contract step. |
| [0053](../docs/adr/0053-the-scope-rides-in-the-message-that-begins.md) | STO-28, The Second Fence | The scope goes out in the message that begins the transaction, as checked literals, not as a bound statement of its own. |
| [0067](../docs/adr/0067-the-two-optional-audits-count-as-well-as-read.md) | OPS-11, Operational Skills | The two optional audits also count, through the twins, on a database of their own. |
