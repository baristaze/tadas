// The theme switch in the chrome: system, light, dark, in turn. The icon shows
// the current choice; the label says what a press does.
import { IconButton } from "../design/kit";
import { usePreferencesStore } from "../store/preferences";
import { nextTheme, themeLabel, type ThemePreference } from "./themeModel";

export function ThemeToggle() {
  const theme = usePreferencesStore((s) => s.theme);
  const setTheme = usePreferencesStore((s) => s.setTheme);
  const next = nextTheme(theme);
  return (
    <IconButton label={`Using the ${themeLabel(theme)}; switch to the ${themeLabel(next)}`} onClick={() => setTheme(next)}>
      <ThemeIcon theme={theme} />
    </IconButton>
  );
}

function ThemeIcon({ theme }: { theme: ThemePreference }) {
  const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      {theme === "light" ? (
        <>
          <circle cx="8" cy="8" r="3" {...stroke} />
          <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" {...stroke} />
        </>
      ) : theme === "dark" ? (
        <path d="M13.5 9.5A5.75 5.75 0 0 1 6.5 2.5a5.75 5.75 0 1 0 7 7z" {...stroke} />
      ) : (
        <>
          <rect x="1.75" y="2.75" width="12.5" height="8.5" rx="1.5" {...stroke} />
          <path d="M5.5 13.75h5M8 11.25v2.5" {...stroke} />
        </>
      )}
    </svg>
  );
}
