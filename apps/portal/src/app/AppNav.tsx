// The bar above every signed-in page. On the left, the org chip: its name goes
// home to the task list, its caret switches org. On the right, the gear goes
// to Settings and the account menu holds who is signed in, the theme, and
// Sign out. The live channel's state is the dot in the bottom-right corner.
import { Link, useLocation } from "react-router-dom";
import { AccountMenu } from "./AccountMenu";
import { ConnectionDot } from "./ConnectionDot";
import { OrgChip } from "./OrgChip";

export function AppNav() {
  const inSettings = useLocation().pathname.startsWith("/settings");
  return (
    <nav className="tadas-nav" aria-label="Main">
      <OrgChip />
      <div className="tadas-nav-end">
        <Link
          to="/settings"
          aria-label="Settings"
          title="Settings"
          aria-current={inSettings ? "page" : undefined}
          className="tadas-icon-button"
        >
          <GearIcon />
        </Link>
        <AccountMenu />
      </div>
      <ConnectionDot />
    </nav>
  );
}

function GearIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M6.6 1.75h2.8l.4 1.9 1.2.7 1.85-.6 1.4 2.4-1.45 1.3v1.1l1.45 1.3-1.4 2.4-1.85-.6-1.2.7-.4 1.9H6.6l-.4-1.9-1.2-.7-1.85.6-1.4-2.4L3.2 8.55v-1.1L1.75 6.15l1.4-2.4L5 4.35l1.2-.7z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <circle cx="8" cy="8" r="2" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}
