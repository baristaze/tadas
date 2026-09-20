import { useQueryClient, type InfiniteData } from "@tanstack/react-query";
import type { TaskPageView, TaskScope, TaskView } from "../../api";
import { useEffect, useMemo, useRef, useState } from "react";
import { keys } from "../../queries/keys";
import {
  useCreateTask,
  useDeleteTask,
  useDoneTasks,
  useMoveTask,
  useOpenTasks,
  useUpdateTask,
} from "../../queries/tasks";
import { useMe, useUsers } from "../../queries/tenancy";
import { usePreferencesStore } from "../../store/preferences";
import { errorMessage } from "../../app/errorMessage";
import { isStale, reorder, STALE_MESSAGE } from "./reorder";
import {
  canAdd,
  canWrite,
  flattenPages,
  MOTION_MS,
  pagesWithOrder,
  pagesWithout,
  pagesWithTaskOnTop,
  pagesWithTaskReplaced,
  taskRow,
  withLeaving,
  type DropSide,
  type Leaving,
} from "./tasksModel";

export interface TaskEdit {
  version: number;
  title: string;
  notes: string;
  assigneeId: string | null;
}

export function useTasksVm() {
  const queryClient = useQueryClient();
  const me = useMe();
  const users = useUsers();
  const scope = usePreferencesStore((s) => s.taskScope);
  const setScope = usePreferencesStore((s) => s.setTaskScope);
  const open = useOpenTasks(scope);
  const done = useDoneTasks(scope);
  const create = useCreateTask();
  const update = useUpdateTask();
  const move = useMoveTask();
  const remove = useDeleteTask();
  const [title, setTitle] = useState("");
  const [leaving, setLeaving] = useState<Leaving[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach(clearTimeout);
  }, []);

  const meId = me.data?.user.id ?? null;
  const usersById = useMemo(() => new Map((users.data ?? []).map((u) => [u.id, u])), [users.data]);
  const openTasks = useMemo(() => flattenPages(open.data), [open.data]);
  const openView = useMemo(() => withLeaving(openTasks, leaving), [openTasks, leaving]);
  const doneTasks = useMemo(() => flattenPages(done.data), [done.data]);
  const leavingIds = useMemo(() => new Set(leaving.map((l) => l.task.id)), [leaving]);

  type Pages = InfiniteData<TaskPageView> | undefined;
  const editOpen = (edit: (data: Pages) => Pages) =>
    queryClient.setQueryData<InfiniteData<TaskPageView>>(keys.tasks.open(scope), edit);
  const editDone = (edit: (data: Pages) => Pages) =>
    queryClient.setQueryData<InfiniteData<TaskPageView>>(keys.tasks.done(scope), edit);
  // The server is the truth: after any write, every task list refetches, in every scope.
  const refresh = () => void queryClient.invalidateQueries({ queryKey: keys.tasks.all });
  // Every write names the version of the task as held here; a write the
  // server refused because the task changed since is said as such. Every
  // write is awaited, and none hands its callbacks to `mutate`: one hook
  // holds one observer, the writes over a task share it, and a second call
  // on an observer drops the first call's callbacks, so a refusal would go
  // unsaid and the row the server wrote unread.
  const fail = (cause: unknown) => {
    setError(isStale(cause) ? STALE_MESSAGE : errorMessage(cause, "Something went wrong; the list was reloaded."));
    refresh();
  };
  const later = (run: () => void) => {
    const timer = setTimeout(() => {
      timers.current.delete(timer);
      run();
    }, MOTION_MS);
    timers.current.add(timer);
  };

  const add = async () => {
    if (!canAdd(title)) return;
    const body = { title: title.trim(), notes: "" };
    setTitle("");
    try {
      const created = await create.mutateAsync(body);
      editOpen((data) => pagesWithTaskOnTop(data, created));
      setError(null);
    } catch (cause) {
      setTitle(body.title);
      fail(cause);
    } finally {
      refresh();
    }
  };

  // Struck through at once; fades out of Open in place while it fades in at the top of Done.
  const complete = async (task: TaskView) => {
    const doneTask: TaskView = { ...task, status: "done", updated_at: new Date().toISOString() };
    const index = openView.findIndex((t) => t.id === task.id);
    setLeaving((current) => [...current.filter((l) => l.task.id !== task.id), { task: doneTask, index }]);
    editOpen((data) => pagesWithout(data, task.id));
    editDone((data) => pagesWithTaskOnTop(data, doneTask));
    later(() => setLeaving((current) => current.filter((l) => l.task.id !== task.id)));
    try {
      // The row the server wrote replaces the optimistic one: it carries
      // the version the write bumped, and without it un-ticking or editing
      // the task before the refetch lands is refused as someone else's
      // change (`reopen` and `add` do the same).
      const completed = await update.mutateAsync({
        id: task.id,
        body: { status: "done", version: task.version },
      });
      editDone((data) => pagesWithTaskOnTop(data, completed));
    } catch (cause) {
      fail(cause);
    } finally {
      refresh();
    }
  };

  const reopen = async (task: TaskView) => {
    editDone((data) => pagesWithout(data, task.id));
    try {
      const reopened = await update.mutateAsync({
        id: task.id,
        body: { status: "open", version: task.version },
      });
      editOpen((data) => pagesWithTaskOnTop(data, reopened));
    } catch (cause) {
      fail(cause);
    } finally {
      refresh();
    }
  };

  const save = async (task: TaskView, edit: TaskEdit) => {
    if (!canAdd(edit.title)) return;
    try {
      const saved = await update.mutateAsync({
        id: task.id,
        body: {
          title: edit.title.trim(),
          notes: edit.notes,
          assignee_id: edit.assigneeId,
          version: edit.version,
        },
      });
      editOpen((data) => pagesWithTaskReplaced(data, saved));
      editDone((data) => pagesWithTaskReplaced(data, saved));
      setEditingId(null);
      setError(null);
    } catch (cause) {
      fail(cause);
      if (isStale(cause)) {
        setError("This task changed while you were editing. Copy your draft before closing and reopening the editor to load the latest task.");
      }
    } finally {
      refresh();
    }
  };

  const destroy = (task: TaskView) => {
    editOpen((data) => pagesWithout(data, task.id));
    editDone((data) => pagesWithout(data, task.id));
    setEditingId(null);
    remove.mutate({ id: task.id, version: task.version }, { onError: fail, onSettled: refresh });
  };

  const drop = (movedId: string, targetId: string, side: DropSide) =>
    void reorder(
      openTasks,
      movedId,
      targetId,
      side,
      {
        move: (id, afterId, version) => move.mutateAsync({ id, afterId, version }),
        showOrder: (order) => editOpen((data) => pagesWithOrder(data, order)),
        showMoved: (task) => editOpen((data) => pagesWithTaskReplaced(data, task)),
        refetch: refresh,
        report: setError,
      },
      (cause) => errorMessage(cause, "The task was not moved; the list was reloaded."),
    );

  const changeScope = (next: TaskScope) => {
    setScope(next);
    setEditingId(null);
  };

  // Only the open copy of a completed task leaves; the done copy is arriving.
  const rowOf = (task: TaskView, group: "open" | "done") => ({
    task,
    row: taskRow(task, usersById, meId),
    leaving: group === "open" && leavingIds.has(task.id),
  });

  return {
    scope,
    setScope: changeScope,
    title,
    setTitle,
    add,
    adding: create.isPending,
    canWrite: canWrite(me.data),
    loading: open.isPending || done.isPending,
    error: error ?? open.error?.message ?? done.error?.message ?? null,
    dismissError: () => setError(null),
    open: openView.map((task) => rowOf(task, "open")),
    done: doneTasks.map((task) => rowOf(task, "done")),
    hasMoreOpen: open.hasNextPage,
    loadingMoreOpen: open.isFetchingNextPage,
    showMoreOpen: () => void open.fetchNextPage(),
    hasMoreDone: done.hasNextPage,
    loadingMoreDone: done.isFetchingNextPage,
    showMoreDone: () => void done.fetchNextPage(),
    editingId,
    startEditing: setEditingId,
    stopEditing: () => setEditingId(null),
    assigneeOptions: [
      { value: "", label: "Unassigned" },
      ...(users.data ?? []).map((u) => ({ value: u.id, label: u.id === meId ? `${u.display_name} (you)` : u.display_name })),
    ],
    complete,
    reopen,
    save,
    destroy,
    drop,
  };
}

export type TasksVm = ReturnType<typeof useTasksVm>;
