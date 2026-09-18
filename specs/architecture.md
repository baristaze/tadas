# Architecture

This project follows the Software Design and Architecture Guidelines:
<https://github.com/baristaze/swe_guidelines/blob/v0.4.0/architecture.md>
(pinned at release `v0.4.0`; the pin moves with the releases this
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
| [0003](../docs/adr/0003-migrate-check-in-the-integration-job.md) | STO-18, The Storage Layer, Migrations | The per-role metadata-vs-schema check needs a migrated Postgres, so it runs in CI's integration job, not the fast gate. |
| [0004](../docs/adr/0004-demo-recorder-calls-the-api-directly.md) | NET-15, The Network Layer, Clients Live in One Place; CON-14, Direction of Calls | The demo recorder, the only Python caller, keeps its own request helper, and every service interface has its in-process impl only, until a Python consumer ships the generated client under `clients/python/`. |
| [0005](../docs/adr/0005-infra-exception-root.md) | DEL-23, Cross-Cutting Conventions, Exceptions | Infra has its own exception root, a mirror of `PlatformException`, because infra imports nothing from the object model; every boundary translates both. |
| [0006](../docs/adr/0006-pre-release-compatibility.md) | NET-23, Public Types; STO-18, Migrations | Until the first deployment a rename lands under `/v1` and a column renames in one migration; `EventView` and the `events` and `work_items` renames are the recorded cases. |
