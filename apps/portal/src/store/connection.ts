// The realtime channel's state as the UI sees it; purely client side.
import { create } from "zustand";

export type ConnectionStatus = "connecting" | "open" | "degraded" | "closed";

export interface ConnectionState {
  status: ConnectionStatus;
  failedCycles: number;
  setStatus: (status: ConnectionStatus) => void;
  recordFailure: () => void;
  reset: () => void;
  /** The channel is done: no reconnect follows, and the next one starts fresh. */
  close: () => void;
}

export const useConnectionStore = create<ConnectionState>()((set) => ({
  status: "closed",
  failedCycles: 0,
  setStatus: (status) => set({ status }),
  recordFailure: () => set((s) => ({ failedCycles: s.failedCycles + 1 })),
  reset: () => set({ status: "open", failedCycles: 0 }),
  // The count belongs to the channel that did the failing. Left standing, a
  // sign-out during a reconnect made the next session's very first drop the
  // second failed cycle, which is the degraded banner without a degraded
  // channel; the store never says open without a socket either way.
  close: () => set({ status: "closed", failedCycles: 0 }),
}));
