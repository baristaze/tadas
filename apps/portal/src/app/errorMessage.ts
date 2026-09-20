// Pure: the one line a screen shows for a failed call. An API refusal quotes
// the request id, so the person can say which call it was; anything else is
// the caller's own words, or the error's when it has some.
import { ApiError } from "../api";

export function errorMessage(caught: unknown, fallback: string): string {
  if (caught instanceof ApiError) return `${caught.message} (${caught.requestId ?? "no id"})`;
  if (caught instanceof Error && caught.message) return caught.message;
  return fallback;
}
