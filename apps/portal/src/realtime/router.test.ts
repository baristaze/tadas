import { QueryClient, type QueryKey } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { keys } from "../queries/keys";
import { parseEnvelope } from "./envelopes";
import { reminderOf, routeEnvelope } from "./router";

function recording() {
  const queryClient = new QueryClient();
  const seen: QueryKey[] = [];
  queryClient.invalidateQueries = (filters) => {
    seen.push(filters?.queryKey ?? []);
    return Promise.resolve();
  };
  return { queryClient, seen };
}

function pushOf(kind: string) {
  const envelope = parseEnvelope(
    JSON.stringify({
      type: "event",
      sent_at: null,
      topic: "entity_changed",
      payload: { kind, target_id: "x", seq: 3, actor_id: "u1" },
    }),
  );
  expect(envelope).not.toBeNull();
  return envelope!;
}

/** Every kind the service pushes on the entity_changed topic. */
const SERVER_KINDS = [
  "tasks.task.created",
  "tasks.task.updated",
  "tasks.task.deleted",
  "tasks.task.reminded",
  "slack.connection.created",
  "slack.connection.updated",
  "slack.connection.deleted",
  "tenancy.api_key.created",
  "tenancy.api_key.deleted",
  "tenancy.membership.updated",
  "tenancy.session.revoked",
  "tenancy.user.created",
  "tenancy.user.updated",
  "tenancy.user.deleted",
];

/** Every key some query reads under, with one sample argument per factory. */
function queryKeys(node: unknown): QueryKey[] {
  if (typeof node === "function") return [(node as (arg: unknown) => QueryKey)("sample")];
  if (Array.isArray(node)) return [node as QueryKey];
  if (typeof node === "object" && node !== null) return Object.values(node).flatMap(queryKeys);
  return [];
}

const isPrefixOf = (prefix: QueryKey, key: QueryKey) =>
  prefix.length <= key.length && prefix.every((part, index) => Object.is(part, key[index]));

describe("routeEnvelope", () => {
  it("invalidates queries by the entity name inside the push's kind, ignoring unknown fields", () => {
    const { queryClient, seen } = recording();
    const envelope = parseEnvelope(
      JSON.stringify({
        type: "event",
        sent_at: null,
        topic: "entity_changed",
        payload: { kind: "tenancy.api_key.created", target_id: "x", seq: 3, added_later: 1 },
      }),
    );
    expect(envelope).not.toBeNull();
    expect(routeEnvelope(queryClient, envelope!)).toEqual({ invalidated: [keys.apiKeys.all] });
    expect(seen).toEqual([keys.apiKeys.all]);
  });

  it("refreshes who the user is and their places when a membership changes, since the role rides both", () => {
    // A user demoted to viewer loses the add, edit, and drag controls on the
    // push, not on the next reload.
    const { queryClient, seen } = recording();
    expect(routeEnvelope(queryClient, pushOf("tenancy.membership.updated"))).toEqual({
      invalidated: [keys.me, keys.myMemberships.all],
    });
    expect(seen).toEqual([keys.me, keys.myMemberships.all]);
  });

  it("refreshes who the user is when a user changes, since the name rides the me query", () => {
    // Renaming yourself from another client changes a row of the member list
    // and the name in the header; the header reads `me`.
    const { queryClient, seen } = recording();
    const outcome = routeEnvelope(queryClient, pushOf("tenancy.user.updated"));
    expect(outcome).toEqual({ invalidated: [keys.users.all, keys.me] });
    expect(seen).toEqual([keys.users.all, keys.me]);
  });

  it("invalidates nothing for a revoked session, which no query reads", () => {
    // This session's own revocation arrives as a 4401 close, not as a push.
    const { queryClient, seen } = recording();
    expect(routeEnvelope(queryClient, pushOf("tenancy.session.revoked"))).toEqual({ invalidated: [] });
    expect(seen).toEqual([]);
  });

  it("routes every kind the server pushes to a key some query reads under", () => {
    const used = queryKeys(keys);
    for (const kind of SERVER_KINDS) {
      const { queryClient } = recording();
      for (const routed of routeEnvelope(queryClient, pushOf(kind)).invalidated) {
        expect(used.some((key) => isPrefixOf(routed, key)), `${kind} routes to ${JSON.stringify(routed)}`).toBe(true);
      }
    }
  });

  it("refreshes the task lists when a reminder goes out, since the task's version moved on", () => {
    const { queryClient, seen } = recording();
    expect(routeEnvelope(queryClient, pushOf("tasks.task.reminded"))).toEqual({ invalidated: [keys.tasks.all] });
    expect(seen).toEqual([keys.tasks.all]);
  });

  it("refreshes the Slack connection on each of its pushes", () => {
    for (const action of ["created", "updated", "deleted"]) {
      const { queryClient, seen } = recording();
      routeEnvelope(queryClient, pushOf(`slack.connection.${action}`));
      expect(seen).toHaveLength(1);
      expect(isPrefixOf(seen[0]!, keys.slack.connection)).toBe(true);
    }
  });

  it("ignores frames that are not pushes and rejects malformed ones", () => {
    const queryClient = new QueryClient();
    const pong = parseEnvelope(JSON.stringify({ type: "pong", sent_at: null }));
    expect(routeEnvelope(queryClient, pong!)).toEqual({ invalidated: [] });
    expect(parseEnvelope("not json")).toBeNull();
    expect(parseEnvelope(JSON.stringify({ type: "mystery" }))).toBeNull();
    const bare = parseEnvelope(
      JSON.stringify({ type: "event", sent_at: null, topic: "entity_changed", payload: {} }),
    );
    expect(routeEnvelope(queryClient, bare!)).toEqual({ invalidated: [] });
  });
});

describe("reminderOf", () => {
  it("names the task a reminder push is about", () => {
    expect(reminderOf(pushOf("tasks.task.reminded"))).toBe("x");
  });

  it("is null for every other push and every other frame", () => {
    expect(reminderOf(pushOf("tasks.task.updated"))).toBeNull();
    expect(reminderOf(pushOf("slack.connection.updated"))).toBeNull();
    expect(reminderOf(parseEnvelope(JSON.stringify({ type: "pong", sent_at: null, seq: 1 }))!)).toBeNull();
    const other = parseEnvelope(
      JSON.stringify({
        type: "event",
        sent_at: null,
        topic: "presence",
        payload: { kind: "tasks.task.reminded", target_id: "x", seq: 3 },
      }),
    );
    expect(reminderOf(other!)).toBeNull();
  });
});
