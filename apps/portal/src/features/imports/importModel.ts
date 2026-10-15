// Pure: which imports the tasks page shows, and how each is said.
import type { billing, tasks, PlanLimit } from "@tadas/client";

/** How long before the page opened an import may have ended and still show. */
export const ENDED_SHOWN_MS = 15 * 60 * 1000;

/** The imports to show, newest first: every one that runs or waits, and each
 * one that ended, until the person dismisses it. One that ended well before
 * the page opened (`openedAt`) is not news. A second import stacks beside
 * the first, so none a person started leaves the page while it is open. */
export function shownImports(
  items: readonly tasks.ImportView[],
  dismissed: ReadonlySet<string>,
  openedAt: number,
): tasks.ImportView[] {
  return items
    .filter((view) => {
      if (view.finished_at === null) return true;
      if (dismissed.has(view.id)) return false;
      return openedAt - Date.parse(view.finished_at) <= ENDED_SHOWN_MS;
    })
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

/** What one import's card draws. */
export interface ImportCard {
  id: string;
  headline: string;
  running: boolean;
  parked: boolean;
  parkedOnThePlan: boolean;
  ended: boolean;
  failed: boolean;
  skipped: string[];
  /** How far a running import is, when its total is known. */
  percent: number | null;
}

export function importCard(view: tasks.ImportView): ImportCard {
  return {
    id: view.id,
    headline: headline(view),
    running: isRunning(view),
    parked: view.status === "parked",
    parkedOnThePlan: isParkedOnThePlan(view),
    ended: view.finished_at !== null,
    failed: view.status === "failed",
    skipped: skippedLines(view),
    percent: view.total ? Math.round((view.created / view.total) * 100) : null,
  };
}

export function isRunning(view: tasks.ImportView): boolean {
  return view.status === "running";
}

export function isParkedOnThePlan(view: tasks.ImportView): boolean {
  return view.status === "parked" && view.park_reason === "plan_limit";
}

function rows(count: number): string {
  return count === 1 ? "1 row" : `${count} rows`;
}

/** How far an import is: created N of M, skipped K. */
export function progressLine(view: tasks.ImportView): string {
  const total = view.total === null ? "" : ` of ${view.total}`;
  const skipped = view.skipped > 0 ? `, skipped ${rows(view.skipped)}` : "";
  return `Created ${view.created}${total}${skipped}`;
}

const FAILURES: Readonly<Record<string, string>> = {
  file_too_large: "the file is larger than 1 MB.",
  too_many_rows: "the file has more than 5,000 rows.",
  not_csv: "the file is not a CSV file.",
  no_title_column: "the file has no title column.",
  file_gone: "the file was removed before it was read.",
  defect: "something went wrong on our side. Try again later.",
};

/** The one sentence at the head of the import's card. */
export function headline(view: tasks.ImportView): string {
  switch (view.status) {
    case "running":
      return view.total === null ? "Importing tasks…" : `Importing tasks: ${progressLine(view).toLowerCase()}.`;
    case "parked":
      return isParkedOnThePlan(view)
        ? `Import paused at your plan's limit of active tasks. ${progressLine(view)}.`
        : `Import paused. ${progressLine(view)}.`;
    case "succeeded":
      return `Imported ${view.created === 1 ? "1 task" : `${view.created} tasks`}${
        view.skipped > 0 ? `; skipped ${rows(view.skipped)}` : ""
      }.`;
    case "failed":
      return `Import failed: ${FAILURES[view.fail_reason ?? "defect"] ?? FAILURES.defect}`;
    case "cancelled":
      return `Import cancelled. ${progressLine(view)}.`;
    default:
      return progressLine(view);
  }
}

/** The rows the import skipped, as lines: `Row 3: no title`. */
export function skippedLines(view: tasks.ImportView): string[] {
  const named = view.row_errors.map((e) => `Row ${e.row}: ${e.reason}`);
  const more = view.skipped - named.length;
  return more > 0 ? [...named, `and ${rows(more)} more`] : named;
}

const ORDER: readonly billing.Plan[] = ["free", "pro", "team", "max"];

/** The bound an import parked on, in the shape the upgrade dialog reads: the
 * org's plan, its active tasks, and the first plan above it with more. */
export function activeTasksLimit(billing: billing.BillingView): PlanLimit {
  const bound = billing.limits.active_tasks;
  const above = billing.plans
    .filter((offer) => ORDER.indexOf(offer.plan) > ORDER.indexOf(billing.plan))
    .find((offer) => offer.limits.active_tasks === null || (bound !== null && offer.limits.active_tasks > bound));
  return { lever: "active_tasks", plan: billing.plan, limit: bound, suggested_plan: above?.plan ?? null };
}
