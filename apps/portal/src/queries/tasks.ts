import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import type {
  AddTaskRequest,
  MoveTaskRequest,
  TaskPageView,
  TaskScope,
  TaskStatus,
  TaskView,
  UpdateTaskRequest,
} from "../api";
import { api } from "../app/api";
import { keys } from "./keys";

export const DONE_PAGE_SIZE = 10;
export const OPEN_PAGE_SIZE = 200;

/** A list a page at a time; the next page is the last page's cursor, and the
 * server says when there is none. Both lists page the same way; only the
 * page size differs, since the open list is the one on screen whole. */
function useTaskPages(status: TaskStatus, scope: TaskScope, pageSize: number) {
  return useInfiniteQuery({
    queryKey: status === "open" ? keys.tasks.open(scope) : keys.tasks.done(scope),
    initialPageParam: null as string | null,
    getNextPageParam: (last: TaskPageView) => last.next_cursor,
    queryFn: ({ pageParam }) => {
      const cursor = pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : "";
      return api.get<TaskPageView>(`/v1/tasks?status=${status}&scope=${scope}&limit=${pageSize}${cursor}`);
    },
  });
}

export function useOpenTasks(scope: TaskScope) {
  return useTaskPages("open", scope, OPEN_PAGE_SIZE);
}

export function useDoneTasks(scope: TaskScope) {
  return useTaskPages("done", scope, DONE_PAGE_SIZE);
}

// Mutations only talk to the server; the list's view model owns the cache edits
// and the motion around them. Every write names the version of the task the
// view model holds: the server refuses a write over a task that changed since
// (409 `version_mismatch`), and the view model reloads the list.

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
    mutationFn: ({ id, afterId, version }: { id: string; afterId: string | null; version: number }) =>
      api.post<TaskView>(`/v1/tasks/${id}/move`, { after_id: afterId, version } satisfies MoveTaskRequest),
  });
}

export function useDeleteTask() {
  return useMutation({
    // A DELETE has no body, so the version rides the query string.
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      api.del<TaskView>(`/v1/tasks/${id}?version=${version}`),
  });
}
