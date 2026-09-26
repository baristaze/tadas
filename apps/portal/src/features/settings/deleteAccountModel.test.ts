import { describe, expect, it } from "vitest";
import { ApiError } from "../../api";
import { confirms, GONE_LINE, listed, ownedAlone, refusalText } from "./deleteAccountModel";

const acme = { id: "o1", name: "Acme", slug: "acme" };
const globex = { id: "o2", name: "Globex", slug: "globex" };

function lastOwner(...orgs: (typeof acme)[]) {
  return new ApiError(409, "last_owner", "you are the last owner", "req_1", undefined, null, null, orgs);
}

describe("delete account model", () => {
  it("goes on only once the account's email is typed, space and case forgiven", () => {
    expect(confirms("", "bob@example.test")).toBe(false);
    expect(confirms("bob@example", "bob@example.test")).toBe(false);
    expect(confirms("  Bob@Example.TEST ", "bob@example.test")).toBe(true);
    expect(confirms("bob@example.test", undefined)).toBe(false);
  });

  it("says what becomes of the data, backups included", () => {
    expect(GONE_LINE).toBe("Gone now, and gone from backups within 7 days.");
  });

  it("names every org the person is the last owner of, and what to do", () => {
    expect(refusalText(lastOwner(acme))).toBe(
      "You are the last owner of Acme. Make someone else an owner of it first.",
    );
    expect(refusalText(lastOwner(acme, globex))).toBe(
      "You are the last owner of Acme and Globex. Make someone else an owner of each first.",
    );
    expect(ownedAlone(lastOwner(acme))).toEqual([acme]);
  });

  it("says any other refusal in the server's words", () => {
    const operator = new ApiError(403, "operator_role_held", "an operator's account is kept", "req_2");
    expect(refusalText(operator)).toBe("An operator's account is kept.");
    expect(ownedAlone(operator)).toEqual([]);
  });

  it("lists names the way a sentence does", () => {
    expect(listed([])).toBe("");
    expect(listed(["A"])).toBe("A");
    expect(listed(["A", "B", "C"])).toBe("A, B, and C");
  });
});
