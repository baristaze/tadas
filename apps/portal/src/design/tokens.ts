// Design tokens: the operator console imports these from the portal.
export const tokens = {
  color: {
    bg: "#f7f7f5",
    surface: "#ffffff",
    text: "#1c1c1a",
    muted: "#6b6b66",
    border: "#e0e0dc",
    accent: "#2b5bd7",
    accentText: "#ffffff",
    danger: "#b42318",
    warningBg: "#fff4e5",
    warningText: "#7a4a00",
  },
  space: { xs: "4px", sm: "8px", md: "16px", lg: "24px", xl: "40px" },
  radius: { sm: "4px", md: "8px" },
  font: {
    family: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    size: { sm: "13px", md: "15px", lg: "20px", xl: "28px" },
  },
} as const;
