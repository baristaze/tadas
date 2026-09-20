// The ping interval and the load balancer idle timeout come from the one
// shared file; a client test and a service test both assert against it.
import pinned from "../../../../deployment/realtime-timeouts.json";

export const PING_INTERVAL_MS = pinned.ping_interval_seconds * 1000;
export const LOAD_BALANCER_IDLE_TIMEOUT_MS = pinned.load_balancer_idle_timeout_seconds * 1000;
export const DEGRADED_POLL_INTERVAL_MS = 30_000;
export const BACKOFF_BASE_MS = 1_000;
export const BACKOFF_MAX_MS = 30_000;
// A socket that has said hello, or stayed open this long, counts as
// connected; only then does the reconnect backoff start over.
export const STABLE_OPEN_MS = 5_000;

export function backoffDelay(attempt: number): number {
  return Math.min(BACKOFF_BASE_MS * 2 ** Math.max(0, attempt - 1), BACKOFF_MAX_MS);
}
