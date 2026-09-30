# Changelog

The latest release has its entry here. It lists what changed since the
previous tag. A project that clones Tadas at a release checks out its
tag, such as `git clone --branch v0.7.0`.

## 0.12.0 (2026-09-30)

A clone of Tadas at this tag finds documents that say what holds, and
one migration revision per role. The pin moves to guideline v0.43.0 by
merging the scaffold. No route, wire type, or screen changes, and the
schema is the one 0.11.0 has.

- **A database older than this release goes through v0.11.0 first.**
  Each role's chain is one revision, so a database at 0.11.0's heads
  has nothing to apply. The migrate step refuses one behind them: it
  names a revision the chain does not hold. Such a database, or a
  snapshot taken before this release, is migrated at v0.11.0, and then
  moves to this one. A developer's local database behind the head is
  made anew with `make reset`. (#191)
- **Each migration chain is one revision under its head's id.** Core
  folds 49 revisions, activity 11, and queue 15; admin is one already.
  The ids stay: core 202610200100, activity 202610010000, queue
  202610080000, admin 202610210000. A schema dump of a database the
  chain made equals one the fold made. Five tests go with the steps
  they pinned, and three assert what the head keeps. (#191)
- **Each ADR states its decision as it stands, under one date.** 13
  that constrain nothing are removed: 0003, 0004, 0012, 0015, 0017,
  0022, 0023, 0043, 0079 to 0082, and 0084. Four take the name of the
  decision they keep: 0025, 0026, 0067, and 0083. A removed number is
  not reused. (#191)
- **The changelog holds the latest release.** The rows of
  `specs/architecture.md` and the comments say what is, in the present
  tense. (#191)
- **The position's expand and contract is in flight.** A task's
  `position` column, its two triggers, and the deprecated field of
  `TaskView` serve the release before. ADR 0050 names what that release
  reads and writes, and the contract step that drops them. (#191)
- **The guideline pin moves to v0.43.0.** `main` merges the `scaffold`
  branch at v0.43.0, which brings the skill `docs-compact` with its
  tests, and the scaffold's ADRs without an Alternatives section. ADR
  0030 is a row of ADR 0002. `make arch-check` passes at v0.43.0.
  (#189)

Every release's notes stay on the repository host: <https://github.com/baristaze/tadas/releases>.
