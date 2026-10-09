// The task lists in the query cache, written from what the server said about
// one task: the answer to this tab's own write, or the single read a push
// leads to through the hint reader (`taskHintEffects`). Where the task goes is
// `placeTask` in `taskPlacement.ts`; this module reads every cached list, in
// every scope, and writes them back.
//
// Answers can arrive out of order, so one ledger per query client
// (`ledger.ts`), shared by this tab's writes and the reader, keeps the newest
// answer heard of each task. An older version never overwrites a newer one,
// even after the task left the lists; a read issued before a removal never
// brings the task back. A write's answer takes its stamp when it lands.
import type { InfiniteData, QueryClient, QueryKey } from "@tanstack/react-query";
import { ApiError, type MeView, type TaskPageView, type TaskScope, type TaskStatus, type TaskView } from "@tadas/client";
import type { HintEffects } from "../realtime/hints";
import { keys } from "./keys";
import { createLedger, type Ledger } from "./ledger";
import {
  DONE_PAGE_SIZE,
  OPEN_PAGE_SIZE,
  placeTask as placement,
  type PlacementOptions,
  type ScopeLists,
  type TaskChange,
} from "./taskPlacement";

type Pages = InfiniteData<TaskPageView>;

interface Heard {
  ledger: Ledger;
  /** The newest answer placed of each task: the task, or null once a 404
   * took it out. */
  tasks: Map<string, TaskView | null>;
  /** Lists being read while a change was placed: their answer may predate
   * it, so the change is placed again once the read lands. */
  pending: Map<string, Set<string>>;
  unsubscribe(): void;
}

const heards = new WeakMap<QueryClient, Heard>();

function heardOf(queryClient: QueryClient): Heard {
  const held = heards.get(queryClient);
  if (held) return held;
  const created: Heard = { ledger: createLedger(), tasks: new Map(), pending: new Map(), unsubscribe: () => undefined };
  created.unsubscribe = queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== "updated" || event.action.type !== "success" || event.action.manual) return;
    const ids = created.pending.get(event.query.queryHash);
    if (!ids) return;
    created.pending.delete(event.query.queryHash);
    const scope = event.query.queryKey[2] as TaskScope;
    for (const id of ids) {
      const task = created.tasks.get(id);
      if (task === undefined) continue;
      applyToScope(queryClient, created, scope, task ? { task } : { gone: id }, {});
    }
  });
  heards.set(queryClient, created);
  return created;
}

const LIMITS: Record<TaskStatus, number> = { open: OPEN_PAGE_SIZE, done: DONE_PAGE_SIZE };

const listKey = (status: TaskStatus, scope: TaskScope): QueryKey =>
  status === "open" ? keys.tasks.open(scope) : keys.tasks.done(scope);

/** Every scope some task list is cached under. */
function cachedScopes(queryClient: QueryClient): Set<TaskScope> {
  const scopes = new Set<TaskScope>();
  for (const status of ["open", "done"] as const) {
    for (const query of queryClient.getQueryCache().findAll({ queryKey: [keys.tasks.all[0], status] })) {
      scopes.add(query.queryKey[2] as TaskScope);
    }
  }
  return scopes;
}

function applyToScope(
  queryClient: QueryClient,
  heard: Heard,
  scope: TaskScope,
  change: TaskChange,
  options: PlacementOptions,
): void {
  const meId = queryClient.getQueryData<MeView>(keys.me)?.user.id ?? null;
  const lists: ScopeLists = {
    open: queryClient.getQueryData<Pages>(listKey("open", scope)),
    done: queryClient.getQueryData<Pages>(listKey("done", scope)),
  };
  const placed = placement(lists, change, { scope, meId, limits: LIMITS }, options);
  const id = "task" in change ? change.task.id : change.gone;
  for (const status of ["open", "done"] as const) {
    const key = listKey(status, scope);
    const { data, outcome } = placed[status];
    if (outcome === "invalidate") {
      void queryClient.invalidateQueries({ queryKey: key, exact: true });
      continue;
    }
    if (outcome !== "unchanged") queryClient.setQueryData<Pages>(key, data);
    const query = queryClient.getQueryCache().find({ queryKey: key, exact: true });
    if (query?.state.fetchStatus === "fetching" && !options.optimistic) {
      const ids = heard.pending.get(query.queryHash) ?? new Set<string>();
      ids.add(id);
      heard.pending.set(query.queryHash, ids);
    }
  }
}

