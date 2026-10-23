import { useMutation, useQuery } from "@tanstack/react-query";
import type { media } from "@tadas/client";
import { api } from "../app/api";
import { keys } from "./keys";

/** A task shows its first page of files; the page is the server's clamp, wide
 * enough for any task a person works on, and the view says when more exist. */
export const ATTACHMENTS_PAGE_SIZE = 200;

export function useAttachments(taskId: string, enabled = true) {
  return useQuery({
    queryKey: keys.files.ofTask(taskId),
    enabled,
    queryFn: ({ signal }) =>
      api.get<media.FilePageView>(`/v1/tasks/${taskId}/attachments?limit=${ATTACHMENTS_PAGE_SIZE}`, { signal }),
  });
}

/** The API calls an upload starts with and a download asks for. The parts
 * and the confirm are the client's `uploadFile`; the flows in
 * `features/attachments/transfer.ts` take these as their effects. */
export const mediaCalls = {
  start: (taskId: string, body: media.AddFileRequest) =>
    api.post<media.FileView>(`/v1/tasks/${taskId}/attachments`, body, { idempotencyKey: crypto.randomUUID() }),
  issueDownload: (fileId: string, inline = false) =>
    api.get<media.IssuedDownloadView>(`/v1/media/files/${fileId}/download${inline ? "?inline=true" : ""}`),
};

/** A preview link lives five minutes on the server; it is signed again
 * before it runs out, and never while it is fresh. */
const PREVIEW_FRESH_MS = 4 * 60 * 1000;

/** The URL a preview loads: the store's short-lived inline link. */
export function usePreviewUrl(fileId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.files.preview(fileId),
    enabled,
    staleTime: PREVIEW_FRESH_MS,
    refetchInterval: PREVIEW_FRESH_MS,
    queryFn: async () => (await mediaCalls.issueDownload(fileId, true)).url,
  });
}

export function useRemoveAttachment() {
  return useMutation({
    mutationFn: ({ taskId, fileId }: { taskId: string; fileId: string }) =>
      api.del<media.FileView>(`/v1/tasks/${taskId}/attachments/${fileId}`),
  });
}
