// The live channel's state as a small dot pinned to the bottom-right corner;
// its label shows on hover or keyboard focus.
import { useState } from "react";
import { tokens } from "../design/tokens";
import { useConnectionStore } from "../store/connection";
import { indicatorFor } from "./connectionIndicator";

export function ConnectionDot() {
  const status = useConnectionStore((s) => s.status);
  const [hovered, setHovered] = useState(false);
  const { tone, label } = indicatorFor(status);
  return (
    <div
      role="status"
      aria-label={label}
      tabIndex={0}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
      style={{ position: "fixed", right: tokens.space.md, bottom: tokens.space.md, padding: tokens.space.xs, zIndex: 10 }}
    >
      <span
        style={{
          display: "block",
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: tone === "live" ? tokens.color.live : tokens.color.pending,
          boxShadow: `0 0 0 2px ${tokens.color.surface}`,
        }}
      />
      {hovered ? (
        <span
          role="tooltip"
          style={{
            position: "absolute",
            right: 0,
            bottom: "100%",
            marginBottom: tokens.space.xs,
            whiteSpace: "nowrap",
            fontSize: tokens.font.size.sm,
            color: tokens.color.accentText,
            background: tokens.color.text,
            borderRadius: tokens.radius.sm,
            padding: `${tokens.space.xs} ${tokens.space.sm}`,
          }}
        >
          {label}
        </span>
      ) : null}
    </div>
  );
}
