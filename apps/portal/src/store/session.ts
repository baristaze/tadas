// Client state only the UI knows about: the session token and who it is for.
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SessionState {
  token: string | null;
  orgSlug: string | null;
  setSession: (token: string, orgSlug: string) => void;
  clear: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      token: null,
      orgSlug: null,
      setSession: (token, orgSlug) => set({ token, orgSlug }),
      clear: () => set({ token: null, orgSlug: null }),
    }),
    { name: "tadas.portal.session" },
  ),
);
