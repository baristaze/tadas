// The current org in the chrome. It opens a menu: the other places to switch
// to, when there are any, and a new team org.
import { tokens } from "../design/tokens";
import { placeNote } from "./orgChipModel";
import { useOrgChipVm } from "./useOrgChipVm";

const itemStyle = {
  display: "flex",
  justifyContent: "space-between",
  gap: tokens.space.md,
  width: "100%",
  font: "inherit",
  textAlign: "left",
  background: "none",
  border: "none",
  borderRadius: tokens.radius.sm,
  padding: tokens.space.sm,
  cursor: "pointer",
  color: tokens.color.text,
} as const;

export function OrgChip() {
  const vm = useOrgChipVm();
  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={vm.toggle}
        disabled={!vm.canOpen || vm.switching}
        aria-haspopup="menu"
        aria-expanded={vm.open}
        title={vm.canSwitch ? "Switch or create an organization" : "Create an organization"}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: tokens.space.xs,
          font: "inherit",
          fontWeight: 600,
          color: tokens.color.text,
          background: tokens.color.surface,
          border: `1px solid ${tokens.color.border}`,
          borderRadius: 999,
          padding: `${tokens.space.xs} ${tokens.space.md}`,
          cursor: vm.canOpen ? "pointer" : "default",
        }}
      >
        {vm.orgName}
        {vm.personal ? (
          <span style={{ color: tokens.color.muted, fontWeight: 400, fontSize: tokens.font.size.sm }}>personal</span>
        ) : null}
        <span aria-hidden style={{ color: tokens.color.muted }}>▾</span>
      </button>
      {vm.open ? (
        <div
          role="menu"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            zIndex: 10,
            minWidth: 240,
            background: tokens.color.surface,
            border: `1px solid ${tokens.color.border}`,
            borderRadius: tokens.radius.md,
            boxShadow: "0 4px 16px rgba(0, 0, 0, 0.08)",
            padding: tokens.space.xs,
          }}
        >
          {vm.canSwitch ? (
            <div style={{ padding: tokens.space.sm, fontSize: tokens.font.size.sm, color: tokens.color.muted }}>
              Switch to
            </div>
          ) : null}
          {vm.others.map((membership) => (
            <button
              key={membership.org.id}
              type="button"
              role="menuitem"
              onClick={() => void vm.pick(membership)}
              style={itemStyle}
            >
              <span>{membership.org.name}</span>
              <span style={{ color: tokens.color.muted, fontSize: tokens.font.size.sm }}>{placeNote(membership)}</span>
            </button>
          ))}
          <div
            style={{
              borderTop: vm.canSwitch ? `1px solid ${tokens.color.border}` : "none",
              marginTop: vm.canSwitch ? tokens.space.xs : 0,
              paddingTop: vm.canSwitch ? tokens.space.xs : 0,
            }}
          >
            <button type="button" role="menuitem" onClick={vm.newOrg} style={itemStyle}>
              <span>New organization…</span>
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
