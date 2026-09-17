// The bar above every signed-in page: the org, the two destinations, and who is
// signed in. The live channel's state is the dot in the bottom-right corner.
import { NavLink } from "react-router-dom";
import { Muted } from "../design/kit";
import { tokens } from "../design/tokens";
import { useMe } from "../queries/tenancy";
import { ConnectionDot } from "./ConnectionDot";

const linkStyle = ({ isActive }: { isActive: boolean }) => ({
  color: isActive ? tokens.color.text : tokens.color.muted,
  fontWeight: isActive ? 600 : 400,
  textDecoration: "none",
});

export function AppNav() {
  const me = useMe();
  return (
    <nav
      style={{
        display: "flex",
        alignItems: "center",
        gap: tokens.space.lg,
        paddingBottom: tokens.space.md,
        marginBottom: tokens.space.lg,
        borderBottom: `1px solid ${tokens.color.border}`,
      }}
    >
      <strong>{me.data?.org.name ?? "Tadas"}</strong>
      <NavLink to="/" end style={linkStyle}>
        Tasks
      </NavLink>
      <NavLink to="/settings" style={linkStyle}>
        Settings
      </NavLink>
      <Muted style={{ marginLeft: "auto", fontSize: tokens.font.size.sm }}>{me.data?.user.email}</Muted>
      <ConnectionDot />
    </nav>
  );
}
