// Pure: the theme a person can pick, what the toggle offers next, and how a
// choice reaches the page (an attribute on the root the theme's CSS reads).

/** "system" follows the operating system's light or dark mode. */
export type ThemePreference = "system" | "light" | "dark";

const ORDER: ThemePreference[] = ["system", "light", "dark"];

/** The toggle cycles: system, light, dark, and back to system. */
export function nextTheme(current: ThemePreference): ThemePreference {
  return ORDER[(ORDER.indexOf(current) + 1) % ORDER.length] ?? "system";
}

export function themeLabel(theme: ThemePreference): string {
  return theme === "system" ? "system theme" : `${theme} theme`;
}

/** A stored value an older or a tampered build left is read as "system". */
export function parseTheme(value: unknown): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

/** Light or dark pins the page; system removes the pin. */
export function applyTheme(root: { dataset: DOMStringMap }, theme: ThemePreference): void {
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}
