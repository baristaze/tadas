import { describe, expect, it, vi } from "vitest";
import type { media } from "@tadas/client";
import { downloadAttachment, StoreRefused, uploadAttachment, type DownloadEffects, type UploadEffects } from "./transfer";

const FILE: media.FileView = {
  id: "f1",
  name: "plan.pdf",
  extension: "pdf",
  content_type: "application/pdf",
  size_bytes: 5,
  purpose: "task_attachment",
  subject_id: "t1",
  status: "pending",
  created_at: "2026-09-22T10:00:00Z",
  created_by: "u1",
  deleted_at: null,
};

const picked = new File(["%PDF!"], "plan.pdf", { type: "application/pdf" });

function uploads() {
  const calls: string[] = [];
  const effects: UploadEffects = {
    start: vi.fn(async (taskId, body) => {
      calls.push(`start ${taskId} ${body.name} ${body.content_type} ${body.size_bytes}`);
      return FILE;
    }),
    send: vi.fn(async (file, fileId, contentType) => {
      calls.push(`send ${file.name} ${fileId} ${contentType}`);
      return { ...FILE, status: "stored" as const };
    }),
  };
  return { effects, calls };
}

describe("uploadAttachment", () => {
  it("starts on the task, then sends the parts under the file's id", async () => {
    const { effects, calls } = uploads();
    const stored = await uploadAttachment("t1", picked, effects);
    expect(stored.status).toBe("stored");
    expect(calls).toEqual(["start t1 plan.pdf application/pdf 5", "send plan.pdf f1 application/pdf"]);
  });

  it("goes on with an upload that stopped and starts no other", async () => {
    const { effects, calls } = uploads();
    await uploadAttachment("t1", picked, effects, "f1");
    expect(calls).toEqual(["send plan.pdf f1 application/pdf"]);
    expect(effects.start).not.toHaveBeenCalled();
  });

  it("names a type the browser left empty from the extension", async () => {
    const { effects, calls } = uploads();
    await uploadAttachment("t1", new File(["%PDF!"], "notes.md"), effects);
    expect(calls[0]).toBe("start t1 notes.md text/markdown 5");
  });
});

function downloads(storeStatus = 200) {
  const saved: [Blob, string][] = [];
  const effects: DownloadEffects = {
    issueDownload: vi.fn(async () => ({ url: "https://store.example.test/o", expires_at: "2026-09-22T10:15:00Z" })),
    fetchFromStore: vi.fn(async () => ({
      ok: storeStatus < 300,
      status: storeStatus,
      blob: async () => new Blob(["from the store"]),
    })),
    save: (blob, name) => void saved.push([blob, name]),
  };
  return { effects, saved };
}

describe("downloadAttachment", () => {
  it("follows the signed link and saves under the file's own name", async () => {
    const { effects, saved } = downloads();
    await downloadAttachment(FILE, effects);
    expect(effects.fetchFromStore).toHaveBeenCalledWith("https://store.example.test/o");
    expect(await saved[0]![0].text()).toBe("from the store");
    expect(saved[0]![1]).toBe("plan.pdf");
  });

  it("says a link the store refused and saves nothing", async () => {
    const { effects, saved } = downloads(403);
    await expect(downloadAttachment(FILE, effects)).rejects.toBeInstanceOf(StoreRefused);
    await expect(downloadAttachment(FILE, effects)).rejects.toThrow("HTTP 403");
    expect(saved).toEqual([]);
  });
});
