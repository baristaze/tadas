import { describe, expect, it } from "vitest";
import { ApiError } from "../../api";
import { checkSignUp, signUpRefusal, type SignUpForm } from "./signUpModel";

const form: SignUpForm = {
  email: "dee@example.test",
  displayName: "Dee",
  password: "long-enough",
};

describe("checkSignUp", () => {
  it("passes a whole form, which names no org", () => {
    expect(checkSignUp(form)).toEqual({ ok: true, message: null });
    expect(Object.keys(form).sort()).toEqual(["displayName", "email", "password"]);
  });

  it("names the first field that is missing or malformed", () => {
    expect(checkSignUp({ ...form, email: "dee" }).message).toMatch(/email/);
    expect(checkSignUp({ ...form, email: "dee@localhost" }).message).toMatch(/email/);
    expect(checkSignUp({ ...form, displayName: " " }).message).toMatch(/name people see/);
    expect(checkSignUp({ ...form, password: "short" }).message).toMatch(/8 characters/);
  });
});

describe("signUpRefusal", () => {
  it("points a held email at sign-in", () => {
    const held = new ApiError(409, "conflict", "an account with this email exists; sign in instead", "r1");
    expect(signUpRefusal(held, "x")).toEqual({
      message: "An account with this email exists. Sign in instead.",
      signIn: true,
    });
  });

  it("says any other refusal as the server did, as a sentence", () => {
    const other = new ApiError(409, "unique_key_taken", "a key is taken", "r2");
    expect(signUpRefusal(other, "x")).toEqual({ message: "A key is taken.", signIn: false });
  });

  it("says a closed door plainly", () => {
    expect(signUpRefusal(new ApiError(404, "not_found", "not found", "r3"), "x").message).toMatch(/closed/);
  });
});
