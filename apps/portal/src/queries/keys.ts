// One key factory per domain. The first element is the entity name the
// server uses in its `entity_changed` pushes, so the realtime router can
// invalidate by convention instead of by table.
export const keys = {
  me: ["me"] as const,
  users: {
    all: ["user"] as const,
    list: (limit: number) => ["user", "list", limit] as const,
  },
  apiKeys: {
    all: ["api_key"] as const,
    list: (limit: number) => ["api_key", "list", limit] as const,
  },
  tasks: {
    all: ["task"] as const,
    open: (scope: string) => ["task", "open", scope] as const,
    done: (scope: string) => ["task", "done", scope] as const,
  },
};
