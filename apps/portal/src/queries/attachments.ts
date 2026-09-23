import { useMutation, useQuery } from "@tanstack/react-query";
import type {
  AddFileRequest,
  FilePageView,
  FileView,
  IssuedDownloadView,
  IssuedUploadView,
  StorageUsageView,
} from "../api";
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
      api.get<FilePageView>(`/v1/tasks/${taskId}/attachments?limit=${ATTACHMENTS_PAGE_SIZE}`, { signal }),
  });
}

export function useStorageUsage(enabled = true) {
  return useQuery({
    queryKey: keys.files.usage,
    enabled,
    queryFn: ({ signal }) => api.get<StorageUsageView>("/v1/media/usage", { signal }),
  });
}

/** The API calls an upload and a download are made of. The flows in
 * `features/attachments/transfer.ts` take these as their effects. */
export const mediaCalls = {
  start: (taskId: string, body: AddFileRequest) =>
    api.post<FileView>(`/v1/tasks/${taskId}/attachments`, body, { idempotencyKey: crypto.randomUUID() }),
  issueUpload: (fileId: string) => api.post<IssuedUploadView>(`/v1/media/files/${fileId}/upload`),
  putContent: (fileId: string, bytes: Blob, contentType: string) =>
    api.putBytes<FileView>(`/v1/media/files/${fileId}/content`, bytes, contentType),
  confirm: (fileId: string) => api.post<FileView>(`/v1/media/files/${fileId}/confirm`),
  issueDownload: (fileId: string) => api.get<IssuedDownloadView>(`/v1/media/files/${fileId}/download`),
  getContent: (fileId: string) => api.getBlob(`/v1/media/files/${fileId}/content`),
};

export function useRemoveAttachment() {
  return useMutation({
    mutationFn: ({ taskId, fileId }: { taskId: string; fileId: string }) =>
      api.del<FileView>(`/v1/tasks/${taskId}/attachments/${fileId}`),
  });
}
