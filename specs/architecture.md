# Architecture

This project follows the Software Design and Architecture Guidelines:
<https://github.com/baristaze/swe_guidelines/blob/0ac8319/architecture.md>
(pinned at commit `0ac8319`, the first commit that closes with the
pointer to this project; the pin moves to a release tag when the
guideline cuts one).

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
| [0004](../docs/adr/0004-demo-recorder-calls-the-api-directly.md) | NET-15, The Network Layer, Clients Live in One Place | The demo recorder, the only Python caller, keeps its own request helper until a Python consumer ships a generated client. |
