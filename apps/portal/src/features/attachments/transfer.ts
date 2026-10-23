// The two flows that move a file's bytes, with their effects handed in, so
// each runs in a test without React, the network, or a browser download.
//
// An upload starts on the task, then goes the one way a file goes: a
// multipart upload whose parts go straight to the store, each a slice of the
// file PUT to the URL the API signed for its length, then the confirm. An
// upload that stopped goes on under its file's id, and the store is sent only
// the parts it does not hold. A download follows the link the API signed,
// straight from the store. No byte of a file crosses the API.
import type { media } from "@tadas/client";
import { contentTypeOf } from "./attachmentsModel";

/** The store answered a download, and not with a success: the link has
 * expired, or the object is gone. */
export class StoreRefused extends Error {
  constructor(readonly status: number) {
    super(`The store refused the transfer (HTTP ${status}).`);
    this.name = "StoreRefused";
  }
}

export interface UploadEffects {
  start(taskId: string, body: media.AddFileRequest): Promise<media.FileView>;
  /** The parts of a started upload the store does not hold, straight to the
   * store, then its confirm: the client's `uploadFile`, which throws
   * `UploadStopped` with the file's id when the upload stops. */
  send(file: File, fileId: string, contentType: string): Promise<media.FileView>;
}

/** A task's attachment: started on the task and sent, or, given the id of an
 * upload that stopped, sent on from where it stopped. */
export async function uploadAttachment(
  taskId: string,
  file: File,
  effects: UploadEffects,
  stoppedId?: string,
): Promise<media.FileView> {
  const contentType = contentTypeOf(file.name, file.type);
  const fileId =
    stoppedId ??
    (await effects.start(taskId, { name: file.name, content_type: contentType, size_bytes: file.size })).id;
  return effects.send(file, fileId, contentType);
}

export interface DownloadEffects {
  issueDownload(fileId: string): Promise<media.IssuedDownloadView>;
  fetchFromStore(url: string): Promise<{ ok: boolean; status: number; blob(): Promise<Blob> }>;
  save(blob: Blob, name: string): void;
}

/** The bytes are fetched and saved under the file's own name: a link to
 * another origin cannot name the file it saves, and the store names the
 * object by its id. */
export async function downloadAttachment(file: media.FileView, effects: DownloadEffects): Promise<void> {
  const link = await effects.issueDownload(file.id);
  const fetched = await effects.fetchFromStore(link.url);
  if (!fetched.ok) throw new StoreRefused(fetched.status);
  effects.save(await fetched.blob(), file.name);
}

/** Hands a blob to the browser as a download under `name`. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
