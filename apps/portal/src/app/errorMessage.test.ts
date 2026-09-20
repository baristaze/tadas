import { describe, expect, it } from "vitest";
import { ApiError, RequestTimeout } from "../api";
import { errorMessage } from "./errorMessage";

describe("errorMessage", () => {
  it("quotes the request id of an API refusal", () => {
    expect(errorMessage(new ApiError(409, "conflict", "already exists", "req_1"), "no")).toBe(
      "already exists (req_1)",
    );
    expect(errorMessage(new ApiError(502, "unknown_error", "Bad Gateway", null), "no")).toBe(
      "Bad Gateway (no id)",
    );
  });

  it("uses the error's own words for a timeout or any other error", () => {
    expect(errorMessage(new RequestTimeout("POST", "/v1/api-keys", 30_000), "no")).toBe(
      "POST /v1/api-keys did not finish within 30000 ms",
    );
    expect(errorMessage(new Error("offline"), "no")).toBe("offline");
  });

  it("falls back to the caller's words when there are none", () => {
    expect(errorMessage(new Error(""), "The key was not created.")).toBe("The key was not created.");
    expect(errorMessage("what", "The key was not created.")).toBe("The key was not created.");
    expect(errorMessage(undefined, "The key was not created.")).toBe("The key was not created.");
  });
});
