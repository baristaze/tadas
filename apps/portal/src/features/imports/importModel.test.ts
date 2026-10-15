import { describe, expect, it } from "vitest";
import type { billing, tasks } from "@tadas/client";
import {
  activeTasksLimit,
  ENDED_SHOWN_MS,
  headline,
  importCard,
  progressLine,
  shownImports,
  skippedLines,
} from "./importModel";

function view(fields: Partial<tasks.ImportView> = {}): tasks.ImportView {
  return {
    id: "i1",
    file_id: "f1",
    status: "running",
    total: 50,
    cursor: 20,
    created: 20,
    skipped: 0,
    row_errors: [],
    park_reason: null,
    fail_reason: null,
    created_at: "2026-09-25T10:00:00Z",
    updated_at: "2026-09-25T10:00:00Z",
    finished_at: null,
    created_by: "u1",
    ...fields,
  };
}

const OPENED = Date.parse("2026-09-25T10:05:00Z");

describe("shownImports", () => {
  it("shows every import that runs or waits, newest first, whatever was dismissed", () => {
    const first = view({ id: "first", status: "parked", park_reason: "plan_limit", created_at: "2026-09-25T09:00:00Z" });
    const second = view({ id: "second", status: "parked", park_reason: "plan_limit", created_at: "2026-09-25T09:30:00Z" });
    const third = view({ id: "third", created_at: "2026-09-25T10:00:00Z" });
    const shown = shownImports([second, first, third], new Set(["first"]), OPENED);
    expect(shown.map((v) => v.id)).toEqual(["third", "second", "first"]);
    expect(shown.map(importCard).map((c) => [c.parked, c.running])).toEqual([
      [false, true],
      [true, false],
      [true, false],
    ]);
    expect(shownImports([], new Set(), OPENED)).toEqual([]);
  });

  it("keeps an import that ended while the page was open until dismissed, and not one long before it", () => {
    const recent = view({ id: "recent", status: "succeeded", finished_at: "2026-09-25T10:04:00Z" });
    expect(shownImports([recent], new Set(), OPENED)).toEqual([recent]);
    expect(shownImports([recent], new Set(["recent"]), OPENED)).toEqual([]);
    const long = new Date(OPENED - ENDED_SHOWN_MS - 1000).toISOString();
    expect(shownImports([view({ status: "succeeded", finished_at: long })], new Set(), OPENED)).toEqual([]);
  });
});

describe("the words", () => {
  it("says how far an import is: created N of M, skipped K", () => {
    expect(progressLine(view())).toBe("Created 20 of 50");
    expect(progressLine(view({ skipped: 1 }))).toBe("Created 20 of 50, skipped 1 row");
    expect(headline(view({ total: null }))).toBe("Importing tasks…");
    expect(headline(view({ skipped: 3 }))).toBe("Importing tasks: created 20 of 50, skipped 3 rows.");
  });

  it("says a park on the plan, the end, a failure, and a cancel", () => {
    const parked = view({ status: "parked", park_reason: "plan_limit", created: 10, cursor: 10 });
    expect(headline(parked)).toBe("Import paused at your plan's limit of active tasks. Created 10 of 50.");
    expect(headline(view({ status: "succeeded", created: 48, skipped: 2 }))).toBe(
      "Imported 48 tasks; skipped 2 rows.",
    );
    expect(headline(view({ status: "failed", fail_reason: "no_title_column" }))).toBe(
      "Import failed: the file has no title column.",
    );
    expect(headline(view({ status: "cancelled", created: 10, cursor: 10 }))).toBe(
      "Import cancelled. Created 10 of 50.",
    );
  });

  it("names the skipped rows it was told of, and counts the rest", () => {
    const skipped = view({ skipped: 22, row_errors: [{ row: 3, reason: "no title" }] });
    expect(skippedLines(skipped)).toEqual(["Row 3: no title", "and 21 rows more"]);
  });
});

describe("activeTasksLimit", () => {
  it("names the org's bound and the first plan above it with more", () => {
    const limits = (active: number | null) => ({ members: 1, api_keys: false, active_tasks: active, storage_bytes: 1 });
    const offer = (plan: "free" | "pro" | "team" | "max", active: number | null) => ({
      plan,
      flat_cents: 0,
      included_seats: null,
      per_seat_cents: 0,
      limits: limits(active),
    });
    const billing = {
      plan: "free",
      limits: limits(10),
      plans: [offer("free", 10), offer("pro", null), offer("team", null), offer("max", null)],
    } as unknown as billing.BillingView;
    expect(activeTasksLimit(billing)).toEqual({
      lever: "active_tasks",
      plan: "free",
      limit: 10,
      suggested_plan: "pro",
    });
  });
});
