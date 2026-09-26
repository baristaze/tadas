// Pure: which list the tasks page shows and what its heading says. A team org
// offers the person's own tasks and the team's; a personal org has one list.
import type { OrgKind, TaskScope } from "../../api";

/** The switch that stands as the page's heading in a team org. */
export const SCOPE_CHOICES: readonly { value: TaskScope; label: string }[] = [
  { value: "mine", label: "My tasks" },
  { value: "team", label: "Team" },
];

/** The list a page shows: in a team org, the one the person picked last; in a
 * personal org, their own. The server's `mine` is every task assigned to the
 * person, or unassigned and created by them, which in an org of one is every
 * task in it. Until the org is known, the pick stands. */
export function shownScope(picked: TaskScope, kind: OrgKind | undefined): TaskScope {
  return kind === "personal" ? "mine" : picked;
}

/** The heading a screen reader hears for the list on screen. */
export function scopeHeading(scope: TaskScope): string {
  return scope === "team" ? "Team tasks" : "My tasks";
}
