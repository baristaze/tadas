# Changelog

The latest release has its entry here. It lists what changed since the
previous tag. A project that clones Tadas at a release checks out its
tag, such as `git clone --branch v0.7.0`.

## 0.13.0 (2026-09-30)

A clone of Tadas at this tag finds managers that keep their core and
reach their other duties through delegates, and no manager interface
over twenty operations. The pin moves to guideline v0.44.0 by merging
the scaffold. No route, wire type, screen, or migration changes, and
nothing is reversed.

- **The tenancy manager keeps its core and delegates the rest.** It
  holds the seeding, the stage transitions, the grant job, and the
  sweep: 19 operations, `member_context` and `sweep_context` among
  them. Its other duties are four delegates reached through it:
  `tenancy.sign_in`, `tenancy.org`, `tenancy.members`, and
  `tenancy.credentials`. A moved operation keeps its body, its
  permission check, and its order of writes. `get_time_zone` is on the
  org delegate, and what two duties ask of the plan is in
  `tenancy/impl/plan.py`. (#190)
- **The tasks manager does the same.** It keeps the task list and the
  sweep's work on it, 19 of the 32 operations it held, and reaches the
  rest through `tasks.attachments`, `tasks.imports`, `tasks.cleanup`,
  and `tasks.reminders`. (#190)
- **The root builds each delegate.** `build_tenancy` and `build_tasks`
  in `om/root.py` build a manager with its delegates. A caller outside
  the namespace names the delegate, as
  `managers.tasks.imports.start_import`. (#190)
- **A manager interface holds at most twenty operations.**
  `make arch-check` passes at v0.44.0, which holds the bound, and no
  `max_operations` is set. (#190)
- **The guideline pin moves to v0.44.0.** `main` merges the `scaffold`
  branch at v0.44.0. (#190)

Every release's notes stay on the repository host: <https://github.com/baristaze/tadas/releases>.
