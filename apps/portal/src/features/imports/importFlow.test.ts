import { describe, expect, it, vi } from "vitest";
import { UploadStopped, type media, type tasks } from "@tadas/client";
import { CSV_TYPE, startImport, type ImportEffects } from "./importFlow";

const FILE: media.FileView = {
  id: "f1",
  name: "tasks.csv",
  extension: "csv",
  content_type: CSV_TYPE,
  size_bytes: 12,
  purpose: "task_import",
  subject_id: null,
  status: "pending",
  created_at: "2026-09-25T10:00:00Z",
  created_by: "u1",
  deleted_at: null,
};

const STARTED: tasks.ImportView = {
  id: "i1",
  file_id: "f1",
  status: "running",
  total: null,
  cursor: 0,
  created: 0,
  skipped: 0,
  row_errors: [],
  park_reason: null,
  fail_reason: null,
  created_at: "2026-09-25T10:00:00Z",
  updated_at: "2026-09-25T10:00:00Z",
  finished_at: null,
  created_by: "u1",
};

// Windows names a CSV file as Excel's; the import sends the one type it takes.
const picked = new File(["title\nShip\n"], "tasks.csv", { type: "application/vnd.ms-excel" });

function effectsFor(sendFails = false) {
  const calls: string[] = [];
  const effects: ImportEffects = {
    startFile: vi.fn(async (body) => {
      calls.push(`file ${body.name} ${body.content_type} ${body.size_bytes}`);
      return FILE;
    }),
    send: vi.fn(async (file, fileId, contentType) => {
      calls.push(`send ${file.name} ${fileId} ${contentType}`);
      if (sendFails) throw new UploadStopped(fileId, "part 1 did not reach the store");
      return { ...FILE, status: "stored" as const };
    }),
    start: vi.fn(async (body) => {
      calls.push(`import ${body.file_id}`);
      return STARTED;
    }),
  };
  return { effects, calls };
}

describe("startImport", () => {
  it("uploads the file's parts to the store, confirms it, and starts its import", async () => {
    const { effects, calls } = effectsFor();
    expect(await startImport(picked, effects)).toEqual(STARTED);
    expect(calls).toEqual(["file tasks.csv text/csv 11", "send tasks.csv f1 text/csv", "import f1"]);
  });

  it("goes on with an upload that stopped and starts no other file", async () => {
    const { effects, calls } = effectsFor();
    await startImport(picked, effects, "f1");
    expect(calls).toEqual(["send tasks.csv f1 text/csv", "import f1"]);
  });

  it("starts no import when the upload stops", async () => {
    const { effects, calls } = effectsFor(true);
    await expect(startImport(picked, effects)).rejects.toBeInstanceOf(UploadStopped);
    expect(calls).not.toContain("import f1");
  });
});
