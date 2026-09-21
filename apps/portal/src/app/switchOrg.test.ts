import { describe, expect, it, vi } from "vitest";
import { ApiError, type IssuedSessionView } from "../api";
import { chipChoices } from "./orgChipModel";
import { switchOrg, type SwitchEffects } from "./switchOrg";

const org = (id: string, name: string) => ({ id, name, slug: id, created_at: "2026-09-01T00:00:00Z" });
const user = { id: "u", email: "ann@example.test", display_name: "Ann", created_at: "2026-09-01T00:00:00Z" };
const issued: IssuedSessionView = {
  token: "ses_new",
  expires_at: "2026-09-02T00:00:00Z",
  org: org("beta", "Beta"),
  user,
  role: "member",
};

function effects(exchange: SwitchEffects["exchange"]) {
  const adopt = vi.fn<SwitchEffects["adopt"]>();
  return {
    exchange: vi.fn(async () => {
      // The old session must still be held while the server is asked.
      expect(adopt).not.toHaveBeenCalled();
      return exchange();
    }),
    adopt,
    report: vi.fn<SwitchEffects["report"]>(),
  };
}

describe("switchOrg", () => {
  it("exchanges first, then drops the old tenant and takes up the new session", async () => {
    const e = effects(() => Promise.resolve(issued));
    await expect(switchOrg(e)).resolves.toBe("switched");
    expect(e.adopt).toHaveBeenCalledWith(issued);
    expect(e.report).not.toHaveBeenCalled();
  });

  it("leaves a 401 to the client, which has signed the tab out already", async () => {
    const e = effects(() => Promise.reject(new ApiError(401, "not_authenticated", "session revoked", "r1")));
    await expect(switchOrg(e)).resolves.toBe("signed_out");
    expect(e.adopt).not.toHaveBeenCalled();
    expect(e.report).not.toHaveBeenCalled();
  });

  it("stays in the current org on any other refusal, and says it", async () => {
    const e = effects(() => Promise.reject(new ApiError(403, "not_authorized", "no longer a member", "r2")));
    await expect(switchOrg(e)).resolves.toBe("refused");
    expect(e.adopt).not.toHaveBeenCalled();
    expect(e.report).toHaveBeenCalledWith("no longer a member (r2)");
  });
});

describe("chipChoices", () => {
  const place = (id: string, name: string) => ({ org: org(id, name), user, role: "member" as const });

  it("offers nothing with one place, or before the lists arrive", () => {
    expect(chipChoices([place("acme", "Acme")], "acme")).toEqual({ canSwitch: false, others: [] });
    expect(chipChoices(undefined, "acme").canSwitch).toBe(false);
    expect(chipChoices([place("acme", "Acme")], undefined).canSwitch).toBe(false);
  });

  it("offers the other places by name, never the current one", () => {
    const choices = chipChoices([place("zeta", "Zeta"), place("acme", "Acme"), place("beta", "Beta")], "acme");
    expect(choices.canSwitch).toBe(true);
    expect(choices.others.map((m) => m.org.name)).toEqual(["Beta", "Zeta"]);
  });
});
