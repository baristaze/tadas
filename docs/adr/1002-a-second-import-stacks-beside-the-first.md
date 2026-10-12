# ADR 1002: A second import stacks beside the first

**Status**: accepted (2026-10-12)

## Context

A person starts an import, and it can run for a while or park at the
plan's bound of active tasks. Meanwhile they can start another. Each
kind of work a person starts says what a second start does while the
first is still open. For an import there are three answers: refuse the
second, end the first, or let both stand.

An import is one file. Two files a person imports are two pieces of
work, and neither says anything about the other. A parked import keeps
the tasks it made and waits for room. Often only an owner or an admin
can make that room, by changing the plan.

## Decision

- **A second import stacks.** It starts beside the first and runs on its
  own record. Each one goes on, parks at its own row, and resumes on its
  own. Nothing a person started is refused or ended by a later start.
- **Every open import shows, one card each.** The tasks page draws a
  card for every import that runs or is parked, newest first, each
  parked one with its own Resume. An ended one stays until it is
  dismissed, and does not show once it ended more than fifteen minutes
  before the page opened.
- **The command line goes on with a parked import.** `tadas imports`
  lists the recent imports with their status, and
  `tadas import --resume <id>` resumes one and follows it, so going on
  never means starting the same rows again.
- **A dismissal is a preference.** The ids of the ended imports a person
  dismissed are kept per org in the portal's local storage, so they are
  per person and per browser. An id that is no longer among the org's
  twenty newest imports is pruned.

## Consequences

- Refusing a second import would leave a person waiting on a parked one
  they may not be able to clear. Ending the first would throw away
  where it stood. Stacking does neither.
- Two imports of one file make each of its tasks twice, since a task's
  id is derived from its import and its row. Resume, on the page or
  with `--resume`, goes on with the parked import instead.
- A plan that rises wakes every import parked on it, and each goes on
  from its own row.
- The page and `tadas imports` read the org's twenty newest imports. An
  import older than those twenty does not show there, though the API
  still reads it by its id, and `tadas import --resume` takes its full
  id.
- Another browser, or another person, still sees an ended import
  someone dismissed, until it is dismissed there or ages out.
- `apps/portal/src/features/imports/ImportStatus.test.ts` holds that two
  parked imports and a running one draw three cards, newest first, each
  parked one with its Resume. `apps/portal/src/store/preferences.test.ts`
  holds that a dismissal survives a reload and is pruned.
  `apps/cli/tests/test_import.py` holds that `--resume` goes on with the
  parked import and starts no other.
