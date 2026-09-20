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
import {
  canAdd,
  canWrite,
  doneWithout,
  doneWithTaskOnTop,
  doneWithTaskReplaced,
  flattenDone,
  MOTION_MS,
  placement,
  taskRow,
  withLeaving,
  withoutTask,
  withOrder,
  withTaskOnTop,
  withTaskReplaced,
  type DropSide,
  type Leaving,
} from "./tasksModel";

export interface TaskEdit {
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
  const openTasks = useMemo(() => open.data?.items ?? [], [open.data]);
  const openView = useMemo(() => withLeaving(openTasks, leaving), [openTasks, leaving]);
  const doneTasks = useMemo(() => flattenDone(done.data), [done.data]);
  const leavingIds = useMemo(() => new Set(leaving.map((l) => l.task.id)), [leaving]);

  const openKey = keys.tasks.open(scope);
  const doneKey = keys.tasks.done(scope);
  const editOpen = (edit: (page: TaskPageView | undefined) => TaskPageView | undefined) =>
    queryClient.setQueryData<TaskPageView>(openKey, edit);
  const editDone = (
    edit: (data: InfiniteData<TaskPageView> | undefined) => InfiniteData<TaskPageView> | undefined,
  ) => queryClient.setQueryData<InfiniteData<TaskPageView>>(doneKey, edit);
  // The server is the truth: after any write, every task list refetches, in every scope.
  const refresh = () => void queryClient.invalidateQueries({ queryKey: keys.tasks.all });
  const fail = (cause: unknown) => {
    setError(cause instanceof Error ? cause.message : "Something went wrong; the list was reloaded.");
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
      editOpen((page) => withTaskOnTop(page, created));
      setError(null);
    } catch (cause) {
      setTitle(body.title);
      fail(cause);
    } finally {
      refresh();
    }
  };

  // Struck through at once; fades out of Open in place while it fades in at the top of Done.
  const complete = (task: TaskView) => {
    const doneTask: TaskView = { ...task, status: "done", updated_at: new Date().toISOString() };
    const index = openView.findIndex((t) => t.id === task.id);
    setLeaving((current) => [...current.filter((l) => l.task.id !== task.id), { task: doneTask, index }]);
    editOpen((page) => withoutTask(page, task.id));
    editDone((data) => doneWithTaskOnTop(data, doneTask));
    later(() => setLeaving((current) => current.filter((l) => l.task.id !== task.id)));
    update.mutate({ id: task.id, body: { status: "done" } }, { onError: fail, onSettled: refresh });
  };

  const reopen = (task: TaskView) => {
    editDone((data) => doneWithout(data, task.id));
    update.mutate(
      { id: task.id, body: { status: "open" } },
      {
        onSuccess: (reopened) => editOpen((page) => withTaskOnTop(page, reopened)),
        onError: fail,
        onSettled: refresh,
      },
    );
  };

  const save = async (task: TaskView, edit: TaskEdit) => {
    if (!canAdd(edit.title)) return;
    try {
      const saved = await update.mutateAsync({
        id: task.id,
        body: { title: edit.title.trim(), notes: edit.notes, assignee_id: edit.assigneeId },
      });
      editOpen((page) => withTaskReplaced(page, saved));
      editDone((data) => doneWithTaskReplaced(data, saved));
      setEditingId(null);
      setError(null);
    } catch (cause) {
      fail(cause);
    } finally {
      refresh();
    }
  };

  const destroy = (task: TaskView) => {
    editOpen((page) => withoutTask(page, task.id));
    editDone((data) => doneWithout(data, task.id));
    setEditingId(null);
    remove.mutate(task.id, { onError: fail, onSettled: refresh });
  };

  const drop = (movedId: string, targetId: string, side: DropSide) => {
    const result = placement(openTasks, movedId, targetId, side);
    if (!result) return;
    editOpen((page) => withOrder(page, result.order));
    move.mutate({ id: movedId, afterId: result.afterId }, { onError: fail, onSettled: refresh });
  };

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
