import { useMutation, useQuery } from "@tanstack/react-query";
import type { media, tasks } from "@tadas/client";
import { api } from "../app/api";
import { keys } from "./keys";

/** The org's newest imports; the tasks page shows each one that runs, waits,
 * or ended lately, so a few imports stacked at once all fit. A push about any
 * import refreshes it, since its key starts with the entity. */
export const RECENT_IMPORTS = 20;

export function useRecentImports(enabled = true) {
  return useQuery({
    queryKey: keys.imports.recent,
    enabled,
    queryFn: ({ signal }) => api.get<tasks.ImportPageView>(`/v1/tasks/imports?limit=${RECENT_IMPORTS}`, { signal }),
  });
}

/** The API calls an import's start is made of. The flow in
 * `features/imports/importFlow.ts` takes these as its effects, beside the
 * media calls that move the bytes. */
export const importCalls = {
  startFile: (body: media.AddFileRequest) =>
    api.post<media.FileView>("/v1/tasks/imports/files", body, { idempotencyKey: crypto.randomUUID() }),
  start: (body: tasks.StartImportRequest) =>
    api.post<tasks.ImportView>("/v1/tasks/imports", body, { idempotencyKey: crypto.randomUUID() }),
};

export function useResumeImport() {
  return useMutation({
    mutationFn: (id: string) => api.post<tasks.ImportView>(`/v1/tasks/imports/${id}/resume`),
  });
}

/** Ends a running or a parked import; the tasks it made stay. */
export function useCancelImport() {
  return useMutation({
    mutationFn: (id: string) => api.post<tasks.ImportView>(`/v1/tasks/imports/${id}/cancel`),
  });
}
