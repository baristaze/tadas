import { describe, expect, it } from "vitest";
import { applyTheme, nextTheme, parseTheme, themeLabel } from "./themeModel";

describe("the theme", () => {
  it("cycles system, light, dark, and back", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });

  it("reads anything it does not know as the system's", () => {
    expect(parseTheme("dark")).toBe("dark");
    expect(parseTheme("light")).toBe("light");
    expect(parseTheme("sepia")).toBe("system");
    expect(parseTheme(undefined)).toBe("system");
  });

  it("pins the root for light or dark and unpins it for system", () => {
    const root = { dataset: {} as DOMStringMap };
    applyTheme(root, "dark");
    expect(root.dataset.theme).toBe("dark");
    applyTheme(root, "light");
    expect(root.dataset.theme).toBe("light");
    applyTheme(root, "system");
    expect(root.dataset.theme).toBeUndefined();
  });

  it("names each choice for the toggle's label", () => {
    expect(themeLabel("system")).toBe("system theme");
    expect(themeLabel("dark")).toBe("dark theme");
  });
});
