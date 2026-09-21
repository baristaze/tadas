import { describe, expect, it } from "vitest";
import { ApiError } from "../../api";
import { checkSignUp, isSlug, signUpRefusal, slugAfterNameChange, suggestSlug, type SignUpForm } from "./signUpModel";

const form: SignUpForm = {
  email: "dee@example.test",
  displayName: "Dee",
  password: "long-enough",
  orgName: "Dee's Bakery",
  orgSlug: "dees-bakery",
};

describe("checkSignUp", () => {
  it("passes a whole form", () => {
    expect(checkSignUp(form)).toEqual({ ok: true, message: null });
  });

  it("names the first field that is missing or malformed", () => {
    expect(checkSignUp({ ...form, email: "dee" }).message).toMatch(/email/);
    expect(checkSignUp({ ...form, email: "dee@localhost" }).message).toMatch(/email/);
    expect(checkSignUp({ ...form, displayName: " " }).message).toMatch(/name people see/);
    expect(checkSignUp({ ...form, password: "short" }).message).toMatch(/8 characters/);
    expect(checkSignUp({ ...form, orgName: "" }).message).toMatch(/organization/);
    expect(checkSignUp({ ...form, orgSlug: "Dees Bakery" }).message).toMatch(/short name/);
  });
});

describe("the slug", () => {
  it("is suggested from the org's name", () => {
    expect(suggestSlug("Dee's Bakery")).toBe("dee-s-bakery");
    expect(suggestSlug("  Café Zürich  ")).toBe("cafe-zurich");
    expect(suggestSlug("!!!")).toBe("");
    expect(suggestSlug("a".repeat(60))).toHaveLength(48);
  });

  it("follows the name until the person types in it", () => {
    expect(slugAfterNameChange("Acme Labs", "acme", false)).toBe("acme-labs");
    expect(slugAfterNameChange("Acme Labs", "mine", true)).toBe("mine");
  });

  it("is what the server accepts", () => {
    expect(isSlug("acme-labs")).toBe(true);
    expect(isSlug("acme--labs")).toBe(false);
    expect(isSlug("-acme")).toBe(false);
    expect(isSlug("")).toBe(false);
    expect(isSlug("a".repeat(49))).toBe(false);
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

  it("says a taken slug as the server did, as a sentence", () => {
    const taken = new ApiError(409, "conflict", "org slug 'acme' is taken", "r2");
    expect(signUpRefusal(taken, "x")).toEqual({ message: "Org slug 'acme' is taken.", signIn: false });
  });

  it("says a closed door plainly", () => {
    expect(signUpRefusal(new ApiError(404, "not_found", "not found", "r3"), "x").message).toMatch(/closed/);
  });
});
