# ADR 1006: An operator reads an org's tasks and billing, and grants a plan

**Status**: accepted (2026-10-14)

## Context

[ADR 0018, The operator allowlist carries a role, and an operator signs in as a person](0018-the-operator-allowlist-carries-a-role.md)
names the operator plane's reads and writes and the role each requires.
Tadas's operator plane has three operations of its own: a support case
often turns on what a team's list holds or what it pays, and a plan
can be granted without a payment.

## Decision

- **`get_tasks` is a read.** It lists an org's tasks, open or done, a
  page at a time (`GET /v1/admin/orgs/{org_id}/tasks`), and requires
  `read`. It reads every task of the team, as no member: the `mine`
  scope is about a member, and an operator is not one.
- **`get_billing` is a read.** It answers an org's plan and its billing
  account (`GET /v1/admin/orgs/{org_id}/billing`), and requires `read`.
- **`comp_plan` is a write.** It grants an org a plan, or takes the
  grant back (`PUT /v1/admin/orgs/{org_id}/plan`), and requires
  `write`.

Each read logs one support-trail line naming the org and the operator,
and nothing of what it read, as the plane's other reads of a tenant's
rows do.

## Consequences

A credential with `read` sees a team's task titles, notes, and
assignees, and its plan. Only `write` changes what an org pays. No
operator operation writes a task.
