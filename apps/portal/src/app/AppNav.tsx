// The bar above every signed-in page: the org chip, the two destinations, who
// is signed in, and the theme. The live channel's state is the dot in the
// bottom-right corner.
import { NavLink } from "react-router-dom";
import { useMe } from "../queries/tenancy";
import { ConnectionDot } from "./ConnectionDot";
import { OrgChip } from "./OrgChip";
import { ThemeToggle } from "./ThemeToggle";

export function AppNav() {
  const me = useMe();
  return (
    <nav className="tadas-nav">
      <OrgChip />
      <NavLink to="/" end className="tadas-nav-link">
        Tasks
      </NavLink>
      <NavLink to="/settings" className="tadas-nav-link">
        Settings
      </NavLink>
      <span className="tadas-nav-email">{me.data?.user.email}</span>
      <ThemeToggle />
      <ConnectionDot />
    </nav>
  );
}
