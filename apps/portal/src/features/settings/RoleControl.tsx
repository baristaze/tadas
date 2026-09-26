import type { Role } from "../../api";
import { Caret, Menu, MenuItemRadio } from "../../design/kit";
import type { MemberRow } from "./settingsModel";

/** A member's role in the member table. A member who may change it gets a
 * small menu of the roles they may give, the current one checked; everyone
 * else reads the role. The menu opens on a click, Enter, Space, or the
 * arrows, and closes on Escape or outside, as every menu of the kit does. */
export function RoleControl({
  row,
  onChange,
  busy,
}: {
  row: MemberRow;
  onChange: (userId: string, role: Role) => void;
  busy: boolean;
}) {
  if (row.role === null) return <span>—</span>;
  if (row.roles.length === 0) return <span data-role={row.role}>{row.role}</span>;
  const current = row.role;
  return (
    <Menu
      label={`Role of ${row.name}`}
      triggerLabel={`Role of ${row.name}: ${current}. Change`}
      triggerClassName="tadas-menu-trigger tadas-role-trigger"
      minWidth={140}
      disabled={busy}
      trigger={
        <>
          <span data-role={current}>{current}</span>
          <Caret />
        </>
      }
    >
      {row.roles.map((role) => (
        <MenuItemRadio
          key={role}
          checked={role === current}
          onSelect={() => {
            if (role !== current) onChange(row.id, role);
          }}
        >
          {role}
        </MenuItemRadio>
      ))}
    </Menu>
  );
}
