// Preferences only the UI knows about, kept across visits: which task list
// the person looked at last, the theme they picked (or the system's), which
// sections of the task list they folded, and which ended imports they
// dismissed, per org. Local storage is the right place for a preference; the
// session token is the one thing that never goes there.
import type { tasks } from "@tadas/client";
import { parseTheme, type ThemePreference } from "../app/themeModel";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export const PREFERENCES_STORAGE_KEY = "tadas.portal.preferences";

/** A key of its own that may hold the scope as a bare word. */
export const LEGACY_SCOPE_KEY = "tadas.portal.taskScope";

/** A section of the task list: the open tasks, or the done ones. */
export type TaskSection = "open" | "done";

/** Which sections an org's task list has folded, by org id. An org the
 * person never folded or unfolded anything in has no entry. */
export type FoldedSections = Record<string, Partial<Record<TaskSection, boolean>>>;

/** How a section starts before the person folds or unfolds it: Open
 * unfolded, since it is the work, and Done folded, since it only grows. */
export const FOLDED_AT_FIRST: Record<TaskSection, boolean> = { open: false, done: true };

/** Pure: whether the section is folded in this org. */
export function isFolded(folded: FoldedSections, orgId: string | null, section: TaskSection): boolean {
  return (orgId === null ? undefined : folded[orgId]?.[section]) ?? FOLDED_AT_FIRST[section];
}

/** The ended imports a person dismissed, by org id: per person and per
 * browser, as every preference here is. */
export type DismissedImports = Record<string, string[]>;

/** Pure: the ids an org's dismissed list keeps once the imports it can name
 * are `recent`; the rest are pruned, so the list never outgrows them. */
export function prunedDismissals(dismissed: readonly string[], recent: readonly string[]): string[] {
  const kept = new Set(recent);
  return dismissed.filter((id) => kept.has(id));
}

/** Pure: dismissals read back from storage, keeping only lists of ids. */
export function parseDismissedImports(stored: unknown): DismissedImports {
  if (!stored || typeof stored !== "object" || Array.isArray(stored)) return {};
  const lists = Object.entries(stored).map(([orgId, ids]): [string, string[]] => [
    orgId,
    Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : [],
  ]);
  return Object.fromEntries(lists.filter(([, ids]) => ids.length > 0));
}

interface PreferencesState {
  taskScope: tasks.TaskScope;
  setTaskScope: (scope: tasks.TaskScope) => void;
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
  folded: FoldedSections;
  setFolded: (orgId: string, section: TaskSection, folded: boolean) => void;
  dismissedImports: DismissedImports;
  dismissImport: (orgId: string, importId: string) => void;
  /** Drops the org's dismissed ids that are not among its `recent` imports. */
  pruneDismissedImports: (orgId: string, recent: readonly string[]) => void;
}

/** Pure: the scope a bare word names, and nothing else. */
export function legacyScope(value: string | null): tasks.TaskScope | null {
  return value === "team" || value === "mine" ? value : null;
}

/** Reads the scope kept as a bare word under its own key, once, and drops
 * it; null when there is none or the storage cannot be read. */
export function adoptLegacyScope(storage: Pick<Storage, "getItem" | "removeItem"> | undefined): tasks.TaskScope | null {
  try {
    const scope = legacyScope(storage?.getItem(LEGACY_SCOPE_KEY) ?? null);
    storage?.removeItem(LEGACY_SCOPE_KEY);
    return scope;
  } catch {
    return null;
  }
}

const adopted = adoptLegacyScope(typeof localStorage === "undefined" ? undefined : localStorage);

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      taskScope: adopted ?? "mine",
      setTaskScope: (taskScope) => set({ taskScope }),
      theme: "system",
      setTheme: (theme) => set({ theme }),
      folded: {},
      setFolded: (orgId, section, value) =>
        set((state) => ({ folded: { ...state.folded, [orgId]: { ...state.folded[orgId], [section]: value } } })),
      dismissedImports: {},
      dismissImport: (orgId, importId) =>
        set((state) => {
          const now = state.dismissedImports[orgId] ?? [];
          if (now.includes(importId)) return state;
          return { dismissedImports: { ...state.dismissedImports, [orgId]: [...now, importId] } };
        }),
      pruneDismissedImports: (orgId, recent) =>
        set((state) => {
          const now = state.dismissedImports[orgId];
          if (!now) return state;
          const kept = prunedDismissals(now, recent);
          if (kept.length === now.length) return state;
          const others = Object.fromEntries(Object.entries(state.dismissedImports).filter(([id]) => id !== orgId));
          return { dismissedImports: kept.length > 0 ? { ...others, [orgId]: kept } : others };
        }),
    }),
    {
      name: PREFERENCES_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      // A theme the stored state does not name, or names wrongly, is the
      // system's; a field the store does not know is dropped. A scope that is
      // not one is the default, folds that are not an object are none, and a
      // dismissal that is not a list of ids is dropped.
      merge: (stored, current) => {
        const kept = (stored ?? {}) as Partial<PreferencesState>;
        const taskScope = kept.taskScope === "team" || kept.taskScope === "mine" ? kept.taskScope : current.taskScope;
        const folded = kept.folded && typeof kept.folded === "object" ? kept.folded : {};
        const dismissedImports = parseDismissedImports(kept.dismissedImports);
        return { ...current, theme: parseTheme(kept.theme), taskScope, folded, dismissedImports };
      },
    },
  ),
);
