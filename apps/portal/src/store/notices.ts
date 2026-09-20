// Transient notices: what a screen says when a write failed and there is no
// row to show it on. Purely client side; an entry leaves when dismissed or
// after a while on its own.
import { create } from "zustand";

export const NOTICE_TTL_MS = 8_000;

export interface Notice {
  id: string;
  message: string;
}

interface NoticesState {
  notices: Notice[];
  /** Adds one; returns its id. */
  notify: (message: string) => string;
  dismiss: (id: string) => void;
}

let sequence = 0;

export const useNoticesStore = create<NoticesState>()((set, get) => ({
  notices: [],
  notify: (message) => {
    sequence += 1;
    const id = `notice-${sequence}`;
    set((s) => ({ notices: [...s.notices, { id, message }] }));
    setTimeout(() => get().dismiss(id), NOTICE_TTL_MS);
    return id;
  },
  dismiss: (id) => set((s) => ({ notices: s.notices.filter((n) => n.id !== id) })),
}));

/** For code outside React: the one store's `notify`. */
export function notify(message: string): string {
  return useNoticesStore.getState().notify(message);
}
