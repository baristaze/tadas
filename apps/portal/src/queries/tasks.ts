import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import type {
  AddTaskRequest,
  TaskPageView,
  TaskScope,
  TaskView,
  UpdateTaskRequest,
} from "../api";
import { api } from "../app/api";
import { keys } from "./keys";

export const DONE_PAGE_SIZE = 10;
export const OPEN_LIMIT = 200;

export function useOpenTasks(scope: TaskScope) {
  return useQuery({
    queryKey: keys.tasks.open(scope),
    queryFn: () => api.get<TaskPageView>(`/v1/tasks?status=open&scope=${scope}&limit=${OPEN_LIMIT}`),
  });
}

/** The done list, a page at a time; the next page is the last page's cursor. */
export function useDoneTasks(scope: TaskScope) {
  return useInfiniteQuery({
    queryKey: keys.tasks.done(scope),
    initialPageParam: null as string | null,
    getNextPageParam: (last: TaskPageView) => last.next_cursor,
    queryFn: ({ pageParam }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<TaskPageView>(`/v1/tasks?status=done&scope=${scope}&limit=${DONE_PAGE_SIZE}${cursor}`);
    },
  });
}

// Mutations only talk to the server; the list's view model owns the cache edits
// and the motion around them.

export function useCreateTask() {
  return useMutation({
    mutationFn: (body: AddTaskRequest) =>
      api.post<TaskView>("/v1/tasks", body, { idempotencyKey: crypto.randomUUID() }),
  });
}

export function useUpdateTask() {
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateTaskRequest }) =>
      api.patch<TaskView>(`/v1/tasks/${id}`, body),
  });
}

export function useMoveTask() {
  return useMutation({
    mutationFn: ({ id, afterId }: { id: string; afterId: string | null }) =>
      api.post<TaskView>(`/v1/tasks/${id}/move`, { after_id: afterId }),
  });
}

export function useDeleteTask() {
  return useMutation({
    mutationFn: (id: string) => api.del<TaskView>(`/v1/tasks/${id}`),
  });
}
