// Preferences only the UI knows about, kept across visits: which task list
// the person looked at last, and the theme they picked (or the system's). Local storage is the right place for a
// preference; the session token is the one thing that never goes there.
import type { TaskScope } from "../api";
import { parseTheme, type ThemePreference } from "../app/themeModel";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export const PREFERENCES_STORAGE_KEY = "tadas.portal.preferences";

/** An earlier build kept the scope under this key as a bare word. */
export const LEGACY_SCOPE_KEY = "tadas.portal.taskScope";

interface PreferencesState {
  taskScope: TaskScope;
  setTaskScope: (scope: TaskScope) => void;
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
}

/** Pure: the scope an earlier build left as a bare word, and nothing else. */
export function legacyScope(value: string | null): TaskScope | null {
  return value === "team" || value === "mine" ? value : null;
}

/** Reads the scope an earlier build left under its own key, once, and drops
 * it; null when there is none or the storage cannot be read. */
export function adoptLegacyScope(storage: Pick<Storage, "getItem" | "removeItem"> | undefined): TaskScope | null {
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
    }),
    {
      name: PREFERENCES_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      // A theme the stored state does not name, or names wrongly, is the system's.
      merge: (stored, current) => {
        const kept = (stored ?? {}) as Partial<PreferencesState>;
        return { ...current, ...kept, theme: parseTheme(kept.theme) };
      },
    },
  ),
);
