import { describe, expect, it } from "vitest";
import { SCOPE_CHOICES, scopeHeading, shownScope } from "./scopeModel";

describe("the list the tasks page shows", () => {
  it("is the one picked in a team org", () => {
    expect(shownScope("team", "team")).toBe("team");
    expect(shownScope("mine", "team")).toBe("mine");
  });

  it("is always the person's own in a personal org", () => {
    expect(shownScope("team", "personal")).toBe("mine");
    expect(shownScope("mine", "personal")).toBe("mine");
  });

  it("keeps the pick until the org is known", () => {
    expect(shownScope("team", undefined)).toBe("team");
  });

  it("names the switch's two sides and the heading behind them", () => {
    expect(SCOPE_CHOICES.map((choice) => choice.label)).toEqual(["My tasks", "Team"]);
    expect(scopeHeading("mine")).toBe("My tasks");
    expect(scopeHeading("team")).toBe("Team tasks");
  });
});
