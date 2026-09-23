# Architecture

This project follows the Software Design and Architecture Guidelines:
<https://github.com/baristaze/swe_guidelines/blob/v0.32.0/architecture.md>
(pinned at release `v0.32.0`; the pin moves with the releases this
project adopts, one pull request per release).

The guideline is the source of truth for how this system is shaped.
`docs/architecture.md` describes what is implemented; `docs/adr/`
records the decisions that constrain future work, including every
deliberate deviation from the guideline.

## Substitutions

Recorded in `docs/adr/0002-technology-choices.md`. None today: Tadas
adopts every technology the guideline names.

| Named in the guideline | Here |
|------------------------|------|

## Deviations

| ADR | Rule | Summary |
|-----|------|---------|
| [0003](../docs/adr/0003-migrate-check-in-the-integration-job.md) | STO-18, The Storage Layer, Migrations | Superseded (2026-09-19): v0.13.0 makes `make migrate-check` a target of its own, run after migrating and in CI's integration job and not in the fast gate, which is what this record decided. The record stays for the interval it covers. |
| [0004](../docs/adr/0004-demo-recorder-calls-the-api-directly.md) | NET-15, The Network Layer, Clients Live in One Place; CON-14, Direction of Calls | Superseded (2026-09-18): the demo recorder kept its own request helper until a Python consumer shipped the generated client; the CLI brought `clients/python/` and the recorder uses it. The record stays for the interval it covers. |
| [0005](../docs/adr/0005-infra-exception-root.md) | DEL-18, Cross-Cutting Conventions, Exceptions | Infra has its own exception root, a mirror of `PlatformException`, because infra imports nothing from the object model; every boundary translates both. |
| [0006](../docs/adr/0006-pre-release-compatibility.md) | NET-23, Public Types; STO-18, Migrations | Until the first deployment a rename lands under `/v1` and a column renames in one migration; `EventView` and the `events` and `work_items` renames are the recorded cases. |
| [0010](../docs/adr/0010-operator-console-not-built-yet.md) | DEL-16, Client App Architecture, The Operator Console; `apps/admin` in Monorepo Folder Structure | No operator console yet: the `/v1/admin/*` routes take `OperatorContext` and operators use the API; the console lands in `apps/admin` with the portal's stack, its own origin and bundle, and no socket, when an operator task needs a screen. |
| [0011](../docs/adr/0011-audit-entries-are-events.md) | OM-16, Namespaces as Swimlanes; Realtime at the Edge | An audit entry is an `Event` with an audit kind in the events stream, built by the `audit_event` helper on the events manager; an `audit` namespace of its own appears when audit gains a reader of its own. |
| [0012](../docs/adr/0012-the-work-queue-has-no-producer-yet.md) | STO-20, ASY-25, The Work Queue; Database Roles | Closed (2026-09-22): a member added or removed on Max lands `work.SYNC_SEATS` beside its change, the path this record held built and tested, and the relay enqueues it (ADR 0027). A work-item key held by another tenant stays a conflict. The record stays for the interval it covers. |
| [0015](../docs/adr/0015-the-event-keeps-its-produced-at.md) | Naming Entities, the append-only record | `Event` keeps `produced_at` although its birth time is the one in its id, because `EventView` publishes no `id` and the wire would lose the "when". The route out is named: the id reaches the wire first, then the column goes. |
| [0019](../docs/adr/0019-an-api-key-hash-stays-unique-after-revocation.md) | STO-26, The Storage Layer, Defining ORM Classes | `uq_api_keys_key_hash` is a full unique index on a soft-deletable table: a key hash digests a fresh random secret, and the lookup reads revoked keys so it can answer "revoked". |
| [0020](../docs/adr/0020-the-cli-signs-in-as-a-person.md) | DEL-17, Client App Architecture, The CLI Is Different; One Tenant at a Time | The CLI signs in as a person, not with an API key, and follows the person's rules: one session in one org, chosen by `--org` or the only membership, listed by `tadas orgs`, and moved by `tadas switch`, whose exchange ends the old session. An API key in `TADAS_TOKEN` is never switched. |
| [0022](../docs/adr/0022-a-deployed-environment-has-no-operator-or-smoke-identity-yet.md) | DEL-45, Migrating a Deployed Database; OPS-22, The Telemetry Round Trip | Closed (2026-09-22): `grant-operator.yml` runs `tadas-api grant-operator` as a one-off grant task, and the smoke test signs in with the smoke identity's operator token after every rollout. The record stays for the interval it covers. |
| [0023](../docs/adr/0023-the-row-level-security-bypass-is-a-setting-for-now.md) | STO-28, Row-Level Security | Release A: three logins, and the system scope admits `tadas_system` or, for one release, the master `tadas`; release B removes the master from the clause and closes the record. |
| [0024](../docs/adr/0024-what-staging-hands-production-is-recorded-and-verified.md) | DEL-38, Cloud: AWS | The release push stays on the workflow token while no ruleset locks `release`; the app token becomes the bypass actor the day it does. The fast rollback is `DEL-50`'s, to the previous release only. The ADR also records the positions on a WAF and on threat detection. |
| [0025](../docs/adr/0025-rules-of-0-29-0-that-wait-for-their-feature.md) | DEL-31, DEL-38, OPS-15; Scale-Out as a Lever | The rules of 0.29.0 that wait for the feature they bind: a replicated overwrite caught by the digest, the app token, queue alarms, and `desired_count` kept out of `ignore_changes` on purpose. |
| [0026](../docs/adr/0026-what-0-31-0-leaves-as-a-choice.md) | CTX-12, CTX-36, STO-34, The Second Fence | What 0.31.0 leaves as a choice: more system-scope methods than the guideline lists, sessions, keys, and tickets kept `both`, no issuer-subject lookup without an external provider, shorter session lifetimes, `valkeys://`, and no audit value to redact yet; and what release B removes. |
| [0027](../docs/adr/0027-plans-are-levers-and-the-processor-is-mirrored.md) | Queues (rate limits), Secrets | The payment processor's webhook route has no rate limit, with no path token to key one on; its key and signing secret are process credentials injected at start, not read through `SecretsInterface`. The record also names the product's choices: plans per org, a mirror written from reads, a 402 that releases the idempotency marker, keys kept and refused after a downgrade, and a seed that grants its own team a plan. |
