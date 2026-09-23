// One key factory per domain. The first element is the entity name the
// server uses in its `entity_changed` pushes, so the realtime router can
// invalidate by convention; an entity the convention does not reach on its
// own (a membership, read through `me`; a user, read through `me` as well as
// its own list) is named in the router's table instead.
export const keys = {
  me: ["me"] as const,
  // The person's places across orgs, read with the session under the
  // identity stage. No push names it; a switch drops it with every other key.
  myMemberships: {
    all: ["my_membership"] as const,
    list: (limit: number) => ["my_membership", "list", limit] as const,
  },
  users: {
    all: ["user"] as const,
    list: (limit: number) => ["user", "list", limit] as const,
  },
  apiKeys: {
    all: ["api_key"] as const,
    list: (limit: number) => ["api_key", "list", limit] as const,
  },
  // Files: a task's attachments and the org's usage, both refreshed by a
  // `media.file.*` push, since the entity is `file`.
  files: {
    all: ["file"] as const,
    ofTask: (taskId: string) => ["file", "task", taskId] as const,
    usage: ["file", "usage"] as const,
    // Outside "file": a file's bytes never change, so a push about the list
    // has no reason to sign its previews again.
    preview: (fileId: string) => ["file_preview", fileId] as const,
  },
  tasks: {
    all: ["task"] as const,
    open: (scope: string) => ["task", "open", scope] as const,
    done: (scope: string) => ["task", "done", scope] as const,
  },
};
