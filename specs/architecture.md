# Architecture

This project follows the Software Design and Architecture Guidelines:
<https://github.com/baristaze/swe_guidelines/blob/v0.19.0/architecture.md>
(pinned at release `v0.19.0`; the pin moves with the releases this
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
| [0012](../docs/adr/0012-the-work-queue-has-no-producer-yet.md) | STO-20, ASY-25, The Work Queue; Database Roles | A write that also starts work is built, wired and held by an end-to-end test, and no write in Tadas starts work: the product has no follow-up work to defer, and the first domain work kind rides the path rather than getting one of its own. A work-item key held by another tenant stays a conflict. |
| [0015](../docs/adr/0015-the-event-keeps-its-produced-at.md) | Naming Entities, the append-only record | `Event` keeps `produced_at` although its birth time is the one in its id, because `EventView` publishes no `id` and the wire would lose the "when". The route out is named: the id reaches the wire first, then the column goes. |
