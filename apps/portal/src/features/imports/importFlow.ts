// The start of an import, with its effects handed in, so it runs in a test
// without React, the network, or a browser: the CSV file's upload begun on
// the API under the import's purpose, its parts sent straight to the store by
// the URLs the API signed and the upload confirmed (the client's
// `uploadFile`), and the import started naming it. An upload that stopped
// goes on under its file's id, sending only what the store does not hold. The
// rows are read by the worker; this returns as soon as the import is
// accepted, and the page follows it by what the channel pushes.
import type { media, tasks } from "@tadas/client";

export const CSV_TYPE = "text/csv";

export interface ImportEffects {
  startFile(body: media.AddFileRequest): Promise<media.FileView>;
  /** The parts of a started upload the store does not hold, then its confirm. */
  send(file: File, fileId: string, contentType: string): Promise<media.FileView>;
  start(body: tasks.StartImportRequest): Promise<tasks.ImportView>;
}

export async function startImport(file: File, effects: ImportEffects, stoppedId?: string): Promise<tasks.ImportView> {
  // A browser names a CSV file's type as it likes (Windows says Excel); the
  // import takes the one type, and the name's extension is what the API holds.
  const fileId =
    stoppedId ?? (await effects.startFile({ name: file.name, content_type: CSV_TYPE, size_bytes: file.size })).id;
  const stored = await effects.send(file, fileId, CSV_TYPE);
  return effects.start({ file_id: stored.id });
}
