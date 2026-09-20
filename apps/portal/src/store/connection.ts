// The realtime channel's state as the UI sees it; purely client side.
import { create } from "zustand";

export type ConnectionStatus = "connecting" | "open" | "degraded" | "closed";

export interface ConnectionState {
  status: ConnectionStatus;
  failedCycles: number;
  setStatus: (status: ConnectionStatus) => void;
  recordFailure: () => void;
  reset: () => void;
}

export const useConnectionStore = create<ConnectionState>()((set) => ({
  status: "closed",
  failedCycles: 0,
  setStatus: (status) => set({ status }),
  recordFailure: () => set((s) => ({ failedCycles: s.failedCycles + 1 })),
  reset: () => set({ status: "open", failedCycles: 0 }),
}));
