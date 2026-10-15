# ADR 1021: Slack and the import match a person by the folded address

**Status**: accepted (2026-10-14)

## Context

[ADR 0072, An address is one address in any case](0072-an-address-is-one-address-in-any-case.md)
folds every address before it is stored, compared, or hashed. Tadas
has two more lookups by address. A Slack command names a Slack user,
whom Tadas knows by the address on their Slack profile. A row of a task
import names its assignee by address.

## Decision

- **Slack** acts as the member whose sign-in proved the address the
  Slack profile holds
  ([ADR 0090, An integration acts as the member its proven address names](0090-an-integration-acts-as-the-member-its-proven-address-names.md)).
  The lookup goes through the identity's digest, which folds first, so
  the profile's address finds the member in any case.
- **The import** reads the org's members once, keyed by their folded
  address (`tenancy.rules.fold_email`), and folds each row's assignee
  before it matches. An address no member holds is a bad row: it is
  skipped and named.

## Consequences

`Dee@example.test` on a Slack profile or in an import's file is the
member who signed in as `dee@example.test`.
