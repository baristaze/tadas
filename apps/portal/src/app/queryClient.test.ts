// The app's one retry is the transport client's. This pins the other half of
// that: the query library does not add a second round of attempts on top.
import { describe, expect, it } from "vitest";
import { queryClient } from "./queryClient";

describe("the shared query cache", () => {
  it("does not retry, so the transport client's attempts are all there are", () => {
    const defaults = queryClient.getDefaultOptions();
    expect(defaults.queries?.retry).toBe(false);
    expect(defaults.mutations?.retry).toBe(false);
  });
});
