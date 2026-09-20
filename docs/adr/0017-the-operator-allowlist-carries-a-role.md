# ADR 0017: The operator allowlist carries a role, and an operator signs in as a person

**Status**: accepted (2026-09-20)

## Context

"The Operator Context" admits an identity to the operator plane when
it is on the operator allowlist, and "Operator Roles" says the
supporter reads a named tenant's rows through that plane with an
allowlist entry that says read. Until now the allowlist was one
boolean on the identity, `is_operator`, so every operator could delete
an org, and an agent holding a support credential held that too.

The operator plane also had no way in for an agent but a person's own
sign-in: there is no operator API key, and a tenant API key produces a
tenant context, which the plane refuses by type.

## Decision

The boolean becomes `Identity.operator_role: OperatorRole | None`,
`read` or `write`, and write includes read. `admit_operator` fills
`OperatorContext.permissions` from it, and every operator operation
requires one: the reads (`get_orgs`, `get_org`, `get_members`,
`get_tasks`, `get_events`, `size`) require read, the writes
(`create_org`, `add_member`, `delete_org`) require write. `bootstrap
--operator` grants write, and `--operator-role read` grants read.

An operator signs in as the person they are, through
`POST /v1/auth/login`, and presents the identity token; no tenant
session is exchanged, because the plane admits the identity stage. The
supporter's credential in `~/.config/tadas/ops/<env>.env` is therefore
an operator identity's email and password whose entry is read, and the
skill reads `GET /v1/me/identity` to check the entry before it reads a
tenant. Every operator read of a tenant's rows logs one line with the
org id and the operator's identity id, and no tenant data.

The two operator creates carry an `Idempotency-Key` like every
creating route. Their markers have no tenant, so they are recorded
under the system scope (`EMPTY_UUID`) keyed by the operator's identity
id, through `begin_for_operator`, `finish_for_operator`, and
`release_for_operator` on the idempotency manager, and the system-scope
sweep that purges the platform's own markers purges them too. The CLI's
`bootstrap` and `add-member` and the operator's `create_org` and
`add_member` share one private path, `tenancy/impl/creates.py`, so the
seed and the API create the same rows.

## Consequences

- A support agent cannot delete an org, create one, or add a member,
  whatever it is told, because its entry does not carry write.
- An operator API key is a later step. It needs a credential kind that
  produces an identity stage and not a tenant one, and a place to
  store it that is not a tenant's `api_keys`. Until then the operator's
  sign-in is a password in an owner-only file, which is the same
  posture as the cloud profiles beside it.
- The migration renames a column in one step, which
  [ADR 0006](0006-pre-release-compatibility.md) allows before the
  first deployment. It is the last such rename: the environments are
  about to exist, and from the first deploy a rename is two releases.
- Operator markers live under the system scope by design; a later
  operator namespace of its own would move them, and nothing else.