/** The archive is read only while it is open, and newest first by a field
 * the lists do not carry, so a task newly archived asks for it to be read
 * again (which reads nothing while it is closed); a task that left it is
 * taken out. */
function applyToArchive(queryClient: QueryClient, id: string, task: TaskView | null): void {
  for (const query of queryClient.getQueryCache().findAll({ queryKey: [keys.tasks.all[0], "archived"] })) {
    const data = query.state.data as TaskPageView | undefined;
    const held = data?.items.find((t) => t.id === id);
    if (task?.archived_at && !task.deleted_at) {
      if (!held || held.version < task.version) void queryClient.invalidateQueries({ queryKey: query.queryKey, exact: true });
    } else if (held && data) {
      queryClient.setQueryData<TaskPageView>(query.queryKey, { ...data, items: data.items.filter((t) => t.id !== id) });
    }
  }
}

/** The next stamp of the ledger: a single read takes one when it is issued,
 * and hands it back with its answer (`since`). */
export function taskStamp(queryClient: QueryClient): number {
  return heardOf(queryClient).ledger.stamp();
}

/** The task as this tab placed it, when that is at or past `version`: a
 * write's answer or a read's, never an optimistic edit, and never a task a
 * 404 took out. Placing puts a task into every cached list, and the ledger
 * places it again into a list read while it was placed, so every list this
 * tab holds already shows it; a push naming that version has nothing to read. */
export function heldTask(queryClient: QueryClient, id: string, version: number): TaskView | null {
  const heard = heardOf(queryClient);
  return heard.ledger.holds(id, version) ? (heard.tasks.get(id) ?? null) : null;
}

export interface PlaceOptions extends PlacementOptions {
  /** The stamp at which the read that answered was issued. */
  since?: number;
}

/** Puts what the server answered for one task into every cached list: a
 * write's answer, or a single read's. An answer older than one already
 * placed, or a read issued before a 404 that landed, is dropped. An
 * optimistic edit is placed as asked and leaves the ledger alone. */
export function placeTask(queryClient: QueryClient, task: TaskView, options: PlaceOptions = {}): void {
  const heard = heardOf(queryClient);
  if (!options.optimistic) {
    if (!heard.ledger.admit(task.id, task.version, options.since ?? heard.ledger.stamp())) return;
    heard.tasks.set(task.id, task);
  }
  for (const scope of cachedScopes(queryClient)) applyToScope(queryClient, heard, scope, { task }, options);
  if (!options.optimistic) applyToArchive(queryClient, task.id, task);
}

export interface RemoveOptions {
  /** The stamp at which the read that answered 404 was issued: a newer
   * answer placed since then wins. */
  since?: number;
  /** A removal made before the server answers. */
  optimistic?: boolean;
}

/** Takes one task out of every cached list: a 404 on its read (deleted, or
 * no longer this org's to see), or a delete before its answer. */
export function removeTask(queryClient: QueryClient, id: string, options: RemoveOptions = {}): void {
  const heard = heardOf(queryClient);
  if (!options.optimistic) {
    if (!heard.ledger.admitGone(id, options.since ?? heard.ledger.stamp())) return;
    heard.tasks.set(id, null);
  }
  for (const scope of cachedScopes(queryClient)) applyToScope(queryClient, heard, scope, { gone: id }, options);
  if (!options.optimistic) applyToArchive(queryClient, id, null);
}

/** Every task list read again, once: for a burst of pushes too large to read
 * task by task, or a write the server refused. */
export function refreshTaskLists(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: keys.tasks.all });
}

/** What the hint reader (`hints.ts`) reaches for to read a task and place it
 * in every list, over the ledger this tab's writes share. Stopping lets go of
 * every answer heard and every list watched, so none is written into a cache
 * read under the next session. */
export function taskHintEffects(
  queryClient: QueryClient,
  read: (id: string) => Promise<TaskView>,
): HintEffects<TaskView> {
  return {
    read,
    isGone: (cause) => cause instanceof ApiError && cause.status === 404,
    holds: (id, version) => heldTask(queryClient, id, version) !== null,
    stamp: () => taskStamp(queryClient),
    place: (task, since) => placeTask(queryClient, task, { since }),
    remove: (id, since) => removeTask(queryClient, id, { since }),
    readCollections: () => refreshTaskLists(queryClient),
    stop() {
      heards.get(queryClient)?.unsubscribe();
      heards.delete(queryClient);
    },
  };
}
